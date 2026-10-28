import uuid
from decimal import Decimal

from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.feria_saldo.feria_tools import FeriaError

from .common import FeriaCommon


@tagged('post_install', '-at_install')
class TestCash(FeriaCommon):

    def setUp(self):
        super().setUp()
        # start every test from a closed, empty period whatever the database already holds
        base = self.cash_summary()
        self.close(base['expected'], Decimal('0'))

    def cash_summary(self):
        return self.env['feria.cash']._summary()

    def cash(self, kind, counted, kept=None, **kwargs):
        values = {'uuid': str(uuid.uuid4()), 'kind': kind, 'counted': Decimal(counted), 'kept': None if kept is None else Decimal(kept)}
        values.update(kwargs)
        return self.env['feria.cash']._cash_register(**values)

    def close(self, counted, kept, **kwargs):
        return self.cash('close', counted, kept, **kwargs)

    def expected(self):
        return self.cash_summary()['expected']

    # ------------------------------------------------------------------
    def test_cash_comes_from_recharges_only(self):
        self.register('RECARGAR', '50.00')
        self.register('RECARGAR', '30.00')
        self.register('COBRAR', '20.00')  # spends wallet balance: no cash moves
        summary = self.cash_summary()
        self.assertEqual(summary['recharges'], Decimal('80.00'))
        self.assertEqual(summary['sales'], Decimal('20.00'))
        self.assertEqual(summary['expected'], Decimal('80.00'))
        self.assertEqual(summary['movements_count'], 3)

    def test_cancelled_recharge_gives_cash_back_but_cancelled_charge_does_not(self):
        recharge = self.register('RECARGAR', '40.00')
        charge = self.register('COBRAR', '10.00')
        # the charge goes first: a recarga the customer already spent cannot be given back
        self.register('ANULACION', None, ref_uuid=charge['uuid'], from_kiosk=False)
        self.register('ANULACION', None, ref_uuid=recharge['uuid'], from_kiosk=False)
        summary = self.cash_summary()
        self.assertEqual(summary['recharges'], Decimal('40.00'))
        self.assertEqual(summary['refunds'], Decimal('40.00'))
        self.assertEqual(summary['expected'], Decimal('0.00'))
        self.assertEqual(summary['sales'], Decimal('0.00'))  # the charge was cancelled too

    def test_back_office_recharge_counts_as_cash(self):
        self.register('RECARGAR', '15.00', from_kiosk=False)
        self.assertEqual(self.expected(), Decimal('15.00'))

    def test_count_is_recorded_but_does_not_start_a_new_period(self):
        self.register('RECARGAR', '60.00')
        result = self.cash('count', '58.50')
        self.assertEqual((result['kind'], result['expected'], result['counted'], result['difference']), ('count', '60.00', '58.50', '-1.50'))
        self.assertEqual(self.expected(), Decimal('60.00'))  # same period, nothing consumed

    def test_close_leaves_a_float_for_the_next_day(self):
        self.register('RECARGAR', '100.00')
        result = self.close('102.00', '30.00', note='sobran 2')
        self.assertEqual(
            (result['expected'], result['counted'], result['difference'], result['kept'], result['withdrawn']),
            ('100.00', '102.00', '2.00', '30.00', '72.00'),
        )
        # next period starts with the float that was left and ignores everything already closed
        summary = self.cash_summary()
        self.assertEqual((summary['opening_float'], summary['recharges'], summary['expected']), (Decimal('30.00'), Decimal('0.00'), Decimal('30.00')))
        self.register('RECARGAR', '10.00')
        self.assertEqual(self.expected(), Decimal('40.00'))

    def test_close_emptying_the_drawer(self):
        self.register('RECARGAR', '25.00')
        self.close('25.00', '0')
        summary = self.cash_summary()
        self.assertEqual((summary['opening_float'], summary['expected']), (Decimal('0.00'), Decimal('0.00')))

    def test_a_movement_is_counted_in_exactly_one_period(self):
        self.register('RECARGAR', '10.00')
        self.close('10.00', '0')
        self.register('RECARGAR', '7.00')
        first = self.close('7.00', '0')
        self.assertEqual(first['recharges'], '7.00')
        self.assertEqual(self.expected(), Decimal('0.00'))

    def test_validation(self):
        with self.assertRaises(FeriaError) as ctx:
            self.close('10.00', '10.01')
        self.assertEqual(ctx.exception.error_code, 'VALIDATION_ERROR')
        with self.assertRaises(FeriaError):
            self.cash('close', '10.00', None)  # a cierre needs the amount left
        with self.assertRaises(FeriaError):
            self.cash('weekly', '10.00')
        with self.assertRaises(FeriaError):
            self.cash('count', '1.00', uuid='not-a-uuid')

    def test_same_uuid_registers_once(self):
        self.register('RECARGAR', '20.00')
        movement_uuid = str(uuid.uuid4())
        first = self.close('20.00', '5.00', uuid=movement_uuid)
        again = self.close('20.00', '5.00', uuid=movement_uuid)
        self.assertEqual((first['duplicate'], again['duplicate']), (False, True))
        self.assertEqual(self.env['feria.cash'].search_count([('uuid', '=', movement_uuid)]), 1)
        with self.assertRaises(FeriaError) as ctx:
            self.close('99.00', '5.00', uuid=movement_uuid)
        self.assertEqual(ctx.exception.error_code, 'DUPLICATE')

    def test_append_only(self):
        record = self.env['feria.cash'].search([], limit=1)
        with self.assertRaises(UserError):
            record.write({'note': 'x'})
        with self.assertRaises(UserError):
            record.unlink()
        with self.assertRaises(UserError):
            self.env['feria.cash'].create({'uuid': str(uuid.uuid4())})

    def test_card_recharges_never_enter_the_drawer(self):
        self.register('RECARGAR', '40.00')                              # cash
        card = self.register('RECARGAR', '25.00', payment_method='card')
        summary = self.cash_summary()
        self.assertEqual((summary['recharges'], summary['card_recharges'], summary['expected']),
                         (Decimal('40.00'), Decimal('25.00'), Decimal('40.00')))
        # giving a card recharge back returns money to the card, not from the drawer
        self.register('ANULACION', None, ref_uuid=card['uuid'], from_kiosk=False)
        summary = self.cash_summary()
        self.assertEqual((summary['refunds'], summary['expected']), (Decimal('0.00'), Decimal('40.00')))

    def test_cancelling_a_cash_recharge_takes_cash_out(self):
        cash = self.register('RECARGAR', '30.00')
        self.register('ANULACION', None, ref_uuid=cash['uuid'], from_kiosk=False)
        summary = self.cash_summary()
        self.assertEqual((summary['refunds'], summary['expected']), (Decimal('30.00'), Decimal('0.00')))

    def test_movements_without_payment_method_count_as_cash(self):
        # data from before the payment method existed
        old = self.register('RECARGAR', '12.00')
        self.env.cr.execute("UPDATE feria_movement SET payment_method = NULL WHERE uuid = %s", [old['uuid']])
        self.env.invalidate_all()
        self.assertEqual(self.cash_summary()['recharges'], Decimal('12.00'))

    def test_a_close_stores_the_card_recharges_for_the_record(self):
        self.register('RECARGAR', '10.00')
        self.register('RECARGAR', '7.00', payment_method='card')
        result = self.close('10.00', '0')
        self.assertEqual((result['recharges'], result['card_recharges'], result['expected']), ('10.00', '7.00', '10.00'))
