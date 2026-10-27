from odoo import fields, models


class FeriaIncident(models.Model):
    _name = 'feria.incident'
    _description = 'Incidencia de feria'
    _order = 'id desc'

    type = fields.Selection(
        [
            ('hash_broken', 'Hash roto'),
            ('sequence_gap', 'Secuencia con huecos'),
            ('clock_skew', 'Reloj desajustado'),
            ('duplicate_code', 'Codigo duplicado'),
            ('other', 'Otra'),
        ],
        string='Tipo', required=True,
    )
    state = fields.Selection([('open', 'Abierta'), ('done', 'Resuelta')], string='Estado', default='open', required=True)
    partner_id = fields.Many2one('res.partner', string='Contacto', ondelete='restrict')
    movement_id = fields.Many2one('feria.movement', string='Movimiento', ondelete='restrict')
    description = fields.Text(string='Descripcion')

    def action_resolve(self):
        self.state = 'done'
