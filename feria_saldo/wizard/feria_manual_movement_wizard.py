import uuid as uuid_lib

from odoo import fields, models
from odoo.exceptions import UserError

from ..feria_tools import FeriaError, parse_amount


class FeriaManualMovementWizard(models.TransientModel):
    _name = 'feria.manual.movement.wizard'
    _description = 'Recarga o ajuste manual'

    partner_id = fields.Many2one('res.partner', string='Contacto', required=True)
    type = fields.Selection(
        [('RECARGAR', 'Recarga'), ('AJUSTE', 'Ajuste')], string='Tipo', required=True, default='RECARGAR',
    )
    direction = fields.Selection([('in', 'Suma'), ('out', 'Resta')], string='Sentido del ajuste', default='in')
    payment_method = fields.Selection(
        [('cash', 'Efectivo'), ('card', 'Tarjeta')], string='Como paga', default='cash',
        help='Solo el efectivo entra en la caja.',
    )
    amount = fields.Char(string='Importe', required=True)
    note = fields.Char(string='Motivo')

    def action_confirm(self):
        self.ensure_one()
        if not self.env.user.has_group('feria_saldo.group_feria_manager'):
            raise UserError('Solo un gestor puede registrar recargas o ajustes manuales.')
        try:
            self.env['feria.movement']._feria_register(
                uuid=str(uuid_lib.uuid4()),
                partner_id=self.partner_id.id,
                type=self.type,
                amount=parse_amount(self.amount.replace(',', '.')),
                direction=self.direction if self.type == 'AJUSTE' else None,
                payment_method=self.payment_method if self.type == 'RECARGAR' else None,
                note=self.note,
            )
        except FeriaError as error:
            raise UserError(error.message) from error
        return {'type': 'ir.actions.act_window_close'}
