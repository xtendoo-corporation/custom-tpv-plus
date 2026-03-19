# tpv_purse_price_variable

Extiende el POS de Odoo 19 para permitir precio manual en productos marcados como `Precio modificable`.

Uso previsto:
- Marcar el producto trigger del `eWallet` como `Precio modificable`.
- Al añadirlo en el POS, se solicita el importe.
- El cliente se fuerza antes de la recarga para que `pos_loyalty` pueda crear o actualizar su monedero con ese saldo.

