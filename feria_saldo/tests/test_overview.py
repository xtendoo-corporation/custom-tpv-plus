from decimal import Decimal

from odoo.tests import tagged

from .common import FeriaCommon


@tagged('post_install', '-at_install')
class TestOverview(FeriaCommon):

    def overview(self):
        return self.env['feria.overview'].create({})

    def test_the_menu_opens_the_overview_not_the_kiosk(self):
        action = self.env['feria.overview'].action_open()
        self.assertEqual((action['type'], action['res_model'], action['view_mode']), ('ir.actions.act_window', 'feria.overview', 'form'))
        self.assertTrue(action['res_id'])
        # the first entry under Feria is the overview: clicking "Feria" lands on it (the kiosk is a later entry)
        root = self.env.ref('feria_saldo.feria_menu_root')
        first = root.child_id.sorted('sequence')[:1]
        self.assertEqual(first, self.env.ref('feria_saldo.feria_menu_overview'))
        self.assertEqual(first.action._name, 'ir.actions.server')

    def test_figures_follow_the_operations(self):
        before = self.overview()
        # plain values: registering a movement invalidates the cache of the record
        recharges, charges = Decimal(str(before.today_recharges)), Decimal(str(before.today_charges))
        recharges_count, charges_count = before.today_recharges_count, before.today_charges_count
        balance, cash = Decimal(str(before.balance_total)), Decimal(str(before.cash_expected))
        card_before = Decimal(str(before.today_card_recharges))
        self.register('RECARGAR', '40.00')
        self.register('RECARGAR', '10.00', payment_method='card')
        self.register('COBRAR', '15.00')
        after = self.overview()
        self.assertEqual(Decimal(str(after.today_recharges)) - recharges, Decimal('50.00'))  # 40 cash + 10 card
        self.assertEqual(Decimal(str(after.today_card_recharges)) - card_before, Decimal('10.00'))
        self.assertEqual(Decimal(str(after.today_charges)) - charges, Decimal('15.00'))
        self.assertEqual(after.today_recharges_count - recharges_count, 2)
        self.assertEqual(after.today_charges_count - charges_count, 1)
        self.assertEqual(Decimal(str(after.balance_total)) - balance, Decimal('35.00'))   # 50 in, 15 spent
        self.assertEqual(Decimal(str(after.cash_expected)) - cash, Decimal('40.00'))       # only the cash one; card and cobros move no cash
        self.assertEqual(after.currency_id.name, 'EUR')
        self.assertTrue(after.last_movement_at)

    def test_recent_operations_newest_first(self):
        first = self.register('RECARGAR', '1.00')
        second = self.register('RECARGAR', '2.00')
        recent = self.overview().recent_movement_ids
        self.assertEqual(recent[0].uuid, second['uuid'])
        self.assertEqual(recent[1].uuid, first['uuid'])
        self.assertLessEqual(len(recent), 12)

    def test_buttons_open_the_right_screens(self):
        overview = self.overview()
        for method, model in (
            ('action_open_charges', 'feria.movement'), ('action_open_recharges', 'feria.movement'),
            ('action_open_balances', 'res.partner'), ('action_open_cash', 'feria.cash'),
        ):
            self.assertEqual(getattr(overview, method)()['res_model'], model, method)
        self.assertEqual(overview.action_open_desk(), {'type': 'ir.actions.act_url', 'url': '/feria', 'target': 'new'})

    def test_customers_are_people_not_cards(self):
        before = self.overview().customers
        person = self.env['res.partner'].create({'name': 'Dos tarjetas'})
        self.env['feria.code'].create({'partner_id': person.id, 'code': 'AAAA0001'})
        self.env['feria.code'].create({'partner_id': person.id, 'code': 'AAAA0002', 'kind': 'rfid'})
        self.assertEqual(self.overview().customers, before + 1)
        self.assertEqual(self.overview().display_name, 'Resumen')

