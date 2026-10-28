from odoo import api, fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    feria_code_ids = fields.One2many('feria.code', 'partner_id', string='Codigos TpvPlus')
    feria_movement_ids = fields.One2many('feria.movement', 'partner_id', string='Movimientos TpvPlus')
    feria_blocked = fields.Boolean(string='Bloqueado en TpvPlus', copy=False)
    feria_currency_id = fields.Many2one('res.currency', compute='_compute_feria_currency_id')
    feria_balance = fields.Monetary(
        string='Saldo TpvPlus', currency_field='feria_currency_id',
        compute='_compute_feria_balance', store=True, readonly=True, copy=False,
    )

    def _compute_feria_currency_id(self):
        currency = self.env['feria.movement']._feria_currency()
        for partner in self:
            partner.feria_currency_id = currency

    @api.depends('feria_movement_ids.signed_amount', 'feria_movement_ids.state')
    def _compute_feria_balance(self):
        self.env['feria.movement'].flush_model(['partner_id', 'signed_amount', 'state'])
        totals = {
            partner.id: total
            for partner, total in self.env['feria.movement']._read_group(
                [('partner_id', 'in', self.ids), ('state', '=', 'confirmed')],
                ['partner_id'], ['signed_amount:sum'],
            )
        }
        for partner in self:
            partner.feria_balance = totals.get(partner.id, 0.0)

    def action_open_feria_topup(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Recarga manual',
            'res_model': 'feria.manual.movement.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_partner_id': self.id},
        }

    def action_open_feria_statement(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Extracto',
            'res_model': 'feria.movement',
            'view_mode': 'list,form',
            'domain': [('partner_id', '=', self.id)],
        }
