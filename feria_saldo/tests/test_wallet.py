import json
import uuid
from decimal import Decimal

from odoo.exceptions import UserError
from odoo.tests import HttpCase, tagged

from ..feria_tools import FeriaError
from .common import FeriaCommon

BASE = '/feria/api/v1'


@tagged('post_install', '-at_install')
class TestWallet(FeriaCommon):
    """A code can share the contact's balance (default) or hold its own individual balance."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.own = cls.env['feria.code'].create({
            'partner_id': cls.partner.id, 'code': 'OWN-1', 'kind': 'rfid', 'shared': False, 'note': 'Hijo',
        })

    def own_balance(self):
        self.own.invalidate_recordset(['balance'])
        return Decimal(str(self.own.balance)).quantize(Decimal('0.01'))

    def test_codes_are_shared_by_default(self):
        self.assertTrue(self.code.shared)
        self.assertFalse(self.own.shared)

    def test_individual_code_has_its_own_balance(self):
        self.register('RECARGAR', '30.00', code_used='OWN-1')
        self.register('RECARGAR', '10.00', code_used='04:a3-1f')  # shared code
        self.assertEqual(self.own_balance(), Decimal('30.00'))
        self.assertEqual(self.balance(), Decimal('10.00'))  # the contact balance excludes the individual wallet

    def test_individual_wallet_cannot_spend_the_shared_balance_and_vice_versa(self):
        self.register('RECARGAR', '10.00', code_used='04:a3-1f')
        with self.assertRaises(FeriaError) as ctx:
            self.register('COBRAR', '5.00', code_used='OWN-1')
        self.assertEqual(ctx.exception.error_code, 'INSUFFICIENT_BALANCE')
        self.register('RECARGAR', '20.00', code_used='OWN-1')
        self.register('COBRAR', '15.00', code_used='OWN-1')
        self.assertEqual(self.own_balance(), Decimal('5.00'))
        self.assertEqual(self.balance(), Decimal('10.00'))
        with self.assertRaises(FeriaError):
            self.register('COBRAR', '11.00', code_used='04:a3-1f')

    def test_balance_after_is_the_wallet_balance(self):
        self.register('RECARGAR', '10.00', code_used='04:a3-1f')
        result = self.register('RECARGAR', '4.00', code_used='OWN-1')
        self.assertEqual(result['balance_after'], '4.00')
        self.assertEqual(result['wallet'], self.own.code)

    def test_cancellation_reverses_the_same_wallet(self):
        movement = self.register('RECARGAR', '8.00', code_used='OWN-1')
        self.env['feria.movement']._feria_register(
            uuid=str(uuid.uuid4()), partner_id=self.partner.id, type='ANULACION', ref_uuid=movement['uuid'],
        )
        self.assertEqual(self.own_balance(), Decimal('0.00'))
        self.assertEqual(self.balance(), Decimal('0.00'))

    def test_back_office_can_target_an_individual_wallet(self):
        self.register('RECARGAR', '6.00', wallet_code_id=self.own.id, from_kiosk=False)
        self.assertEqual(self.own_balance(), Decimal('6.00'))
        self.assertEqual(self.balance(), Decimal('0.00'))
        with self.assertRaises(FeriaError):  # a shared code has no wallet of its own
            self.register('RECARGAR', '6.00', wallet_code_id=self.code.id, from_kiosk=False)

    def test_cannot_turn_a_used_individual_code_into_shared(self):
        self.register('RECARGAR', '6.00', code_used='OWN-1')
        with self.assertRaises(UserError):
            self.own.shared = True
        with self.assertRaises(UserError):
            self.own.unlink()

    def test_hash_chain_still_verifies_with_wallets(self):
        self.register('RECARGAR', '6.00', code_used='OWN-1')
        self.register('RECARGAR', '2.00', code_used='04:a3-1f')
        with self.assertRaises(UserError) as ctx:  # "La cadena de hash es correcta." is raised as a message
            self.env['feria.movement'].action_verify_chain()
        self.assertIn('correcta', str(ctx.exception))


@tagged('post_install', '-at_install')
class TestWalletApi(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env['res.partner'].create({'name': 'Familia Ruiz'})
        cls.env['feria.code'].create({'partner_id': cls.partner.id, 'code': 'PAPA01', 'note': 'Papa'})
        cls.env['feria.code'].create({'partner_id': cls.partner.id, 'code': 'NINO01', 'shared': False, 'note': 'Nico'})

    def call(self, method, path, data=None):
        response = self.url_open(
            BASE + path, data=json.dumps(data) if data is not None else None,
            headers={'Content-Type': 'application/json'}, method=method, timeout=30,
        )
        return response.status_code, response.json()

    def topup(self, code, amount):
        return self.call('POST', '/movements', {
            'uuid': str(uuid.uuid4()), 'code': code, 'type': 'RECARGAR', 'amount': amount, 'payment_method': 'cash',
        })

    def test_lookup_returns_wallet_balance_and_note(self):
        self.assertEqual(self.topup('PAPA01', '50.00')[0], 200)
        self.assertEqual(self.topup('NINO01', '12.00')[0], 200)
        _status, shared = self.call('GET', '/contacts/lookup?code=PAPA01')
        _status, own = self.call('GET', '/contacts/lookup?code=NINO01')
        self.assertEqual(shared['balance'], '50.00')
        self.assertEqual(shared['wallet'], {'shared': True, 'code': None})
        self.assertEqual(shared['scanned'], {'code': 'PAPA01', 'note': 'Papa'})
        self.assertEqual(own['balance'], '12.00')
        self.assertEqual(own['wallet'], {'shared': False, 'code': 'NINO01'})
        self.assertEqual(own['scanned']['note'], 'Nico')
        self.assertEqual(own['contact']['name'], 'Familia Ruiz')

    def test_history_is_filtered_by_wallet(self):
        self.topup('PAPA01', '50.00')
        self.topup('NINO01', '12.00')
        cid = self.partner.id
        _s, shared = self.call('GET', f'/movements?contact_id={cid}&code=PAPA01')
        _s, own = self.call('GET', f'/movements?contact_id={cid}&code=NINO01')
        self.assertEqual([m['amount'] for m in shared['movements']], ['50.00'])
        self.assertEqual([m['amount'] for m in own['movements']], ['12.00'])

    def test_cobrar_with_the_individual_code_checks_its_own_balance(self):
        self.topup('PAPA01', '50.00')
        status, data = self.call('POST', '/movements', {
            'uuid': str(uuid.uuid4()), 'code': 'NINO01', 'type': 'COBRAR', 'amount': '5.00',
        })
        self.assertEqual(status, 409)
        self.assertEqual(data['error_code'], 'INSUFFICIENT_BALANCE')
