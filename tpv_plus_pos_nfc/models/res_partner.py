# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import AccessError


class ResPartner(models.Model):
    _inherit = 'res.partner'

    @api.model
    def tpv_plus_customer_history(self, partner_id, limit=30):
        """Customer history shown in the POS: eWallet balance and movements
        (top-ups, payments) plus the latest paid POS orders."""
        if not self.env.user.has_group('point_of_sale.group_pos_user'):
            raise AccessError(self.env._("Solo los usuarios del TPV pueden consultar el historial."))
        partner = self.env['res.partner'].sudo().browse(partner_id).exists()
        if not partner:
            return {}
        limit = max(1, min(int(limit or 30), 100))

        cards = self.env['loyalty.card'].sudo().search([
            ('partner_id', '=', partner.id),
            ('program_id.program_type', '=', 'ewallet'),
        ])
        movements = self.env['loyalty.history'].sudo().search(
            [('card_id', 'in', cards.ids)], order='create_date desc, id desc', limit=limit,
        )
        wallet_moves = [{
            'id': move.id,
            'date': fields.Datetime.to_string(move.create_date),
            'description': move.description or '',
            'issued': move.issued,
            'used': move.used,
        } for move in movements]

        orders = self.env['pos.order'].sudo().search([
            ('partner_id', '=', partner.id),
            ('state', 'in', ('paid', 'done', 'invoiced')),
        ], order='date_order desc, id desc', limit=limit)
        # The wallet is applied as a discount, so the order total excludes it:
        # add it back and list it as one more way of paying.
        wallet_used = {}
        for move in self.env['loyalty.history'].sudo().search([
            ('card_id', 'in', cards.ids),
            ('order_model', '=', 'pos.order'),
            ('order_id', 'in', orders.ids),
        ]):
            wallet_used[move.order_id] = wallet_used.get(move.order_id, 0.0) + move.used
        order_list = [{
            'id': order.id,
            'name': order.pos_reference or order.name,
            'date': fields.Datetime.to_string(order.date_order),
            'total': order.amount_total + wallet_used.get(order.id, 0.0),
            'payments': ([{
                'method': self.env._("Monedero"),
                'amount': wallet_used[order.id],
            }] if wallet_used.get(order.id) else []) + [{
                'method': payment.payment_method_id.name,
                'amount': payment.amount,
            } for payment in order.payment_ids],
            'lines': [{
                'name': line.product_id.display_name,
                'qty': line.qty,
                'total': line.price_subtotal_incl,
            } for line in order.lines],
        } for order in orders]

        return {
            'partner_name': partner.name,
            'balance': sum(cards.mapped('points')),
            'wallet_moves': wallet_moves,
            'orders': order_list,
        }
