from odoo import api, fields, models
from odoo.exceptions import UserError


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    feria_pos_link = fields.Boolean(string='Vincular con el TPV de Odoo', config_parameter='feria.pos_link')
    feria_pos_config_id = fields.Many2one('pos.config', string='TPV', config_parameter='feria.pos_config_id')
    feria_pos_payment_method_id = fields.Many2one(
        'pos.payment.method', string='Metodo de pago', config_parameter='feria.pos_payment_method_id',
        domain="[('config_ids', 'in', feria_pos_config_id)]",
        help='Metodo de pago del TPV con el que se registra el cobro (por ejemplo uno llamado "Monedero").',
    )
    feria_pos_product_id = fields.Many2one(
        'product.product', string='Producto auxiliar', config_parameter='feria.pos_product_id',
        domain="[('available_in_pos', '=', True)]",
        help='Cada cobro es una linea de este producto, con el importe del cobro como precio.',
    )

    @api.onchange('feria_pos_config_id')
    def _onchange_feria_pos_config_id(self):
        if self.feria_pos_payment_method_id not in self.feria_pos_config_id.payment_method_ids:
            self.feria_pos_payment_method_id = False

    def set_values(self):
        if self.feria_pos_link:
            if not self.feria_pos_config_id:
                raise UserError('Para vincular con el TPV elige el TPV.')
            if self.feria_pos_payment_method_id not in self.feria_pos_config_id.payment_method_ids:
                raise UserError('Elige un metodo de pago que pertenezca a ese TPV.')
            if not self.feria_pos_product_id:
                raise UserError('Para vincular con el TPV hace falta un producto auxiliar.')
        super().set_values()
