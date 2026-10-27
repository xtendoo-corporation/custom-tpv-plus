# feria_saldo

Monedero de feria para Odoo 20 Community. La tarjeta/pulsera solo guarda un identificador;
el saldo vive aqui y es **la suma de movimientos confirmados** (nunca un campo editable).

La caja es **una unica pantalla tipo kiosko** (`/feria`), sin login ni PIN, con cuatro botones grandes:
**COBRAR, RECARGAR, VER PEDIDOS, VER SALDO**. Al pulsar uno, la pantalla pregunta **"¿Qué cliente?"**.
Los formularios de Odoo quedan detras, solo para gestion (contactos y codigos, movimientos,
ajustes, cierre).

Estado: servidor + pantalla de caja hechos y probados. **Fase 6 (Kubernetes, CloudNativePG, backups) pendiente.**
No hay dispositivos, emparejamiento, operadores ni sesiones.

## Pantalla de caja (`/feria`)

- Inicio: los cuatro botones. Nada mas. En movil se apilan; en pantalla ancha forman una cuadricula 2×2.
- **¿Qué cliente?**: un solo campo siempre enfocado. Sirve para pasar la tarjeta, escribir el codigo o escribir parte
  del **nombre** (una coincidencia abre directamente al cliente; varias muestran una lista para elegir). La busqueda por
  nombre solo encuentra clientes que tienen tarjeta. Tras leer, muestra nombre y saldo (o sigue con el importe).
- **Lectura de tarjetas** (la misma tecnica que `custom-tpv-plus/TPVPlus` de Odoo 19):
  1. Lector USB/PDA en modo teclado (RFID o NFC): escribe el codigo + Enter en el campo enfocado.
  2. Web NFC: Chrome Android con HTTPS, o el `NDEFReader` que inyecta la app Android (se arranca solo al abrir la pantalla).
     Si la tarjeta tiene un registro de texto NDEF se usa ese texto; si no, el UID (`04:A3:1F` o `04a31f`, se normaliza).
  3. `window.handleNfcScan(id)`: entrada global que llama la app Android cuando lee un tag.
  Una tarjeta solo se atiende en la pantalla "¿Qué cliente?" (en el inicio se ignora) y una lectura repetida en la misma
  pantalla se descarta. El codigo se da de alta en el cliente (pestana Feria); sirve el mismo identificador que ya use
  el TPV si las tarjetas son las mismas.
- Para usar la app Android `TPVPlus` con esta pantalla hay que apuntar su `TPV_URL` a `https://servidor/feria`
  (la app solo entrega tags a paginas de ese mismo host y bloquea certificados no validos).
- VER PEDIDOS enseña las operaciones guardadas en este modulo para ese cliente (cobros, recargas, anulaciones y ajustes), las mas
  recientes primero, con el importe, la fecha y el saldo que quedo. No lee los pedidos de ventas de Odoo.
- COBRAR / RECARGAR: cliente → nombre y saldo → teclado de importe → confirmar. "COBRADO"/"RECARGADO" solo
  aparece tras la confirmacion del servidor. VER SALDO y VER PEDIDOS solo consultan.
- Sin conexion: franja roja **SIN CONEXION: NO SE PUEDE OPERAR** y botones bloqueados; se recupera sola.
- Operacion en vuelo: se guarda en el navegador **antes** de enviarse con su uuid. Si no hay respuesta queda
  **PENDIENTE DE CONFIRMAR** y consulta `GET /movements/{uuid}` (con reintentos con backoff y jitter) hasta
  resolver, tambien tras recargar la pagina. Reenviar el mismo uuid es seguro (idempotente). Tras resolver una
  operacion pendiente el resultado no se cierra solo.
- Kiosko: pantalla completa al primer toque, sin zoom ni menu contextual, pantalla siempre encendida (si el
  navegador lo permite), vuelta automatica al inicio a los 60 s sin tocar, y `manifest` para instalarla como app a
  pantalla completa (Chrome Android: menu → "Anadir a pantalla de inicio").
- Los ficheros de la pantalla llevan un numero de version en la URL: tras actualizar el modulo el navegador carga siempre
  la pantalla nueva (no se queda con una copia vieja).
- Junto a ONLINE hay un boton **Caja** (ver abajo).
- Menu Odoo **Feria → Abrir pantalla de caja** abre la misma pantalla.

