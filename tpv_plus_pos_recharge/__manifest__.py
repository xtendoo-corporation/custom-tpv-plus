{
    'name': 'TPV Plus - Recarga Monedero Electrónico POS',
    'summary': 'Botón de recarga de monedero electrónico en el POS con importe manual',
    'description': """
        Funcionalidades:
        - Botón "Recarga" visible en la pantalla de producto del POS.
        - Wizard (NumberPopup) para introducir el importe a recargar.
        - Añade automáticamente el producto de recarga configurado al pedido.
        - El precio introducido es el precio final (sin descuento).
        - Configuración del producto de recarga en Ajustes del POS.
    """,
    'version': '19.0.1.0.0',
    'author': 'TPV Plus',
    'category': 'Point of Sale',
    'depends': ['point_of_sale'],
    'assets': {
        'point_of_sale._assets_pos': [
            'tpv_plus_pos_recharge/static/src/**/*',
        ],
    },
    'data': [
        'views/res_config_settings_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}

