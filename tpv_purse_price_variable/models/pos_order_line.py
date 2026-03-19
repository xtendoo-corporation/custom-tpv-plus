from odoo import models, fields, api


class PosOrderLine(models.Model):
    _inherit = "pos.order.line"

    tpv_purse_program_id = fields.Many2one(
        comodel_name="loyalty.program",
        string="TPV Purse Program",
        help="Programa eWallet seleccionado para una recarga de monedero con precio variable.",
    )

    @api.model
    def _load_pos_data_fields(self, config):
        fields_list = super()._load_pos_data_fields(config)
        if "tpv_purse_program_id" not in fields_list:
            fields_list.append("tpv_purse_program_id")
        return fields_list


