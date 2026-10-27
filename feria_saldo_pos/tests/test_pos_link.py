import uuid
from decimal import Decimal

from odoo.addons.feria_saldo.tests.common import FeriaCommon
from odoo.exceptions import UserError
from odoo.tests import tagged


@tagged('post_install', '-at_install')
class TestPosLink(FeriaCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.config = cls.env['pos.config'].search([('payment_method_ids.type', '=', 'cash')], limit=1)
        cls.cash_method = cls.config.payment_method_ids.filtered(lambda m: m.type == 'cash')[:1]
        cls.product = cls.env.ref('feria_saldo_pos.product_feria_charge')

    def set_param(self, key, value):
        params = self.env['ir.config_parameter'].sudo()
        params.set_bool(key, value) if isinstance(value, bool) else params.set_str(key, str(value))

    def setUp(self):
        super().setUp()
        self.set_param('feria.pos_config_id', self.config.id)
        self.set_param('feria.pos_payment_method_id', self.cash_method.id)
        self.set_param('feria.pos_product_id', self.product.id)
        self.set_param('feria.pos_link', True)
        self.register('RECARGAR', '200.00')

    def open_session(self):
        config = self.config.sudo()
        session = config.current_session_id
        if not session:
            config.open_ui()
            session = config.current_session_id
        if session.state == 'opening_control':
            session.set_opening_control(0, None)
        return session

    def close_sessions(self):
        """Leave the TPV without an open session."""
        self.env['pos.session'].sudo().search([('config_id', '=', self.config.id), ('state', '!=', 'closed')]).write({'state': 'closed'})
        self.config.sudo().invalidate_recordset(['current_session_id', 'session_ids'])

    def link_of(self, movement):
        return self.env['feria.pos.link'].sudo().search([('movement_id.uuid', '=', movement['uuid'])])

    # ------------------------------------------------------------------
    def test_the_auxiliary_product_exists_and_can_be_sold_in_the_pos(self):
        self.assertEqual((self.product.type, self.product.available_in_pos, self.product.default_code), ('service', True, 'FERIA-COBRO'))
        self.assertFalse(self.product.taxes_id)

    def test_nothing_is_linked_when_the_option_is_off(self):
        self.set_param('feria.pos_link', False)
        self.open_session()
        charge = self.register('COBRAR', '12.00')
        self.assertFalse(self.link_of(charge))
        self.assertFalse(self.env['pos.order'].sudo().search([('uuid', '=', charge['uuid'])]))

    def test_a_charge_becomes_a_paid_pos_order_with_the_auxiliary_product(self):
        session = self.open_session()
        charge = self.register('COBRAR', '12.50')
        link = self.link_of(charge)
        self.assertEqual((link.state, link.attempts), ('done', 1))
        order = link.pos_order_id
        self.assertEqual(order.uuid, charge['uuid'])
        self.assertEqual(order.session_id, session)
        self.assertEqual(order.partner_id, self.partner)
        self.assertEqual(order.state, 'paid')
        self.assertEqual(Decimal(str(order.amount_total)), Decimal('12.50'))
        self.assertEqual(order.lines.product_id, self.product)
        self.assertEqual(order.payment_ids.payment_method_id, self.cash_method)
        # the wallet balance is untouched by the link
        self.assertEqual(self.balance(), Decimal('187.50'))

    def test_recharges_are_not_sales_and_create_no_order(self):
        self.open_session()
        recharge = self.register('RECARGAR', '30.00')
        self.assertFalse(self.link_of(recharge))

    def test_without_an_open_session_the_charge_is_kept_and_retried(self):
        self.close_sessions()
        charge = self.register('COBRAR', '8.00')
        self.assertEqual(self.balance(), Decimal('192.00'))  # never blocked by the POS
        link = self.link_of(charge)
        self.assertEqual(link.state, 'pending')
        self.assertIn('sesion abierta', link.error)
        self.open_session()
        self.env['feria.pos.link'].sudo()._cron_sync()
        self.assertEqual(link.state, 'done')
        self.assertTrue(link.pos_order_id)

    def test_a_pos_failure_never_blocks_the_wallet(self):
        self.open_session()
        self.set_param('feria.pos_payment_method_id', 0)  # misconfigured
        charge = self.register('COBRAR', '5.00')
        self.assertEqual(charge['status'], 'confirmed')
        link = self.link_of(charge)
        self.assertEqual(link.state, 'pending')
        self.assertIn('metodo de pago', link.error)

    def test_the_same_uuid_creates_one_order(self):
        self.open_session()
        movement_uuid = str(uuid.uuid4())
        self.register('COBRAR', '3.00', uuid=movement_uuid)
        again = self.register('COBRAR', '3.00', uuid=movement_uuid)
        self.assertTrue(again['duplicate'])
        self.assertEqual(self.env['pos.order'].sudo().search_count([('uuid', '=', movement_uuid)]), 1)
        self.assertEqual(self.env['feria.pos.link'].sudo().search_count([('movement_id.uuid', '=', movement_uuid)]), 1)

    def test_cancelling_before_it_was_sent_cancels_the_order(self):
        self.close_sessions()
        charge = self.register('COBRAR', '9.00')
        link = self.link_of(charge)
        self.assertEqual(link.state, 'pending')
        self.register('ANULACION', None, ref_uuid=charge['uuid'], from_kiosk=False)
        self.assertEqual(link.state, 'cancelled')
        self.open_session()
        self.env['feria.pos.link'].sudo()._cron_sync()
        self.assertEqual((link.state, bool(link.pos_order_id)), ('cancelled', False))

    def test_cancelling_after_it_was_sent_flags_it_for_review(self):
        self.open_session()
        charge = self.register('COBRAR', '9.00')
        link = self.link_of(charge)
        self.assertEqual(link.state, 'done')
        self.register('ANULACION', None, ref_uuid=charge['uuid'], from_kiosk=False)
        self.assertEqual(link.state, 'review')
        incident = self.env['feria.incident'].sudo().search([('movement_id', '=', link.movement_id.id)])
        self.assertIn(link.pos_order_id.display_name, incident.description)

    def test_settings_need_everything_to_link(self):
        settings = self.env['res.config.settings'].sudo().create({
            'feria_pos_link': True, 'feria_pos_config_id': False,
            'feria_pos_payment_method_id': False, 'feria_pos_product_id': False,
        })
        with self.assertRaises(UserError):
            settings.set_values()
        settings = self.env['res.config.settings'].sudo().create({
            'feria_pos_link': True, 'feria_pos_config_id': self.config.id,
            'feria_pos_payment_method_id': self.cash_method.id, 'feria_pos_product_id': self.product.id,
        })
        settings.set_values()  # complete: accepted
        other_config = self.env['pos.config'].sudo().search([('id', '!=', self.config.id)], limit=1)
        foreign = other_config.payment_method_ids - self.config.payment_method_ids
        if foreign:
            settings = self.env['res.config.settings'].sudo().create({
                'feria_pos_link': True, 'feria_pos_config_id': self.config.id,
                'feria_pos_payment_method_id': foreign[0].id, 'feria_pos_product_id': self.product.id,
            })
            with self.assertRaises(UserError):
                settings.set_values()

    def test_the_overview_counts_pending_and_review_orders(self):
        self.close_sessions()
        overview = self.env['feria.overview'].create({})
        pending_before = overview.pos_pending
        self.assertTrue(overview.pos_link_enabled)
        charge = self.register('COBRAR', '6.00')
        self.assertEqual(self.link_of(charge).state, 'pending')
        self.assertEqual(self.env['feria.overview'].create({}).pos_pending, pending_before + 1)
        self.set_param('feria.pos_link', False)
        self.assertFalse(self.env['feria.overview'].create({}).pos_link_enabled)

