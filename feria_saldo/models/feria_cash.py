from decimal import Decimal

from odoo import api, fields, models
from odoo.exceptions import UserError

from ..feria_tools import CENT, UUID_RE, FeriaError, serial_env
from .feria_movement import CHAIN_LOCK

KINDS = {'count', 'close'}


class FeriaCash(models.Model):
    _name = 'feria.cash'
    _description = 'Recuento o cierre de caja'
    _order = 'id desc'
    _rec_name = 'uuid'

    uuid = fields.Char(string='UUID', required=True, readonly=True, copy=False, index=True)
    kind = fields.Selection(
        [('count', 'Recuento'), ('close', 'Cierre de caja')], string='Tipo', required=True, readonly=True, index=True,
    )
    date = fields.Datetime(string='Fecha', required=True, readonly=True, default=fields.Datetime.now)
    period_start = fields.Datetime(string='Desde', readonly=True, help='Cierre anterior (vacio si es el primero)')
    last_movement_id = fields.Integer(string='Ultimo movimiento incluido', readonly=True)
    currency_id = fields.Many2one('res.currency', string='Moneda', required=True, readonly=True)
    opening_float = fields.Monetary(string='Fondo inicial', readonly=True, help='Lo que se dejo en caja en el cierre anterior')
    recharges = fields.Monetary(string='Recargas cobradas', readonly=True)
    refunds = fields.Monetary(string='Devoluciones', readonly=True, help='Recargas anuladas: dinero que se devuelve')
    expected = fields.Monetary(string='Esperado en caja', readonly=True)
    counted = fields.Monetary(string='Contado', readonly=True)
    difference = fields.Monetary(string='Diferencia', readonly=True, help='Contado menos esperado')
    kept = fields.Monetary(string='Dejado para el dia siguiente', readonly=True)
    withdrawn = fields.Monetary(string='Retirado', readonly=True, help='Contado menos lo dejado')
    sales = fields.Monetary(string='Ventas (cobros)', readonly=True, help='Informativo: no mueve efectivo')
    movements_count = fields.Integer(string='Operaciones', readonly=True)
    note = fields.Char(string='Nota', readonly=True)

    _uuid_unique = models.Constraint('UNIQUE (uuid)', 'Ya existe un registro con este UUID.')
    _amounts_valid = models.Constraint(
        'CHECK (counted >= 0 AND kept >= 0 AND kept <= counted)', 'Importes de caja no validos.',
    )

    # ------------------------------------------------------------------
    # Append-only, like the movements
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.context.get('feria_cash_register'):
            raise UserError('Los recuentos y cierres de caja se hacen desde la pantalla de caja.')
        return super().create(vals_list)

    def write(self, vals):
        raise UserError('Los registros de caja no se pueden modificar.')

    def unlink(self):
        raise UserError('Los registros de caja no se pueden borrar.')

    # ------------------------------------------------------------------
    # Cash that should be in the drawer
    # ------------------------------------------------------------------
    @api.model
    def _summary(self):
        """What the drawer should hold now, in the caller's transaction.

        Cash enters with RECARGAR and leaves when a recarga is cancelled. COBRAR spends wallet
        balance, so it moves no cash and is only reported as sales. A period starts right after
        the last movement included in the previous cierre, so nothing is counted twice or missed.
        """
        cr = self.env.cr
        cr.execute("SELECT kept::text, date, last_movement_id FROM feria_cash WHERE kind = 'close' ORDER BY id DESC LIMIT 1")
        last = cr.fetchone()
        opening = Decimal(last[0]) if last else Decimal(0)
        after_id = last[2] if last else 0
        cr.execute(
            """
            SELECT COALESCE(SUM(m.amount) FILTER (WHERE m.type = 'RECARGAR'), 0)::text,
                   COALESCE(SUM(m.amount) FILTER (WHERE m.type = 'ANULACION' AND o.type = 'RECARGAR'), 0)::text,
                   (COALESCE(SUM(m.amount) FILTER (WHERE m.type = 'COBRAR'), 0)
                    - COALESCE(SUM(m.amount) FILTER (WHERE m.type = 'ANULACION' AND o.type = 'COBRAR'), 0))::text,
                   COUNT(*), COALESCE(MAX(m.id), %s)
              FROM feria_movement m
              LEFT JOIN feria_movement o ON o.id = m.ref_movement_id
             WHERE m.state = 'confirmed' AND m.id > %s
            """,
            [after_id, after_id],
        )
        recharges, refunds, sales, count, last_id = cr.fetchone()
        recharges, refunds, sales = Decimal(recharges), Decimal(refunds), Decimal(sales)
        return {
            'period_start': last[1] if last else False,
            'last_movement_id': last_id,
            'opening_float': opening,
            'recharges': recharges,
            'refunds': refunds,
            'expected': opening + recharges - refunds,
            'sales': sales,
            'movements_count': count,
            'currency': self.env['feria.movement']._feria_currency().name,
        }

    @api.model
    def _summary_to_api(self, summary):
        result = {key: (str(value.quantize(CENT)) if isinstance(value, Decimal) else value) for key, value in summary.items()}
        result['period_start'] = summary['period_start'] and summary['period_start'].isoformat() + 'Z' or None
        return result

    def _to_api(self):
        self.ensure_one()
        money = lambda value: str(Decimal(str(value or 0)).quantize(CENT))  # noqa: E731
        return {
            'uuid': self.uuid,
            'kind': self.kind,
            'date': self.date.isoformat() + 'Z',
            'currency': self.currency_id.name,
            'opening_float': money(self.opening_float),
            'recharges': money(self.recharges),
            'refunds': money(self.refunds),
            'expected': money(self.expected),
            'counted': money(self.counted),
            'difference': money(self.difference),
            'kept': money(self.kept),
            'withdrawn': money(self.withdrawn),
            'sales': money(self.sales),
            'movements_count': self.movements_count,
            'note': self.note or None,
        }

    # ------------------------------------------------------------------
    # Registration service (idempotent by uuid, serialized with the movements)
    # ------------------------------------------------------------------
    @api.model
    def _cash_register(self, *, uuid, kind, counted, kept=None, note=None):
        """Store a recuento or a cierre de caja. Returns its API form ('duplicate': True on a replay)."""
        with serial_env(self.env) as env:
            record, duplicate = env['feria.cash']._cash_register_locked(
                uuid=uuid, kind=kind, counted=counted, kept=kept, note=note,
            )
            result = record._to_api()
        result['duplicate'] = duplicate
        return result

    @api.model
    def _cash_register_locked(self, *, uuid, kind, counted, kept, note):
        if not isinstance(uuid, str) or not UUID_RE.match(uuid):
            raise FeriaError('VALIDATION_ERROR', 'uuid must be a lowercase RFC 4122 uuid')
        if kind not in KINDS:
            raise FeriaError('VALIDATION_ERROR', 'kind must be count or close')
        if kind == 'close':
            if kept is None:
                raise FeriaError('VALIDATION_ERROR', 'kept is required to close the cash desk')
            if kept > counted:
                raise FeriaError('VALIDATION_ERROR', 'You cannot leave more than what was counted')
        else:
            kept = Decimal(0)

        def replay(existing):
            same = (
                existing.kind == kind
                and Decimal(str(existing.counted)).quantize(CENT) == counted
                and Decimal(str(existing.kept)).quantize(CENT) == kept
            )
            if not same:
                raise FeriaError('DUPLICATE', 'This uuid was already used with different data', 409, record=existing._to_api())
            return existing, True

        existing = self.search([('uuid', '=', uuid)], limit=1)
        if existing:
            return replay(existing)

        # Same lock as the movements: nothing can slip between the totals and the cierre.
        self.env.cr.execute("SELECT pg_advisory_xact_lock(%s)", [CHAIN_LOCK])
        existing = self.search([('uuid', '=', uuid)], limit=1)
        if existing:
            return replay(existing)

        summary = self._summary()
        record = self.with_context(feria_cash_register=True).create({
            'uuid': uuid,
            'kind': kind,
            'period_start': summary['period_start'] or False,
            'last_movement_id': summary['last_movement_id'],
            'currency_id': self.env['feria.movement']._feria_currency().id,
            'opening_float': summary['opening_float'],
            'recharges': summary['recharges'],
            'refunds': summary['refunds'],
            'expected': summary['expected'],
            'counted': counted,
            'difference': counted - summary['expected'],
            'kept': kept,
            'withdrawn': counted - kept,
            'sales': summary['sales'],
            'movements_count': summary['movements_count'],
            'note': note or False,
        })
        return record, False
