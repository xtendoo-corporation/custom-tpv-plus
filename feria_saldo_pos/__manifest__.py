{
    'name': 'Feria Saldo - Vinculo con el TPV',
    'version': '20.0.1.0.0',
    'category': 'Services',
    'summary': 'Cada cobro del monedero de feria crea un pedido en el TPV de Odoo con un producto auxiliar',
    'description': """
Se instala solo cuando estan instalados feria_saldo y el TPV (point_of_sale).
Se activa en Ajustes > Feria > Vinculo con el TPV de Odoo. Es opcional y nunca bloquea un cobro:
si el TPV no puede recibir el pedido (por ejemplo no hay sesion abierta), el cobro queda registrado
y el pedido se reintenta.
""",
    'author': 'Xtendoo',
    'license': 'LGPL-3',
    'depends': ['feria_saldo', 'point_of_sale'],
    'auto_install': True,
    'data': [
        'security/ir.access.csv',
        'data/feria_saldo_pos_data.xml',
        'views/feria_pos_link_views.xml',
        'views/res_config_settings_views.xml',
        'views/feria_overview_views.xml',
    ],
}
