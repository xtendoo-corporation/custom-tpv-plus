import zoneinfo
from datetime import datetime

from odoo import api, fields, models


class FeriaOverview(models.TransientModel):
    _name = 'feria.overview'
    _description = 'Resumen de TpvPlus'

    currency_id = fields.Many2one('res.currency', compute='_compute_figures')
    today_recharges = fields.Monetary(string='Recargas de hoy', compute='_compute_figures')
    today_recharges_count = fields.Integer(string='Recargas', compute='_compute_figures')
    today_card_recharges = fields.Monetary(string='De ellas, con tarjeta', compute='_compute_figures',
                                           help='No entran en la caja: el dinero entra por el datafono')
    today_charges = fields.Monetary(string='Cobros de hoy', compute='_compute_figures')
    today_charges_count = fields.Integer(string='Cobros', compute='_compute_figures')
    balance_total = fields.Monetary(string='Saldo en circulacion', compute='_compute_figures',
                                    help='Suma de los saldos de todos los clientes: lo que se les debe en consumiciones')
    cash_expected = fields.Monetary(string='Efectivo que debe haber en caja', compute='_compute_figures')
    last_close_date = fields.Datetime(string='Ultimo cierre de caja', compute='_compute_figures')
    last_close_kept = fields.Monetary(string='Dejado en el ultimo cierre', compute='_compute_figures')
    customers = fields.Integer(string='Clientes con tarjeta', compute='_compute_figures')
    last_movement_at = fields.Datetime(string='Ultima operacion', compute='_compute_figures')
    recent_movement_ids = fields.Many2many('feria.movement', string='Ultimas operaciones', compute='_compute_figures')

    def _compute_display_name(self):
        for overview in self:
            overview.display_name = 'Resumen'

    @api.model
    def _today_start(self):
        """Midnight of the user's day, as the naive UTC datetime the database stores."""
        zone = zoneinfo.ZoneInfo(self.env.user.tz or 'UTC')
        local_midnight = datetime.now(zone).replace(hour=0, minute=0, second=0, microsecond=0)
        return local_midnight.astimezone(zoneinfo.ZoneInfo('UTC')).replace(tzinfo=None)

    def _compute_figures(self):
        movement = self.env['feria.movement'].sudo()
        movement.flush_model()
        cr = self.env.cr
        cr.execute(
            """
            SELECT COALESCE(SUM(amount) FILTER (WHERE type = 'RECARGAR'), 0),
                   COUNT(*) FILTER (WHERE type = 'RECARGAR'),
                   COALESCE(SUM(amount) FILTER (WHERE type = 'COBRAR'), 0),
                   COUNT(*) FILTER (WHERE type = 'COBRAR'),
                   COALESCE(SUM(amount) FILTER (WHERE type = 'RECARGAR' AND payment_method = 'card'), 0)
              FROM feria_movement WHERE state = 'confirmed' AND received_at >= %s
            """,
            [self._today_start()],
        )
        recharges, recharges_count, charges, charges_count, card_recharges = cr.fetchone()
        cr.execute("SELECT COALESCE(SUM(signed_amount), 0) FROM feria_movement WHERE state = 'confirmed'")
        balance = cr.fetchone()[0]
        cash = self.env['feria.cash'].sudo()
        expected = cash._summary()['expected']
        last_close = cash.search([('kind', '=', 'close')], limit=1)
        last_movement = movement.search([], limit=1)
        customers = self.env['res.partner'].sudo().search_count([('feria_code_ids', '!=', False)])  # people, not cards
        recent = movement.search([], limit=12)
        currency = movement._feria_currency()
        for overview in self:
            overview.currency_id = currency
            overview.today_recharges = recharges
            overview.today_recharges_count = recharges_count
            overview.today_card_recharges = card_recharges
            overview.today_charges = charges
            overview.today_charges_count = charges_count
            overview.balance_total = balance
            overview.cash_expected = float(expected)
            overview.last_close_date = last_close.date
            overview.last_close_kept = last_close.kept
            overview.customers = customers
            overview.last_movement_at = last_movement.received_at
            overview.recent_movement_ids = recent

    # ------------------------------------------------------------------
    @api.model
    def action_open(self):
        """Menu entry: a fresh overview, so the numbers are the ones of this moment."""
        record = self.create({})
        return {
            'type': 'ir.actions.act_window',
            'name': 'Resumen',
            'res_model': self._name,
            'res_id': record.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_refresh(self):
        return self.action_open()

    def _open(self, xml_id):
        return self.env['ir.actions.actions']._for_xml_id(xml_id)

    def action_open_desk(self):
        return {'type': 'ir.actions.act_url', 'url': '/feria', 'target': 'new'}

    def action_open_charges(self):
        return self._open('feria_saldo.feria_movement_action_charges')

    def action_open_recharges(self):
        return self._open('feria_saldo.feria_movement_action_recharges')

    def action_open_balances(self):
        return self._open('feria_saldo.res_partner_action_feria')

    def action_open_cash(self):
        return self._open('feria_saldo.feria_cash_action')
