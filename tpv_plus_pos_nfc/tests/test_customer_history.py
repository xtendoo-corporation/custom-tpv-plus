# -*- coding: utf-8 -*-
from odoo.exceptions import AccessError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged('post_install', '-at_install')
class TestCustomerHistory(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env['res.partner'].create({'name': 'Cliente historial'})
        cls.program = cls.env['loyalty.program'].create({
            'name': 'Monedero test',
            'program_type': 'ewallet',
        })
        cls.card = cls.env['loyalty.card'].create({
            'program_id': cls.program.id,
            'partner_id': cls.partner.id,
            'points': 7.5,
        })
        cls.env['loyalty.history'].create([
            {'card_id': cls.card.id, 'description': 'Recarga', 'issued': 10.0},
            {'card_id': cls.card.id, 'description': 'Pago', 'used': 2.5},
        ])
        cls.pos_user = cls.env['res.users'].create({
            'name': 'Cajero test',
            'login': 'cajero_history_test',
            'group_ids': [(6, 0, [cls.env.ref('point_of_sale.group_pos_user').id])],
        })

    def test_history_returns_balance_and_movements(self):
        data = self.env['res.partner'].with_user(self.pos_user).tpv_plus_customer_history(self.partner.id)
        self.assertEqual(data['balance'], 7.5)
        moves = {m['description']: m for m in data['wallet_moves']}
        self.assertEqual(moves['Recarga']['issued'], 10.0)
        self.assertEqual(moves['Pago']['used'], 2.5)
        self.assertEqual(data['orders'], [])

    def test_history_requires_pos_user(self):
        user = self.env['res.users'].create({
            'name': 'Sin TPV', 'login': 'sin_tpv_history_test',
            'group_ids': [(6, 0, [self.env.ref('base.group_user').id])],
        })
        with self.assertRaises(AccessError):
            self.env['res.partner'].with_user(user).tpv_plus_customer_history(self.partner.id)
