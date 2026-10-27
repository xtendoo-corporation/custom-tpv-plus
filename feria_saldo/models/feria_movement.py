import uuid as uuid_lib
from decimal import Decimal

import psycopg2.errors

from odoo import api, fields, models
from odoo.exceptions import UserError

from ..feria_tools import CENT, UUID_RE, FeriaError, normalize_code, serial_env, sha256_hex

CLOCK_SKEW_SECONDS = 300
CHAIN_LOCK = 727001  # advisory lock key serializing the global hash chain
# Types a kiosk may register; AJUSTE and ANULACION are back office only.
KIOSK_TYPES = {'COBRAR', 'RECARGAR'}
SIGN = {'COBRAR': -1, 'RECARGAR': 1}


def _dec(value):
    return Decimal(str(value or 0)).quantize(CENT)


class FeriaMovement(models.Model):
    _name = 'feria.movement'
    _description = 'Movimiento de saldo'
    _order = 'id desc'
    _rec_name = 'uuid'

    uuid = fields.Char(string='UUID', required=True, readonly=True, copy=False, index=True)
    partner_id = fields.Many2one('res.partner', string='Contacto', required=True, readonly=True, index=True, ondelete='restrict')
    code_used = fields.Char(string='Codigo usado', readonly=True)
    type = fields.Selection(
        [
            ('COBRAR', 'Cobrar'),
            ('RECARGAR', 'Recargar'),
            ('AJUSTE', 'Ajuste'),
            ('ANULACION', 'Anulacion'),
        ],
        string='Tipo', required=True, readonly=True, index=True,
    )
    currency_id = fields.Many2one('res.currency', string='Moneda', required=True, readonly=True)
    amount = fields.Monetary(string='Importe', required=True, readonly=True)
    signed_amount = fields.Monetary(string='Efecto en saldo', required=True, readonly=True)
    balance_after = fields.Monetary(string='Saldo tras movimiento', readonly=True)
    created_at_device = fields.Datetime(string='Fecha en el cliente', readonly=True)
    received_at = fields.Datetime(string='Recibido', required=True, readonly=True, default=fields.Datetime.now)
    state = fields.Selection(
        [('pending', 'Pendiente'), ('confirmed', 'Confirmado'), ('rejected', 'Rechazado')],
        string='Estado', required=True, readonly=True, default='confirmed', index=True,
    )
    sequence = fields.Integer(string='Secuencia', readonly=True)
    hash_prev = fields.Char(readonly=True)
    hash = fields.Char(readonly=True)
    ref_movement_id = fields.Many2one('feria.movement', string='Movimiento anulado', readonly=True, ondelete='restrict')
    note = fields.Char(string='Nota', readonly=True)

    _uuid_unique = models.Constraint('UNIQUE (uuid)', 'Ya existe un movimiento con este UUID.')
    _amount_positive = models.Constraint('CHECK (amount > 0)', 'El importe debe ser positivo.')
    _single_cancellation = models.UniqueIndex(
        "(ref_movement_id) WHERE type = 'ANULACION'",
        'Este movimiento ya esta anulado.',
    )

    # ------------------------------------------------------------------
    # Append-only
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.context.get('feria_register'):
            raise UserError('Los movimientos solo se crean con el registro de movimientos (recarga manual o API).')
        return super().create(vals_list)

    def write(self, vals):
        raise UserError('Los movimientos no se pueden modificar: use una anulacion o un ajuste.')

    def unlink(self):
        raise UserError('Los movimientos no se pueden borrar: use una anulacion o un ajuste.')

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @api.model
    def _feria_param(self, name, default=''):
        """Single place that reads settings: Odoo 20 replaced get_param by typed getters."""
        return self.env['ir.config_parameter'].sudo().get_str(f'feria.{name}', str(default))

    @api.model
    def _feria_currency(self):
        currency_id = int(self._feria_param('currency_id', 0) or 0)
        currency = self.env['res.currency'].browse(currency_id).exists() if currency_id else self.env['res.currency']
        return currency or self.env.company.currency_id

    @staticmethod
    def _hash_of(prev, uuid, partner_id, type_, amount, created_at_device, sequence):
        return sha256_hex(
            prev, uuid, partner_id, type_, _dec(amount),
            created_at_device.strftime('%Y-%m-%dT%H:%M:%S') if created_at_device else '',
            sequence or '',
        )

    def _compute_hash(self, prev):
        self.ensure_one()
        return self._hash_of(
            prev, self.uuid, self.partner_id.id, self.type, self.amount,
            self.created_at_device, self.sequence,
        )

    def _to_api(self):
        self.ensure_one()
        return {
            'uuid': self.uuid,
            'status': self.state,
            'type': self.type,
            'amount': str(_dec(self.amount)),
            'signed_amount': str(_dec(self.signed_amount)),
            'balance_after': str(_dec(self.balance_after)),
            'currency': self.currency_id.name,
            'contact_id': self.partner_id.id,
            'code_used': self.code_used or None,
            'created_at_device': self.created_at_device and self.created_at_device.isoformat() + 'Z' or None,
            'received_at': self.received_at.isoformat() + 'Z',
            'sequence': self.sequence or None,
            'hash': self.hash or None,
            'ref_uuid': self.ref_movement_id.uuid or None,
            'note': self.note or None,
        }

    # ------------------------------------------------------------------
    # Registration service
    # ------------------------------------------------------------------
    @api.model
    def _feria_register(self, *, uuid, partner_id, type, amount=None, code_used=None,
                        created_at_device=None, sequence=None, ref_uuid=None,
                        note=None, direction=None, from_kiosk=False):
        """Register one movement, serialized per contact and durable on return.

        Runs on its own READ COMMITTED transaction: takes the chain lock, then the contact
        lock, checks idempotency, rules and balance, inserts and commits before returning.
        Returns the API representation of the movement ('duplicate': True on a replay).
        Raises FeriaError for every business rejection (nothing is stored then).
        """
        with serial_env(self.env) as env:
            movement, duplicate = env['feria.movement']._feria_register_locked(
                uuid=uuid, partner_id=partner_id, type=type, amount=amount, code_used=code_used,
                created_at_device=created_at_device, sequence=sequence, ref_uuid=ref_uuid,
                note=note, direction=direction, from_kiosk=from_kiosk,
            )
            result = movement._to_api()
        result['duplicate'] = duplicate
        return result

    @api.model
    def _feria_register_locked(self, *, uuid, partner_id, type, amount, code_used,
                               created_at_device, sequence, ref_uuid, note, direction, from_kiosk):
        cr = self.env.cr
        if not isinstance(uuid, str) or not UUID_RE.match(uuid):
            raise FeriaError('VALIDATION_ERROR', 'uuid must be a lowercase RFC 4122 uuid')
        if type not in dict(self._fields['type'].selection):
            raise FeriaError('VALIDATION_ERROR', 'unknown movement type')
        if from_kiosk and type not in KIOSK_TYPES:
            raise FeriaError('FORBIDDEN', f'{type} is only allowed from the back office', 403)
        if type == 'AJUSTE':
            if not note:
                raise FeriaError('VALIDATION_ERROR', 'AJUSTE requires a note')
            if direction not in ('in', 'out'):
                raise FeriaError('VALIDATION_ERROR', 'AJUSTE requires direction in/out')
        if type == 'ANULACION' and not ref_uuid:
            raise FeriaError('VALIDATION_ERROR', 'ANULACION requires ref_uuid')
        if type != 'ANULACION' and amount is None:
            raise FeriaError('VALIDATION_ERROR', 'amount is required')

        payload = {'partner_id': partner_id, 'type': type, 'amount': amount}

        existing = self.search([('uuid', '=', uuid)], limit=1)
        if existing:
            return self._replay(existing, payload)

        # Lock order is always chain, then contact. The chain lock is held until commit.
        cr.execute("SELECT pg_advisory_xact_lock(%s)", [CHAIN_LOCK])
        cr.execute("SELECT id FROM res_partner WHERE id = %s FOR UPDATE", [partner_id])
        if not cr.rowcount:
            raise FeriaError('CODE_UNKNOWN', 'Unknown contact', 404)
        partner = self.env['res.partner'].browse(partner_id)

        # Another request with the same uuid may have committed while we waited.
        existing = self.search([('uuid', '=', uuid)], limit=1)
        if existing:
            return self._replay(existing, payload)

        if partner.feria_blocked:
            raise FeriaError('CODE_BLOCKED', 'This contact is blocked', 403)
        code = False
        if code_used:
            code = self.env['feria.code'].search([('code', '=', normalize_code(code_used))], limit=1)
            if not code or code.partner_id != partner:
                raise FeriaError('CODE_UNKNOWN', 'Unknown code', 404)
            if code.blocked:
                raise FeriaError('CODE_BLOCKED', 'This code is blocked', 403)

        if from_kiosk:
            limit = Decimal(str(self._feria_param('max_amount', 0) or 0))
            if limit > 0 and amount > limit:
                raise FeriaError('LIMIT_EXCEEDED', f'Amount above the {limit} limit', 403)

        original = self.env['feria.movement']
        if type == 'ANULACION':
            original = self.search([('uuid', '=', ref_uuid)], limit=1)
            if not original or original.partner_id != partner:
                raise FeriaError('VALIDATION_ERROR', 'ref_uuid does not match a movement of this contact')
            if original.state != 'confirmed' or original.type == 'ANULACION':
                raise FeriaError('VALIDATION_ERROR', 'The referenced movement cannot be cancelled')
            if self.search_count([('ref_movement_id', '=', original.id), ('type', '=', 'ANULACION')]):
                raise FeriaError('VALIDATION_ERROR', 'The referenced movement is already cancelled')
            if amount is not None and amount != _dec(original.amount):
                raise FeriaError('VALIDATION_ERROR', 'ANULACION amount must equal the original amount')
            amount = _dec(original.amount)
            signed = -_dec(original.signed_amount)
        elif type == 'AJUSTE':
            signed = amount if direction == 'in' else -amount
        else:
            signed = amount * SIGN[type]

        cr.execute(
            "SELECT COALESCE(SUM(signed_amount), 0)::text FROM feria_movement WHERE partner_id = %s AND state = 'confirmed'",
            [partner_id],
        )
        balance_before = Decimal(cr.fetchone()[0])
        if balance_before + signed < 0:
            raise FeriaError(
                'INSUFFICIENT_BALANCE', 'Insufficient balance', 409,
                balance=str(balance_before.quantize(CENT)),
            )

        incidents = []
        cr.execute("SELECT sequence, hash FROM feria_movement WHERE hash IS NOT NULL ORDER BY id DESC LIMIT 1")
        last = cr.fetchone()
        hash_prev = last[1] if last and last[1] else ''
        expected_sequence = (last[0] if last else 0) + 1
        if sequence is None:
            sequence = expected_sequence
        elif last and sequence != expected_sequence:
            incidents.append(('sequence_gap', f'Expected sequence {expected_sequence}, received {sequence}'))
        if created_at_device:
            created_at_device = created_at_device.replace(microsecond=0)
            skew = abs((fields.Datetime.now() - created_at_device).total_seconds())
            if skew > CLOCK_SKEW_SECONDS:
                incidents.append(('clock_skew', f'Client clock differs {int(skew)} s from the server'))

        vals = {
            'uuid': uuid,
            'partner_id': partner_id,
            'code_used': code.code if code else False,
            'type': type,
            'currency_id': self._feria_currency().id,
            'amount': amount,
            'signed_amount': signed,
            'balance_after': balance_before + signed,
            'created_at_device': created_at_device or False,
            'sequence': sequence,
            'hash_prev': hash_prev,
            'hash': self._hash_of(hash_prev, uuid, partner_id, type, amount, created_at_device, sequence),
            'ref_movement_id': original.id or False,
            'note': note or False,
        }
        try:
            with cr.savepoint():
                movement = self.with_context(feria_register=True).create(vals)
        except psycopg2.errors.UniqueViolation:
            existing = self.search([('uuid', '=', uuid)], limit=1)
            if not existing:
                raise
            return self._replay(existing, payload)
        if incidents:
            self.env['feria.incident'].create([{
                'type': kind,
                'partner_id': partner_id,
                'movement_id': movement.id,
                'description': text,
            } for kind, text in incidents])
        # Materialize the stored balance before the transaction commits.
        self.env.flush_all()
        return movement, False

    @api.model
    def _replay(self, existing, payload):
        same_amount = payload['amount'] is None or _dec(existing.amount) == payload['amount']
        if existing.partner_id.id != payload['partner_id'] or existing.type != payload['type'] or not same_amount:
            raise FeriaError(
                'DUPLICATE', 'This uuid was already used with different data', 409,
                movement=existing._to_api(),
            )
        return existing, True

    def action_cancel(self):
        """Back office cancellation of the selected movement (manager)."""
        self.ensure_one()
        if not self.env.user.has_group('feria_saldo.group_feria_manager'):
            raise UserError('Solo un gestor puede anular movimientos.')
        try:
            self._feria_register(
                uuid=str(uuid_lib.uuid4()), partner_id=self.partner_id.id, type='ANULACION',
                ref_uuid=self.uuid, note=f'Anulacion de {self.uuid}',
            )
        except FeriaError as error:
            raise UserError(error.message) from error
        return True

    @api.model
    def action_verify_chain(self):
        """Recompute the global hash chain and open an incident at the first broken link."""
        if not self.env.user.has_group('feria_saldo.group_feria_manager'):
            raise UserError('Solo un gestor puede verificar la cadena.')
        previous_hash = ''
        for movement in self.sudo().search([('hash', '!=', False)], order='id'):
            if (movement.hash_prev or '') != previous_hash or movement.hash != movement._compute_hash(previous_hash):
                self.env['feria.incident'].sudo().create({
                    'type': 'hash_broken',
                    'movement_id': movement.id,
                    'partner_id': movement.partner_id.id,
                    'description': f'Hash chain broken at movement {movement.uuid}',
                })
                return {
                    'type': 'ir.actions.act_window', 'name': 'Incidencias',
                    'res_model': 'feria.incident', 'view_mode': 'list,form',
                }
            previous_hash = movement.hash
        raise UserError('La cadena de hash es correcta.')
