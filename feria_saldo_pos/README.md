# feria_saldo_pos

Vinculo opcional de **feria_saldo** con el **TPV de Odoo**. Se instala solo cuando estan instalados `feria_saldo` y `point_of_sale`.

## Como se activa
Ajustes → **TpvPlus** → *Vinculo con el TPV de Odoo*:

1. Marca **Vincular con el TPV de Odoo**.
2. Elige el **TPV** (necesita una sesion abierta), el **metodo de pago** del TPV con el que se registra el cobro (por ejemplo uno llamado
   "Monedero") y el **producto auxiliar**.

El producto auxiliar (**«Cobro monedero TpvPlus»**, referencia `TPVPLUS-COBRO`) se crea con el modulo: servicio, disponible en el TPV, sin
impuestos. Si quieres IVA, ponselo con un impuesto **incluido en el precio** para que el total del pedido coincida con el cobro.

## Que hace
- Cada **COBRAR** crea un **pedido pagado** en el TPV: una linea del producto auxiliar con el importe del cobro, a nombre del cliente y
  con el metodo de pago elegido. El pedido usa el mismo uuid que el cobro, asi nunca se duplica.
- Las **recargas no** crean pedido: son un pago por adelantado, no una venta (si no, la venta se contaria dos veces).
- **Nunca bloquea un cobro.** El monedero se confirma primero; despues se intenta crear el pedido. Si el TPV no puede (no hay sesion abierta,
  esta ocupado o mal configurado) el cobro queda igualmente registrado y el pedido queda **pendiente**; un cron lo reintenta cada 5 minutos
  (y se puede reintentar a mano). Ver **TpvPlus → Operaciones → Pedidos del TPV**.
- Los pedidos se crean de uno en uno (bloqueo en PostgreSQL), porque el TPV bloquea su propia numeracion: sin eso, cobros simultaneos
  fallaban al crear el pedido.
- **Anulaciones:** si el cobro aun no se habia enviado, el pedido se cancela. Si ya estaba en el TPV, queda marcado **"Revisar en el TPV"** y
  se abre una incidencia: hay que abonar o revisar ese pedido alli (no se crea un reembolso automatico).
- Solo se vinculan los cobros hechos **con la opcion activa**; los anteriores no se envian.

## Probado
10 tests (pedido pagado con producto auxiliar, sin sesion → reintento, fallo del TPV sin bloquear el monedero, duplicados, anulaciones,
validacion de ajustes) y con servidor real de 4 procesos: **30 cobros simultaneos → 30 pedidos del TPV al momento, 61 cobros = 61 pedidos
pagados, saldo exacto**.
