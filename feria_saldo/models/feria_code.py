from odoo import api, fields, models

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
    note = fields.Char(string='Nota')

    _code_unique = models.UniqueIndex('(code)', 'Este codigo ya esta asignado a otro contacto.')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('code'):
                vals['code'] = normalize_code(vals['code'])
        return super().create(vals_list)

    def write(self, vals):
        if vals.get('code'):
            vals['code'] = normalize_code(vals['code'])
        return super().write(vals)

    def action_block(self):
        self.blocked = True

    def action_unblock(self):
        self.blocked = False