## Caja: contar y cerrar

El boton **💰 Caja** (arriba, junto a ONLINE) enseña el **efectivo que debe haber en el cajon** y permite contarlo y cerrarlo:

- **Efectivo esperado** = fondo que se dejo en el cierre anterior + recargas cobradas − devoluciones (recargas anuladas).
  Los **cobros no mueven efectivo** (gastan saldo del monedero): solo se muestran como ventas, a titulo informativo.
  Una recarga manual hecha desde Odoo cuenta como efectivo.
- **Contar caja**: se escribe lo contado y se ve al momento "La caja cuadra", "Sobran X" o "Faltan X". Se puede guardar como recuento
  (queda registrado y no cambia el periodo).
- **Cerrar caja**: se cuenta, se elige **cuanto se deja para el dia siguiente** ("No dejar nada" lo vacia, "Dejar todo", o un importe) y se
  confirma. Se anota cuanto se retira (contado − dejado) y la diferencia. El dia siguiente empieza con lo que se dejo como fondo.
- Los periodos se cortan por **movimiento**, no por hora: cada operacion cuenta en un solo periodo, ni repetida ni perdida. El cierre toma
  el mismo bloqueo que los cobros, asi que ninguno se cuela entre el calculo y el cierre.
- Es idempotente como los cobros (uuid) y se guarda antes de enviarse: con un corte de red a mitad del cierre queda "PENDIENTE" y se
  resuelve una sola vez al volver. Los registros son de solo anadir (no se editan ni se borran).
- API: `GET /cash` (importe esperado y desglose) y `POST /cash` (`{uuid, kind: count|close, counted, kept, note}`).
- En Odoo: **Feria → Caja → Cierres y recuentos** (con filtros por cierres, recuentos y "con diferencia").

## Revisar en Odoo sin la pantalla

Al pulsar **Feria** en Odoo se abre el **Resumen**: lo de hoy (recargas y cobros, con su numero), el dinero (saldo en circulacion, efectivo que debe
haber en caja, ultimo cierre), el estado (clientes con tarjeta y, si hay vinculo con el TPV, los pedidos pendientes o por revisar)
y las ultimas 12 operaciones, con botones a cada pantalla. "Actualizar" muestra los datos de ese momento. La pantalla de caja (kiosko) es otra
entrada del menu, ya no la primera: antes, pulsar Feria abria el kiosko en otra pestana.

Menu **Feria**: *Resumen*, *Saldos de clientes* (con el total en circulacion y filtros con saldo/bloqueados), *Operaciones* (**Pedidos (cobros)**,
**Recargas**, **Todos los movimientos**, agrupables por dia, cliente, tipo...), *Caja* (cierres y recuentos), *Informes*
(resumen por dia) y *Configuracion* (codigos, ajustes). Todo exportable a CSV/XLSX con la exportacion estandar.

## Vinculo con el TPV de Odoo (modulo `feria_saldo_pos`)

Es opcional y vive en un modulo puente que **se instala solo cuando estan `feria_saldo` y el TPV (`point_of_sale`)**; `feria_saldo` no
depende del TPV. Ver `feria_saldo_pos/README.md`.

## App Android (`custom-tpv-plus/TPVPlus`)

Es un WebView con NFC nativo que abre la pantalla de caja dentro de la app:
- **Primer arranque:** pide la direccion del servidor (`192.168.0.113:8080`; se anade `http://` y `/feria` si faltan) y la guarda.
- **Cambiar la direccion:** 5 toques seguidos en la esquina superior derecha. Si no se puede conectar, sale sola con
  "Reintentar" y la direccion para corregir.
- **NFC:** la app lee el tag (texto NDEF o UID en hexadecimal) y se lo entrega a la pagina, que lo busca como codigo del cliente.
  Solo se entregan tags a paginas del servidor configurado.
- El boton "atras" de Android vuelve a los 4 botones sin cerrar la app; la pantalla se mantiene encendida.
- Permite `http` (red local sin HTTPS). Para usarla fuera de una red de confianza hace falta HTTPS en el servidor.
- Compilar: `cd TPVPlus && ./gradlew assembleDebug` → `app/build/outputs/apk/debug/app-debug.apk`.
  Pruebas de la logica de la direccion: `./gradlew testDebugUnitTest`.

