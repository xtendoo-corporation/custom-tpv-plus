{
    "name": "TPV Purse Price Variable",
    "summary": "Recarga de monedero con precio variable en POS",
    "version": "19.0.1.0.0",
    "author": "TPV Plus",
    "category": "Point of Sale",
    "license": "LGPL-3",
    "depends": [
        "point_of_sale",
        "pos_loyalty",
    ],
    "data": [
        "views/product_template_views.xml",
    ],
    "assets": {
        "point_of_sale._assets_pos": [
            "tpv_purse_price_variable/static/src/app/models/pos_order_line.js",
            "tpv_purse_price_variable/static/src/app/services/pos_store.js",
        ],
    },
    'images': ['static/description/icon.png'],
    "installable": True,
    "application": False,
    "auto_install": False,
}

