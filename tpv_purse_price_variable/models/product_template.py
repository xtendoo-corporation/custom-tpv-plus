from odoo import api, fields, models


class ProductTemplate(models.Model):
    _inherit = "product.template"

    pos_variable_price = fields.Boolean(
        string="Precio modificable",
        default=False,
        help="Si está activo, al seleccionar este producto en el POS se pedirá el precio.",
    )

    @api.model
    def _load_pos_data_fields(self, config_id):
        fields_list = super()._load_pos_data_fields(config_id)
        if "pos_variable_price" not in fields_list:
            fields_list.append("pos_variable_price")
        return fields_list

