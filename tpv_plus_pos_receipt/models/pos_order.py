# -*- coding: utf-8 -*-
from odoo import models, api
import logging

_logger = logging.getLogger(__name__)


class PosOrder(models.Model):
    _inherit = 'pos.order'

    @api.model
    def get_ewallet_balance_for_partner(self, partner_id):
        """
        Devuelve la lista de eWallets del partner con su saldo actual.
        Se usa desde el frontend para mostrar el saldo restante en el ticket.
        Retorna una lista de dicts: [{'program_name': str, 'balance': float}]
        """
        if not partner_id:
            return []

        partner = self.env['res.partner'].browse(partner_id)
        if not partner.exists():
            return []

        result = []
        loyalty_cards = self.env['loyalty.card'].search([
            ('partner_id', '=', partner.id),
            ('program_id.program_type', '=', 'ewallet'),
        ])
        for card in loyalty_cards:
            result.append({
                'program_name': card.program_id.name or 'Monedero Electronico',
                'balance': card.points,
                'card_id': card.id,
            })

        return result
