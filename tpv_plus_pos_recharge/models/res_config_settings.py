# -*- coding: utf-8 -*-

from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    pos_recharge_product_id = fields.Many2one(
        related='pos_config_id.recharge_product_id',
        readonly=False,
    )

