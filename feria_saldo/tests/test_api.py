import json
import uuid

from odoo import fields
from odoo.tests import HttpCase, tagged
from odoo.tools import mute_logger

BASE = '/feria/api/v1'


@tagged('post_install', '-at_install')
class TestApi(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env['res.partner'].create({'name': 'Marta Quiroga'})
        cls.env['feria.code'].create({'partner_id': cls.partner.id, 'code': 'AABB11'})
        cls.other = cls.env['res.partner'].create({'name': 'Marta Lopez'})
        cls.env['feria.code'].create({'partner_id': cls.other.id, 'code': 'CCDD22'})
        cls.nocard = cls.env['res.partner'].create({'name': 'Marta SinTarjeta'})

    def call(self, method, path, data=None):
        response = self.url_open(
            BASE + path, data=json.dumps(data) if data is not None else None,
            headers={'Content-Type': 'application/json'}, method=method, timeout=30,
        )
        return response.status_code, response.json()

    def movement_body(self, **kwargs):
        body = {
            'uuid': str(uuid.uuid4()), 'code_used': 'AABB11', 'type': 'RECARGAR', 'amount': '25.00', 'payment_method': 'cash',
            'created_at_device': fields.Datetime.now().isoformat() + 'Z',
        }
        body.update(kwargs)
        return body

    # ------------------------------------------------------------------
    def test_page_is_a_kiosk_with_the_four_buttons_and_no_login(self):
        response = self.url_open('/feria')
        self.assertEqual(response.status_code, 200)
        for label in ('app.js', 'app.css', 'TpvPlus'):
            self.assertIn(label, response.text)
        self.assertIn("script-src 'self'", response.headers['Content-Security-Policy'])
        # assets carry a version so a browser can never keep running an old screen
        self.assertRegex(response.text, r'app\.js\?v=\d+')
        self.assertNotIn('__V__', response.text)
        self.assertEqual(self.url_open('/feria_saldo/static/app/app.js?v=1').status_code, 200)
        js = self.url_open('/feria_saldo/static/app/app.js').text
        for button in ('Cobrar', 'Recargar', 'Ver saldo y pedidos', '¿Qué cliente?', 'Efectivo', 'Tarjeta'):
            self.assertIn(button, js)
        self.assertEqual(js.count('data-act="start"'), 3)  # three options on the home screen, not four
        self.assertNotIn('Cómo paga', js)  # the two payment buttons say it themselves
        # Caja is the fourth tile of the home screen, no longer a button in the header
        self.assertIn('data-act="cash" data-needs-online>', js)
        self.assertNotIn('cashbtn', js)
        # a recarga is built with coins and notes, not with the numeric keypad
        for denomination in ('data-act="denom"', 'denom-undo', 'denom-clear'):
            self.assertIn(denomination, js)
        for entry in ('handleNfcScan', 'NDEFReader', 'nfc-ready'):  # same reader hooks as the TPVPlus Android app
            self.assertIn(entry, js)
        self.assertNotIn("'USD'", js)  # the symbol comes from the server's currency
        for entry in ('tpvHandleBack', 'Todavía no hay operaciones', 'currencySymbol'):  # Android back button, operation history
            self.assertIn(entry, js)
        for gone in ('Pagar', 'PIN', 'login'):
            self.assertNotIn(gone, js)

    def test_health_and_config(self):
        status, body = self.call('GET', '/health')
        self.assertEqual((status, body['status'], body['db_ok']), (200, 'ok', True))
        status, body = self.call('GET', '/config')
        self.assertEqual((status, body['offline_mode']), (200, 'disabled'))
        self.assertEqual(body['currency'], 'EUR')  # the wallet is in euros by default

    def test_lookup_by_card_and_by_id(self):
        status, body = self.call('GET', '/contacts/lookup?code=aa-bb:11')
        self.assertEqual((status, body['contact']['name'], body['balance']), (200, 'Marta Quiroga', '0.00'))
        self.assertEqual(body['currency'], 'EUR')
        self.assertEqual(body['codes'][0]['code'], 'AABB11')
        self.assertFalse(body['blocked'])
        self.assertEqual(self.call('GET', '/contacts/lookup?code=ZZZ')[1]['error_code'], 'CODE_UNKNOWN')
        status, body = self.call('GET', f'/contacts/lookup?contact_id={self.other.id}')
        self.assertEqual((status, body['contact']['name']), (200, 'Marta Lopez'))
        self.assertEqual(self.call('GET', f'/contacts/lookup?contact_id={self.nocard.id}')[1]['error_code'], 'CODE_UNKNOWN')

    def test_there_is_no_search_by_name(self):
        # customers are identified by their wristband or card only: the endpoint that listed names is gone
        self.assertEqual(self.url_open(BASE + '/contacts/search?q=marta').status_code, 404)

    def test_movements_by_card_and_by_contact(self):
        recharge = self.movement_body()
        status, body = self.call('POST', '/movements', recharge)
        self.assertEqual((status, body['status'], body['balance_after']), (200, 'confirmed', '25.00'))
        status, again = self.call('POST', '/movements', recharge)
        self.assertEqual((status, again['balance_after'], again['duplicate']), (200, '25.00', True))

        status, body = self.call('POST', '/movements', self.movement_body(type='COBRAR', amount='30.00'))
        self.assertEqual((status, body['error_code'], body['balance']), (409, 'INSUFFICIENT_BALANCE', '25.00'))

        by_id = {'uuid': str(uuid.uuid4()), 'contact_id': self.partner.id, 'type': 'COBRAR', 'amount': '10.50'}
        self.assertEqual(self.call('POST', '/movements', by_id)[1]['balance_after'], '14.50')
        status, body = self.call('GET', f"/movements/{by_id['uuid']}")
        self.assertEqual((status, body['status'], body['amount']), (200, 'confirmed', '10.50'))
        status, body = self.call('GET', f'/movements/{uuid.uuid4()}')
        self.assertEqual((status, body['status']), (404, 'unknown'))
        status, body = self.call('GET', f'/movements?contact_id={self.partner.id}&limit=10')
        self.assertEqual(len(body['movements']), 2)
        # what VER PEDIDOS shows: this module's own operations, newest first, with the effect on the balance
        newest, oldest = body['movements']
        self.assertEqual((newest['type'], newest['signed_amount'], newest['balance_after']), ('COBRAR', '-10.50', '14.50'))
        self.assertEqual((oldest['type'], oldest['signed_amount'], oldest['balance_after']), ('RECARGAR', '25.00', '25.00'))
        status, body = self.call('GET', f'/orders?contact_id={self.partner.id}')
        self.assertEqual((status, body['orders']), (200, []))

    def test_pagar_and_back_office_types_are_refused(self):
        status, body = self.call('POST', '/movements', self.movement_body(type='PAGAR'))
        self.assertEqual((status, body['error_code']), (400, 'VALIDATION_ERROR'))
        for kind in ('AJUSTE', 'ANULACION'):
            status, body = self.call('POST', '/movements', self.movement_body(type=kind, direction='in', note='x', ref_uuid=str(uuid.uuid4())))
            self.assertEqual((status, body['error_code']), (403, 'FORBIDDEN'), kind)

    def test_validation_errors(self):
        for patch in ({'amount': '1.234'}, {'amount': 'abc'}, {'uuid': 'not-a-uuid'}, {'type': 'ROBAR'}, {'code_used': None}):
            status, body = self.call('POST', '/movements', self.movement_body(**patch))
            self.assertEqual((status, body['error_code']), (400, 'VALIDATION_ERROR'), patch)

    def test_blocked_customer_cannot_be_charged(self):
        self.call('POST', '/movements', self.movement_body())
        self.partner.feria_blocked = True
        status, body = self.call('POST', '/movements', self.movement_body(type='COBRAR', amount='1.00'))
        self.assertEqual((status, body['error_code']), (403, 'CODE_BLOCKED'))
        self.assertTrue(self.call('GET', '/contacts/lookup?code=AABB11')[1]['blocked'])

    def test_allowed_networks(self):
        params = self.env['ir.config_parameter'].sudo()
        params.set_str('feria.allowed_networks', '10.99.0.0/16')
        status, body = self.call('GET', '/config')
        self.assertEqual((status, body['error_code']), (403, 'FORBIDDEN'))
        self.assertEqual(self.url_open('/feria').status_code, 403)
        self.assertEqual(self.call('GET', '/health')[0], 200)  # probes keep working
        params.set_str('feria.allowed_networks', '127.0.0.0/8, 10.99.0.0/16')
        self.assertEqual(self.call('GET', '/config')[0], 200)
        self.assertEqual(self.url_open('/feria').status_code, 200)
        params.set_str('feria.allowed_networks', 'not-a-network')
        with mute_logger('odoo.addons.feria_saldo.controllers.feria_api'):
            self.assertEqual(self.call('GET', '/config')[0], 403)

    def test_cash_endpoints(self):
        status, base = self.call('GET', '/cash')
        self.assertEqual(status, 200)
        self.assertEqual(base['currency'], 'EUR')
        # close the period so the numbers below are independent of what the database already holds
        self.assertEqual(self.call('POST', '/cash', {
            'uuid': str(uuid.uuid4()), 'kind': 'close', 'counted': base['expected'], 'kept': '0',
        })[0], 200)
        self.call('POST', '/movements', self.movement_body(amount='80.00'))
        self.call('POST', '/movements', self.movement_body(type='COBRAR', amount='30.00'))
        status, summary = self.call('GET', '/cash')
        self.assertEqual((summary['recharges'], summary['sales'], summary['expected'], summary['opening_float']),
                         ('80.00', '30.00', '80.00', '0.00'))

        count_body = {'uuid': str(uuid.uuid4()), 'kind': 'count', 'counted': '79.50'}
        status, result = self.call('POST', '/cash', count_body)
        self.assertEqual((status, result['difference'], result['duplicate']), (200, '-0.50', False))
        self.assertTrue(self.call('POST', '/cash', count_body)[1]['duplicate'])

        close_body = {'uuid': str(uuid.uuid4()), 'kind': 'close', 'counted': '80.00', 'kept': '20.00', 'note': 'cierre del dia'}
        status, result = self.call('POST', '/cash', close_body)
        self.assertEqual((status, result['kept'], result['withdrawn'], result['difference']), (200, '20.00', '60.00', '0.00'))
        status, after = self.call('GET', '/cash')
        self.assertEqual((after['opening_float'], after['expected'], after['last_close']['kept']), ('20.00', '20.00', '20.00'))

    def test_cash_validation(self):
        for body in (
            {'kind': 'close', 'counted': '10', 'kept': '11'},   # leaves more than counted
            {'kind': 'close', 'counted': '10'},                 # missing the amount to leave
            {'kind': 'close', 'counted': '-1', 'kept': '0'},
            {'kind': 'weekly', 'counted': '1'},
            {'kind': 'count', 'counted': 'abc'},
        ):
            status, result = self.call('POST', '/cash', {'uuid': str(uuid.uuid4()), **body})
            self.assertEqual((status, result['error_code']), (400, 'VALIDATION_ERROR'), body)
        status, result = self.call('POST', '/cash', {'uuid': str(uuid.uuid4()), 'kind': 'count', 'counted': '0'})
        self.assertEqual(status, 200)  # an empty drawer is a valid count

    def test_a_recharge_says_how_it_is_paid(self):
        for patch in ({'payment_method': None}, {'payment_method': 'bizum'}, {'payment_method': ''}):
            status, body = self.call('POST', '/movements', self.movement_body(**patch))
            self.assertEqual((status, body['error_code']), (400, 'VALIDATION_ERROR'), patch)
        status, cash = self.call('POST', '/movements', self.movement_body(amount='20.00', payment_method='cash'))
        status, card = self.call('POST', '/movements', self.movement_body(amount='15.00', payment_method='CARD'))
        self.assertEqual((cash['payment_method'], card['payment_method']), ('cash', 'card'))
        status, history = self.call('GET', f'/movements?contact_id={self.partner.id}')
        self.assertEqual([m['payment_method'] for m in history['movements'][:2]], ['card', 'cash'])
        # a charge needs no payment method (the wallet pays it)
        status, charge = self.call('POST', '/movements', self.movement_body(type='COBRAR', amount='5.00', payment_method=None))
        self.assertEqual((status, charge['payment_method']), (200, None))

    def test_only_cash_recharges_go_into_the_drawer(self):
        status, base = self.call('GET', '/cash')
        self.call('POST', '/cash', {'uuid': str(uuid.uuid4()), 'kind': 'close', 'counted': base['expected'], 'kept': '0'})
        self.call('POST', '/movements', self.movement_body(amount='50.00', payment_method='cash'))
        self.call('POST', '/movements', self.movement_body(amount='30.00', payment_method='card'))
        status, summary = self.call('GET', '/cash')
        self.assertEqual((summary['recharges'], summary['card_recharges'], summary['expected']), ('50.00', '30.00', '50.00'))

    def test_same_uuid_with_another_payment_method_is_a_conflict(self):
        body = self.movement_body(amount='9.00', payment_method='cash')
        self.assertEqual(self.call('POST', '/movements', body)[0], 200)
        self.assertEqual(self.call('POST', '/movements', body)[1]['duplicate'], True)
        status, result = self.call('POST', '/movements', {**body, 'payment_method': 'card'})
        self.assertEqual((status, result['error_code']), (409, 'DUPLICATE'))
