from odoo.tests import tagged

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

    def test_saved_code_is_normalized_and_found_either_way(self):
        code = self.env['feria.code'].create({'partner_id': self.partner.id, 'code': 'ad:24:fw', 'kind': 'nfc'})
        self.assertEqual(code.code, 'AD24FW')
        result = self.register('RECARGAR', '5.00', code_used='AD-24-FW')  # a reader that writes it differently
        self.assertEqual(result['code_used'], 'AD24FW')
