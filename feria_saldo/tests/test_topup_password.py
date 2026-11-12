import json
import uuid

from odoo.tests import HttpCase, tagged

BASE = '/feria/api/v1'


@tagged('post_install', '-at_install')
class TestTopupPassword(HttpCase):
    """Recargar needs the password from Ajustes; cobrar and everything else does not."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env['res.partner'].create({'name': 'Clara Prueba'})
        cls.env['feria.code'].create({'partner_id': cls.partner.id, 'code': 'PASS01'})
        cls.env['ir.config_parameter'].sudo().set_str('feria.topup_password', 's3creta')

    def call(self, method, path, data=None):
        response = self.url_open(
            BASE + path, data=json.dumps(data) if data is not None else None,
            headers={'Content-Type': 'application/json'}, method=method, timeout=30,
        )
        return response.status_code, response.json()

    def recarga(self, **extra):
        body = {'uuid': str(uuid.uuid4()), 'code': 'PASS01', 'type': 'RECARGAR', 'amount': '10.00', 'payment_method': 'cash'}
        body.update(extra)
        return body

    def test_config_says_the_password_is_required(self):
        self.assertTrue(self.call('GET', '/config')[1]['topup_password_required'])
        self.env['ir.config_parameter'].sudo().set_str('feria.topup_password', '')
        self.assertFalse(self.call('GET', '/config')[1]['topup_password_required'])

    def test_recarga_without_or_with_wrong_password_is_refused(self):
        for extra in ({}, {'topup_password': 'otra'}, {'topup_password': ''}):
            status, data = self.call('POST', '/movements', self.recarga(**extra))
            self.assertEqual((status, data['error_code']), (403, 'PASSWORD_WRONG'))
        self.assertFalse(self.env['feria.movement'].search_count([('partner_id', '=', self.partner.id)]))

    def test_recarga_with_the_password_works_and_a_replay_needs_nothing(self):
        body = self.recarga(topup_password='s3creta')
        self.assertEqual(self.call('POST', '/movements', body)[0], 200)
        body.pop('topup_password')  # a retry after a reload no longer carries it
        status, data = self.call('POST', '/movements', body)
        self.assertEqual(status, 200)
        self.assertTrue(data['duplicate'])

    def test_cobrar_does_not_need_the_password(self):
        self.call('POST', '/movements', self.recarga(topup_password='s3creta'))
        status, _data = self.call('POST', '/movements', {
            'uuid': str(uuid.uuid4()), 'code': 'PASS01', 'type': 'COBRAR', 'amount': '4.00',
        })
        self.assertEqual(status, 200)

    def test_verify_endpoint(self):
        self.assertEqual(self.call('POST', '/topup/verify', {'password': 's3creta'})[0], 200)
        status, data = self.call('POST', '/topup/verify', {'password': 'mala'})
        self.assertEqual((status, data['error_code']), (403, 'PASSWORD_WRONG'))

    def test_no_lockout_after_many_failures(self):
        for _i in range(8):
            self.assertEqual(self.call('POST', '/topup/verify', {'password': 'mala'})[0], 403)
        self.assertEqual(self.call('POST', '/topup/verify', {'password': 's3creta'})[0], 200)

    def test_without_a_configured_password_everything_is_open(self):
        self.env['ir.config_parameter'].sudo().set_str('feria.topup_password', '')
        self.assertEqual(self.call('POST', '/movements', self.recarga())[0], 200)
        self.assertEqual(self.call('POST', '/topup/verify', {'password': 'x'})[0], 200)
