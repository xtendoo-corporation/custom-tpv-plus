{
    'name': 'Feria Saldo',
    'version': '20.0.1.0.0',
    'category': 'Services',
    'summary': 'Monedero de feria con tarjetas NFC/RFID: saldo en servidor y pantalla de caja de una sola pagina',
    'description': """
Fuente de verdad de contactos, codigos, movimientos y saldo para el monedero de feria.
El saldo es siempre la suma de movimientos confirmados; las tarjetas solo contienen un identificador.
""",
    'author': 'Xtendoo',
    'license': 'LGPL-3',
    'application': True,
    'depends': [],
    'data': [
        'security/feria_saldo_security.xml',
        'security/ir.access.csv',
        'data/feria_saldo_data.xml',
        'views/feria_code_views.xml',
        'views/feria_movement_views.xml',
        'views/feria_cash_views.xml',
        'views/feria_overview_views.xml',
        'views/feria_incident_views.xml',
        'views/res_partner_views.xml',
        'views/res_config_settings_views.xml',
        'wizard/feria_manual_movement_wizard_views.xml',
        'views/feria_menus.xml',
    ],
}
