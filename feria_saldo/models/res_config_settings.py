from odoo import fields, models
from odoo.exceptions import UserError

from ..feria_tools import parse_networks


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    feria_currency_id = fields.Many2one('res.currency', string='Moneda del monedero', config_parameter='feria.currency_id')
    feria_offline_mode = fields.Selection(
        [('disabled', 'Desactivado (online estricto)'), ('limited', 'Limitado (no disponible aun)')],
        string='Modo offline', config_parameter='feria.offline_mode', default='disabled',
    )
    feria_max_amount = fields.Float(
        string='Importe maximo por operacion', config_parameter='feria.max_amount', help='0 = sin limite',
    )
    feria_allowed_networks = fields.Char(
        string='Redes permitidas', config_parameter='feria.allowed_networks',
        help='Redes (CIDR) separadas por comas desde las que se puede usar la pantalla de caja, '
             'por ejemplo 192.168.1.0/24. Vacio = cualquiera.',
    )

    def set_values(self):
        if self.feria_offline_mode == 'limited':
            raise UserError('El modo offline limitado aun no esta implementado.')
        try:
            parse_networks(self.feria_allowed_networks)
        except ValueError as error:
            raise UserError(f'Redes permitidas no validas: {error}') from error
        super().set_values()
