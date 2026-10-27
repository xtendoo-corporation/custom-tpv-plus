import uuid
from decimal import Decimal

from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged
from odoo.tools import mute_logger

from odoo.addons.feria_saldo.feria_tools import FeriaError

from .common import FeriaCommon


@tagged('post_install', '-at_install')
class TestMovement(FeriaCommon):

    def assertRejected(self, error_code, **kwargs):
        with self.assertRaises(FeriaError) as ctx:
            self.register(**kwargs)
        self.assertEqual(ctx.exception.error_code, error_code)
        return ctx.exception

    def test_balance_is_sum_of_movements(self):
        self.register('RECARGAR', '50.00')
        result = self.register('COBRAR', '12.50')
        self.assertEqual(result['balance_after'], '37.50')
        self.register('COBRAR', '7.50')
        self.assertEqual(self.balance(), Decimal('30.00'))

    def test_insufficient_balance_rejected_and_not_stored(self):
        self.register('RECARGAR', '5.00')
        error = self.assertRejected('INSUFFICIENT_BALANCE', type_='COBRAR', amount='5.01')
        self.assertEqual(error.extra['balance'], '5.00')
        self.assertEqual(self.balance(), Decimal('5.00'))
        self.assertEqual(self.env['feria.movement'].search_count([('partner_id', '=', self.partner.id)]), 1)

    def test_same_uuid_registers_once(self):
        movement_uuid = str(uuid.uuid4())
        self.register('RECARGAR', '20.00')
        first = self.register('COBRAR', '4.00', uuid=movement_uuid)
        again = [self.register('COBRAR', '4.00', uuid=movement_uuid) for _ in range(20)]
        self.assertFalse(first['duplicate'])
        for replay in again:
            self.assertTrue(replay['duplicate'])
            self.assertEqual(replay['balance_after'], first['balance_after'])
        self.assertEqual(self.env['feria.movement'].search_count([('uuid', '=', movement_uuid)]), 1)
        self.assertEqual(self.balance(), Decimal('16.00'))

    def test_same_uuid_with_other_data_is_a_conflict(self):
        movement_uuid = str(uuid.uuid4())
        self.register('RECARGAR', '20.00', uuid=movement_uuid)
        error = self.assertRejected('DUPLICATE', type_='RECARGAR', amount='99.00', uuid=movement_uuid)
        self.assertEqual(error.extra['movement']['amount'], '20.00')

    def test_cancellation_is_a_counter_movement(self):
        self.register('RECARGAR', '30.00')
        paid = self.register('COBRAR', '10.00')
        self.assertEqual(self.balance(), Decimal('20.00'))
        cancel = self.register('ANULACION', None, ref_uuid=paid['uuid'], from_kiosk=False)
        self.assertEqual(cancel['signed_amount'], '10.00')
        self.assertEqual(cancel['ref_uuid'], paid['uuid'])
        self.assertEqual(self.balance(), Decimal('30.00'))
        self.assertTrue(self.env['feria.movement'].search([('uuid', '=', paid['uuid'])]))
        with self.assertRaises(FeriaError):
            self.register('ANULACION', None, ref_uuid=paid['uuid'], from_kiosk=False)

    def test_kiosk_cannot_cancel(self):
        paid = self.register('RECARGAR', '30.00')
        self.assertRejected('FORBIDDEN', type_='ANULACION', amount=None, ref_uuid=paid['uuid'])

    def test_adjust_not_allowed_from_api(self):
        self.assertRejected('FORBIDDEN', type_='AJUSTE', amount='5.00', direction='in', note='x')

    def test_adjust_backoffice_needs_note_and_direction(self):
        kwargs = {'from_kiosk': False}
        self.assertRejected('VALIDATION_ERROR', type_='AJUSTE', amount='5.00', direction='in', **kwargs)
        result = self.register('AJUSTE', '5.00', direction='in', note='regalo', **kwargs)
        self.assertEqual(result['balance_after'], '5.00')

    def test_blocked_code_and_contact(self):
        self.register('RECARGAR', '10.00')
        self.code.blocked = True
        self.assertRejected('CODE_BLOCKED', type_='COBRAR', amount='1.00', code_used='04A31F')
        self.code.blocked = False
        self.partner.feria_blocked = True
        self.assertRejected('CODE_BLOCKED', type_='COBRAR', amount='1.00')

    def test_unknown_code_for_partner(self):
        other = self.env['res.partner'].create({'name': 'Otro'})
        self.env['feria.code'].create({'partner_id': other.id, 'code': 'BEEF'})
        self.assertRejected('CODE_UNKNOWN', type_='COBRAR', amount='1.00', code_used='BEEF')

    def test_max_amount_applies_to_the_kiosk_only(self):
        self.env['ir.config_parameter'].sudo().set_str('feria.max_amount', '20')
        self.register('RECARGAR', '20.00')
        self.assertRejected('LIMIT_EXCEEDED', type_='RECARGAR', amount='20.01')
        self.register('RECARGAR', '100.00', from_kiosk=False)

    def test_amount_validation(self):
        from odoo.addons.feria_saldo.feria_tools import parse_amount
        for bad in ('0', '-1', '1.234', 'abc', 'NaN', None, True):
            with self.assertRaises(FeriaError, msg=repr(bad)):
                parse_amount(bad)
        self.assertEqual(parse_amount('10'), Decimal('10.00'))
        self.assertEqual(parse_amount(0.1 + 0.2 if False else '0.30'), Decimal('0.30'))

    def test_append_only(self):
        result = self.register('RECARGAR', '10.00')
        movement = self.env['feria.movement'].search([('uuid', '=', result['uuid'])])
        with self.assertRaises(UserError):
            movement.write({'note': 'x'})
        with self.assertRaises(UserError):
            movement.unlink()
        with self.assertRaises(UserError), mute_logger('odoo.sql_db'):
            self.env['feria.movement'].create({'uuid': str(uuid.uuid4())})

    def test_code_normalization_and_uniqueness(self):
        self.assertEqual(self.code.code, '04A31F')
        other = self.env['res.partner'].create({'name': 'Otro'})
        with self.assertRaises(Exception), mute_logger('odoo.sql_db'):
            self.env['feria.code'].create({'partner_id': other.id, 'code': '04-a3:1f'})

    def test_hash_chain_and_tamper_detection(self):
        for _ in range(3):
            self.register('RECARGAR', '1.00')
        # the chain is global: other movements may already exist, so look at ours only
        movements = self.env['feria.movement'].search([('partner_id', '=', self.partner.id)], order='id')
        self.assertEqual(len(movements), 3)
        self.assertEqual(movements[1].hash_prev, movements[0].hash)
        self.assertEqual(movements[2].hash_prev, movements[1].hash)
        self.assertEqual([m.sequence - movements[0].sequence for m in movements], [0, 1, 2])
        with self.assertRaises(UserError):  # intact chain: "all fine" message
            self.env['feria.movement'].action_verify_chain()
        self.env.cr.execute('UPDATE feria_movement SET amount = 99 WHERE id = %s', [movements[1].id])
        self.env.invalidate_all()
        self.env['feria.movement'].action_verify_chain()
        incident = self.env['feria.incident'].search([('type', '=', 'hash_broken')])
        self.assertEqual(incident.movement_id, movements[1])

    def test_sequence_gap_and_clock_skew_open_incidents(self):
        from datetime import timedelta
        from odoo import fields
        first = self.register('RECARGAR', '1.00')
        self.register(
            'RECARGAR', '1.00', sequence=first['sequence'] + 5,
            created_at_device=fields.Datetime.now() - timedelta(hours=2),
        )
        incidents = self.env['feria.incident'].search([('partner_id', '=', self.partner.id)])
        self.assertEqual(set(incidents.mapped('type')), {'sequence_gap', 'clock_skew'})

    def test_manual_wizard_requires_manager(self):
        wizard = self.env['feria.manual.movement.wizard'].create({
            'partner_id': self.partner.id, 'type': 'RECARGAR', 'amount': '12,50',
        })
        with self.assertRaises((UserError, AccessError)):
            wizard.with_user(self.env['res.users'].create({
                'name': 'Consulta', 'login': 'feria_viewer',
                'group_ids': [(6, 0, [self.env.ref('feria_saldo.group_feria_user').id])],
            })).action_confirm()
        wizard.action_confirm()
        self.assertEqual(self.balance(), Decimal('12.50'))
