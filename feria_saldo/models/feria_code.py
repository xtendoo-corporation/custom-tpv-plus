from odoo import api, fields, models
from odoo.exceptions import UserError

from ..feria_tools import normalize_code


class FeriaCode(models.Model):
    _name = 'feria.code'
    _description = 'Codigo de tarjeta o pulsera'
    _rec_name = 'code'
    _order = 'partner_id, id'

    partner_id = fields.Many2one('res.partner', string='Contacto', required=True, index=True, ondelete='restrict')
    code = fields.Char(string='Codigo', required=True, copy=False)
    kind = fields.Selection(
        [('nfc', 'NFC'), ('rfid', 'RFID'), ('qr', 'QR'), ('manual', 'Manual')],
        string='Tipo', required=True, default='manual',
    )
    active = fields.Boolean(default=True)
    blocked = fields.Boolean(string='Bloqueado', copy=False)
    note = fields.Char(string='Nota', help='Se muestra entre parentesis junto al nombre del contacto al escanear el codigo.')
    shared = fields.Boolean(
        string='Saldo compartido', default=True,
        help='Marcado: este codigo usa el saldo del contacto, compartido con sus otros codigos. '
             'Desmarcado: el codigo tiene su propio saldo individual.',
    )
    wallet_movement_ids = fields.One2many('feria.movement', 'wallet_code_id', string='Movimientos del saldo individual')
    currency_id = fields.Many2one('res.currency', compute='_compute_currency_id')
    balance = fields.Monetary(
        string='Saldo individual', currency_field='currency_id',
        compute='_compute_balance', store=True, readonly=True, copy=False,
    )

    _code_unique = models.UniqueIndex('(code)', 'Este codigo ya esta asignado a otro contacto.')

    def _compute_currency_id(self):
        currency = self.env['feria.movement']._feria_currency()
        for code in self:
            code.currency_id = currency

    @api.depends('wallet_movement_ids.signed_amount', 'wallet_movement_ids.state')
    def _compute_balance(self):
        self.env['feria.movement'].flush_model(['wallet_code_id', 'signed_amount', 'state'])
        totals = {
            code.id: total
            for code, total in self.env['feria.movement']._read_group(
                [('wallet_code_id', 'in', self.ids), ('state', '=', 'confirmed')],
                ['wallet_code_id'], ['signed_amount:sum'],
            )
        }
        for code in self:
            code.balance = totals.get(code.id, 0.0)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('code'):
                vals['code'] = normalize_code(vals['code'])
        return super().create(vals_list)

    def write(self, vals):
        if vals.get('code'):
            vals['code'] = normalize_code(vals['code'])
        if 'shared' in vals:
            for code in self.filtered(lambda c: c.shared != vals['shared'] and c.wallet_movement_ids):
                raise UserError(
                    f'El codigo {code.code} ya tiene movimientos en su saldo individual: no se puede pasar a '
                    'compartido. Deje su saldo a cero con un ajuste y bloquee el codigo.'
                )
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_wallet(self):
        for code in self.filtered('wallet_movement_ids'):
            raise UserError(f'El codigo {code.code} tiene un saldo individual con movimientos: bloqueelo en vez de borrarlo.')

    def action_block(self):
        self.blocked = True

    def action_unblock(self):
        self.blocked = False
