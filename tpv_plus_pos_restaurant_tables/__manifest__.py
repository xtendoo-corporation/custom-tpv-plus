{
    'name': 'TPV Plus - Mesas Restaurante POS',
    'summary': 'Grid visual de mesas con asignación persistente de clientes en POS Restaurante',
    'description': """
        Funcionalidades:
        - Grid visual de mesas en el plano del restaurante (reemplaza el mapa estándar).
        - Asignación persistente de clientes a mesas (campo feria_partner_id).
        - El cliente asignado sobrevive al cierre de sesión, finalización de pedido, etc.
        - Generación automática de 100 mesas al entrar en el plano.
        - Botones para añadir/eliminar mesas manualmente.
        - Verificación de duplicados: un cliente no puede estar en dos mesas.
        - Auto-asignación del cliente al abrir una mesa con cliente asignado.
    """,
    'version': '19.0.1.0.0',
    'author': 'TPV Plus',
    'category': 'Point of Sale',
    'depends': ['pos_restaurant'],
    'assets': {
        'point_of_sale._assets_pos': [
            'tpv_plus_pos_restaurant_tables/static/src/**/*',
        ],
    },
    'images': ['static/description/icon.png'],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}