## Hallazgos de Odoo 20 que condicionan el diseno

| Tema | Hallazgo | Como se ha resuelto |
|---|---|---|
| Permisos | `ir.model.access` + `ir.rule` se unifican en `security/ir.access.csv`; sin fila = denegado. `_sql_constraints` se **ignora**: `models.Constraint/UniqueIndex`. | CSV nuevo y `models.Constraint`. |
| Grupos | Cuelgan de `res.groups.privilege`; en usuarios el campo es `group_ids`. | `res_groups_privilege_feria`. |
| Parametros | `ir.config_parameter.get_param` **ya no existe**: `get_str/get_int/get_float/get_bool`. | Unico punto de lectura: `feria.movement._feria_param`. |
| Rutas | Tipos `http`, `jsonrpc` y `json2`; `/json/2` es la API generica nueva. | Controladores propios `type='http'`, JSON REST plano, `auth='none'`, token propio. |
| Lecturas | Las GET `http` se sirven por defecto con cursor **de solo lectura/replica**; una replica atrasada podria decir "no existe" de un cobro confirmado. | Todas las rutas con `readonly=False` (siempre primaria). |
| Aislamiento | Odoo usa REPEATABLE READ: tras esperar un `FOR UPDATE` el snapshot es viejo y PostgreSQL aborta; 50 cobros al mismo contacto agotarian los 5 reintentos. | `serial_env()`: transaccion propia READ COMMITTED con commit antes de contestar. |
| Nombres | `BaseModel._register` existe. | `_feria_register`. |
| Multi-BD | Con varias bases y `dbfilter=.*` las rutas `auth='none'` dan 404. | Produccion: una sola BD o `dbfilter` fijo. Tests: `--db-filter='^feria_test$'`. |
| Modo offline | Los cobros no pasan por el POS. `offline_mode=limited` esta **bloqueado** (no se puede guardar). | Datos/API preparados (`uuid`, `sequence`, `hash`, `state`). |

## Instalacion (Doodba de este repo)

Vive en `odoo/custom/src/private/feria_saldo` (`private: ["*"]` en `addons.yaml`).

```bash
docker compose exec odoo odoo -d feria_test -i feria_saldo --stop-after-init
```

Despues: Feria → Contactos (pestana Feria: codigos y saldo; recarga manual) y abrir
`http://servidor:8069/feria` en la PDA / PC de caja.

## Tests

```bash
docker compose exec odoo odoo -d feria_test -u feria_saldo --test-tags /feria_saldo \
    --stop-after-init --workers=0 --http-port=18069 --db-filter='^feria_test$'
```

43 tests: saldo, idempotencia, anulacion, limite, solo-anadir, hash, incidencias, bloqueos y API HTTP (busqueda por
nombre, tarjeta y cliente, tipos solo de back office rechazados, redes permitidas, pagina kiosko sin PAGAR ni PIN).

Concurrencia **real** (los tests transaccionales no pueden probarla), con servidor multi-worker:

```bash
docker compose exec -d odoo odoo -d feria_test --workers=4 --http-port=18069 --gevent-port=18072 \
    --db-filter='^feria_test$' --logfile=/tmp/feria_srv.log
python3 scripts/stress_test.py http://localhost:18069 CODIGO_TARJETA 50
```

Medido: 50 cobros simultaneos al mismo contacto → 33 confirmados y 17 `INSUFFICIENT_BALANCE` (saldo inicial 100, cobros de 3):
saldo final exacto, nunca negativo, `balance_after` todos distintos; mismo uuid x100 → un movimiento y 99 repeticiones
con el mismo resultado; despues, secuencia 1..N sin huecos y cadena de hash intacta.

Pantalla en navegador real (Chrome + selenium): `scripts/e2e_kiosk.py` (recorrido completo, capturas escritorio y movil),
`scripts/e2e_nfc.py` (lectura de tarjeta imitando la app Android: NDEFReader, texto NDEF, `handleNfcScan`, teclado) y `scripts/e2e_offline.py` (red cortada a mitad de cobro: PENDIENTE DE CONFIRMAR → se resuelve y se cobra una sola vez).

## API (`/feria/api/v1`, sin autenticacion)

