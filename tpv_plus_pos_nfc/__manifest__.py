{
    'name': 'TPV Plus - Escáner NFC / Código de Barras POS',
    'summary': 'Botón para escanear NFC (RFID) o código de barras en el POS',
    'description': """
        Funcionalidades:
        - Botón "Escanear NFC o Código de barras" en la pantalla de producto del POS,
          ubicado encima del botón de Recarga.
        - Wizard limpio que detecta automáticamente:
            • Lectura de código de barras (pistola/escáner).
            • Lectura de tag RFID vía Web NFC API.
        - El valor escaneado/leído se muestra en un campo "Valor".
    """,
    'version': '19.0.1.0.0',
    'author': 'TPV Plus',
    'category': 'Point of Sale',
    'depends': ['point_of_sale', 'tpv_plus_pos_recharge'],
    'assets': {
        'point_of_sale._assets_pos': [
            'tpv_plus_pos_nfc/static/src/**/*',
        ],
    },
    'images': ['static/description/icon.png'],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}

