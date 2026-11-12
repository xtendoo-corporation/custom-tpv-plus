from odoo import models
from odoo.tools import float_round


class PosOrderReceipt(models.AbstractModel):
    _inherit = 'pos.order.receipt'

    def order_receipt_generate_data(self, basic_receipt=False):
        """Saldo del monedero electrónico (eWallet) usado en el pedido.

        La contraparte JS es ``generate_printer_data.js``; ambas deben devolver las mismas
        claves (programName, amountUsed, remainingBalance) para que el recibo del frontend
        y el del backend coincidan.
        """
        data = super().order_receipt_generate_data(basic_receipt)
        histories = self.env['loyalty.history'].search([
            ('order_model', '=', 'pos.order'),
            ('order_id', '=', self.id),
        ])
        ewallets = []
        for card, card_histories in histories.grouped('card_id').items():
            if card.program_id.program_type != 'ewallet':
                continue
            used = sum(card_histories.mapped('used'))
            if used <= 0:
                continue
            ewallets.append({
                'programName': card.program_id.name or 'Monedero Electronico',
                'amountUsed': float_round(used, precision_rounding=0.01),
                'remainingBalance': float_round(max(card.points, 0), precision_rounding=0.01),
            })
        data['extra_data']['ewallets'] = ewallets
        return data
