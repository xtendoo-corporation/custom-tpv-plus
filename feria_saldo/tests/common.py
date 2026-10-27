import uuid
from decimal import Decimal

from odoo.addons.base.tests.common import BaseCommon


class FeriaCommon(BaseCommon):
    # BaseCommon runs every test as this user, so access rights are exercised
    _test_user_groups = ('feria_saldo.group_feria_manager',)

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.enterClassContext(cls.registry_test_mode())
        cls.env = cls.env(su=True)  # fixtures as superuser
        cls.partner = cls.env['res.partner'].create({'name': 'Cliente Feria'})
        cls.code = cls.env['feria.code'].create({'partner_id': cls.partner.id, 'code': '04:a3-1f', 'kind': 'nfc'})

    def register(self, type_='RECARGAR', amount='10.00', **kwargs):
        values = {
            'uuid': str(uuid.uuid4()),
            'partner_id': self.partner.id,
            'type': type_,
            'amount': Decimal(amount) if amount is not None else None,
            'from_kiosk': True,
        }
        values.update(kwargs)
        return self.env['feria.movement']._feria_register(**values)

    def balance(self):
        self.partner.invalidate_recordset(['feria_balance'])
        return Decimal(str(self.partner.feria_balance)).quantize(Decimal('0.01'))
