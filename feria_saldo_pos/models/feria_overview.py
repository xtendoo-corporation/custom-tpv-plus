from odoo import fields, models


class FeriaOverview(models.TransientModel):
    _inherit = 'feria.overview'

    pos_link_enabled = fields.Boolean(compute='_compute_pos')
    pos_pending = fields.Integer(string='Pedidos del TPV pendientes de enviar', compute='_compute_pos')
    pos_review = fields.Integer(string='Pedidos del TPV para revisar', compute='_compute_pos')

    def _compute_pos(self):
        link = self.env['feria.pos.link'].sudo()
        enabled = link._link_enabled()
        pending = link.search_count([('state', '=', 'pending')])
        review = link.search_count([('state', '=', 'review')])
        for overview in self:
            overview.pos_link_enabled = enabled
            overview.pos_pending = pending
            overview.pos_review = review

    def action_open_pos_links(self):
        return self._open('feria_saldo_pos.feria_pos_link_action')
