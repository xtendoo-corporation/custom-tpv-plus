{
    'name': 'TPV Plus - Saldo Monedero en Ticket POS',
    'summary': 'Muestra el saldo restante del monedero electronico en el ticket del POS',
    'description': """
        Funcionalidades:
        - Detecta si la orden contiene un pago con monedero electronico (eWallet).
        - Muestra en el ticket impreso el saldo restante del monedero del cliente
          despues de la transaccion.
        - Informacion clara y visible en la seccion de pagos del recibo.
    """,
    'version': '19.0.1.0.0',
    'author': 'TPV Plus',
    'category': 'Point of Sale',
    'depends': ['xtendoo_pos_receipt', 'pos_loyalty'],
    'assets': {
        'point_of_sale._assets_pos': [
            'tpv_plus_pos_receipt/static/src/js/ewallet_receipt.js',
            'tpv_plus_pos_receipt/static/src/xml/ewallet_receipt.xml',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