Importes como **cadenas** decimales (`"12.50"`). Fechas ISO 8601 UTC. El acceso se controla por red (ver abajo).

```bash
B=https://servidor/feria/api/v1
curl -s $B/health                                  # sondas readiness/liveness
curl -s $B/config
curl -s "$B/contacts/lookup?code=04:A3:1F"         # VER SALDO por tarjeta
curl -s "$B/contacts/lookup?contact_id=7"          # ... o por cliente
curl -s "$B/contacts/search?q=marta"               # buscar por nombre (solo clientes con tarjeta)
curl -s $B/movements -H 'Content-Type: application/json' -d '{
  "uuid":"3f2b8c1e-5a47-4d0e-9b0a-1c2d3e4f5a6b","code_used":"04A31F","type":"COBRAR","amount":"4.50",
  "created_at_device":"2026-10-26T14:00:00Z"}'     # COBRAR / RECARGAR (con "contact_id" en vez de "code_used" tambien vale)
curl -s $B/movements/3f2b8c1e-5a47-4d0e-9b0a-1c2d3e4f5a6b      # resolver "pendiente"
curl -s "$B/movements?contact_id=7&limit=20"
curl -s "$B/orders?contact_id=7"                   # VER PEDIDOS
```

Errores `{error_code, message}`: `CODE_UNKNOWN` (404), `CODE_BLOCKED` (403), `INSUFFICIENT_BALANCE` (409, incluye `balance`),
`DUPLICATE` (409, mismo uuid con datos distintos; incluye el original), `FORBIDDEN`/`LIMIT_EXCEEDED` (403),
`VALIDATION_ERROR` (400). El mismo uuid con los mismos datos devuelve 200 con el resultado original y `"duplicate": true`.
`GET /movements/{uuid}` desconocido: 404 con `"status":"unknown"`.

## Decisiones y limites a conocer

- **Solo COBRAR (resta) y RECARGAR (suma)** desde la pantalla. AJUSTE y ANULACION solo desde Odoo (gestor; la anulacion es un contra-movimiento) y la API los rechaza.
- **Sin login ni PIN: el control de acceso es la red.** Cualquier equipo que llegue a `/feria` puede cobrar y recargar.
  Ajustes → **Redes permitidas** (por ejemplo `192.168.1.0/24`) limita la pantalla y la API a esas redes (vacio = cualquiera;
  `/health` queda siempre abierto). Detras de un proxy hay que activar `proxy_mode` para que Odoo vea la IP real. Use ademas
  VLAN/Wi-Fi propio y TLS en el ingress. Los movimientos no registran quien los hizo, solo el uuid, la hora y la secuencia.
- Ajustes → **Importe maximo por operacion** (0 = sin limite) se aplica solo a la pantalla.
- Cadena de hash **global** (`hash_prev`, `hash`, `sequence`), serializada con un bloqueo de PostgreSQL (consultas muy cortas;
  suficiente para una feria). Hueco de secuencia y reloj desajustado (>5 min) se anotan como incidencia interna pero no rechazan.
  Las incidencias y la verificacion de la cadena ya no tienen entrada en el menu (el codigo y los datos siguen ahi).
- Solo-anadir se garantiza en el ORM (`write`/`unlink` bloqueados); no hay trigger en PostgreSQL.
- Sin estado en el proceso (todo en PostgreSQL): valido con varias replicas de Odoo.
- `Monetary` de Odoo es `float` en Python: aritmetica y validacion en `Decimal`; columna `numeric`; en la pantalla el importe
  nunca pasa por numeros de coma flotante (se envia como texto).
- La moneda es el **euro** por defecto: el modulo activa el euro y lo fija en Ajustes → Moneda del monedero (se puede cambiar).
  La pantalla pone el simbolo que corresponde a la moneda del servidor (`€`), no uno escrito a mano.
- `/orders` lee `sale.order` solo si `sale` esta instalado (si no, lista vacia).
- Informes: cierre = pivot de movimientos (dia × tipo) con exportacion estandar CSV/XLSX; sin informe de conciliacion propio.
- TLS con certificado propio y pinning, ingress, IP virtual, PodDisruptionBudget, CloudNativePG y backups: **fase 6 pendiente**.
- Textos de interfaz en espanol directamente (modulo privado, sin `.po`).
