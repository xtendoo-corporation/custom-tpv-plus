from odoo.tests import tagged
from odoo.tools import mute_logger

from ..feria_tools import normalize_code
from .common import FeriaCommon


@tagged('post_install', '-at_install')
class TestCodeNormalization(FeriaCommon):

    def test_letters_digits_and_separators(self):
        self.assertEqual(normalize_code('ad:24:fw'), 'AD24FW')
        self.assertEqual(normalize_code('AD-24 FW'), 'AD24FW')
        self.assertEqual(normalize_code('04:a3-1f'), '04A31F')
        self.assertEqual(normalize_code('891'), '891')

    def test_accents_and_other_letters_are_kept(self):
        self.assertEqual(normalize_code('Ñandú 7'), 'ÑANDÚ7')
        self.assertEqual(normalize_code(''), '')
        self.assertEqual(normalize_code(None), '')

    def test_code_is_kept_as_typed_and_found_with_any_separators(self):
        code = self.env['feria.code'].create({'partner_id': self.partner.id, 'code': ' 29:a2:4d:3e ', 'kind': 'nfc'})
        self.assertEqual(code.code, '29:a2:4d:3e')  # colons and case are not touched
        self.assertEqual(code.code_key, '29A24D3E')
        for scanned in ('29:A2:4D:3E', '29a24d3e', '29-A2-4D-3E', '29 a2 4d 3e'):
            self.assertEqual(self.env['feria.code']._feria_find(scanned), code, scanned)
        result = self.register('RECARGAR', '5.00', code_used='29A24D3E')  # a reader that writes it differently
        self.assertEqual(result['code_used'], '29:a2:4d:3e')

    def test_same_code_with_other_separators_is_a_duplicate(self):
        self.env['feria.code'].create({'partner_id': self.partner.id, 'code': 'ad:24:fw'})
        other = self.env['res.partner'].create({'name': 'Otro'})
        with self.assertRaises(Exception), mute_logger('odoo.sql_db'), self.cr.savepoint():  # unique violation on the search key
            self.env['feria.code'].create({'partner_id': other.id, 'code': 'AD-24-FW'})
