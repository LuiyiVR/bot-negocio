# 📱 Guía del Bot — Negocio de Viajes
### Para: LAVR · FEDE · SPAIDER RATA

---

## ¿Cómo entrar al bot?

1. Abre Telegram
2. Busca el bot por su nombre (te lo pasa LAVR)
3. Presiona **Iniciar / Start**
4. Aparece el menú principal — **todo se maneja con botones, no tienes que escribir comandos**

> ⚠️ Solo los 3 socios tienen acceso. Si alguien más lo intenta, el bot lo rechaza.

---

## 🏠 Menú Principal

```
🛒  Nueva Venta
📦  Pedidos
📋 Mis Ventas   |  👥 Todas las Ventas
📅 Resumen Mes  |  🗓 Otro Mes
🏦 Ver Inversión |  💸 Gasto Inversión
```

---

## 🛒 Nueva Venta (venta directa, sin pedido)

Úsalo cuando ya hiciste la venta y quieres registrarla de inmediato.

**Pasos:**
1. Presiona **🛒 Nueva Venta**
2. Selecciona **tu nombre** (botón)
3. Escribe los **16 dígitos de la tarjeta** usada
4. Escribe **qué se vendió** (ej: Airbnb CDMX 3 noches)
5. Escribe **cuánto le cobraste al cliente** (ej: `2500 MX`)
6. Escribe **cuánto te costó a ti** (ej: `2000 MX`)
7. El bot muestra el resumen y registra la ganancia ✅

> 💡 **Formato de montos:**
> - Pesos mexicanos → `1500 MX`
> - Dólares → `100 USD` (el bot convierte automáticamente al tipo de cambio del día)

---

## 📦 Pedidos — El flujo más importante

Los pedidos sirven cuando alguien consigue una oportunidad y la quiere ofrecer a los demás antes de tomarla, o cuando uno la trabaja en dos tiempos (primero la reserva, luego la completa).

### 📝 Crear un Pedido

1. Presiona **📦 Pedidos** → **📝 Crear Pedido**
2. Selecciona el tipo: **Vuelo / Airbnb / Tour / Otro**
3. Pega el **link** del servicio (o presiona ⏭ Saltar si no tienes)
4. Escribe una **descripción breve** (ej: Airbnb CDMX 3 noches del 5 al 8 abril)
5. Escribe el **total de la compra** — lo que marca el servicio (ej: `2000 MX`)
6. Escribe el **cobrado al cliente** — lo que tú le cobras (ej: `2500 MX`)
7. El pedido queda publicado y los demás socios reciben una **notificación automática**

---

### ✅ Aceptar un Pedido (cuando te llega notificación)

Cuando otro socio crea un pedido, te llega un mensaje así:

```
🔔 Nuevo Pedido Disponible

#5 🏠 Airbnb — CDMX 3 noches
💸 Total de compra: $2,000.00 MXN
💰 Cobrado al cliente: $2,500.00 MXN
📈 Ganancia: $500.00 MXN
👤 Creado por: FEDE

[✅ Aceptar pedido #5]
```

Si quieres trabajarlo:
1. Presiona **✅ Aceptar pedido #5**
2. El bot te muestra los detalles completos
3. Presiona **✅ Sí, lo acepto**
4. El pedido queda **reservado para ti** — los demás se enteran que ya fue tomado
5. **Tómate el tiempo que necesites** para realizar la compra

> ⚠️ Si dos socios intentan aceptar el mismo pedido al mismo tiempo, solo el primero lo obtiene.

---

### ✔️ Completar un Pedido (cuando ya hiciste la compra)

Una vez que realizaste la compra del producto:

1. Presiona **📦 Pedidos** → **✅ Mis Pedidos**
2. Verás tus pedidos en proceso con el botón:
   ```
   [✔️ Ya lo completé — #5 CDMX 3 noches]
   ```
3. Presiona el botón
4. Escribe los **16 dígitos de la tarjeta** con la que hiciste la compra
5. ¡Listo! La venta queda registrada automáticamente y los socios reciben confirmación ✅

---

### ⏳ Ver Pedidos Pendientes

Si quieres ver qué pedidos hay disponibles (sin esperar notificación):

1. **📦 Pedidos** → **⏳ Pendientes**
2. Aparece la lista con botón de aceptar para cada uno

---

## 📋 Mis Ventas

Muestra todas las ventas que tú has registrado con su ganancia.

1. Presiona **📋 Mis Ventas**
2. Selecciona tu nombre
3. Ver historial completo con fechas, tarjetas y ganancias

---

## 👥 Todas las Ventas

Muestra un resumen de todos los socios: cuántas ventas tiene cada uno y su ganancia total.

---

## 📅 Resumen del Mes

Muestra el resumen financiero completo del mes actual:

- Ventas por socio
- Total cobrado y gastado
- Ganancia del mes
- Estado de la inversión inicial ($15,000 MXN)
- **Cuánto le toca a cada socio** (se divide en partes iguales)

Para ver un mes anterior: **🗓 Otro Mes** → escribe `MM/AAAA` (ej: `03/2026`)

---

## 🏦 Inversión Inicial

El negocio arrancó con **$15,000 MXN** entre los 3 socios.

### Ver estado de la inversión
**🏦 Ver Inversión** — muestra:
- Inversión inicial total
- Cuánto se ha gastado de ella
- Saldo disponible

### Registrar un gasto de la inversión
Cuando se gaste dinero de los $15,000 (ej: publicidad, dominio, etc.):

1. **💸 Gasto Inversión**
2. Escribe en qué se gastó (ej: Anuncio de Facebook)
3. Escribe el monto (ej: `500 MX`)

---

## 💡 Tips rápidos

| Situación | Qué hacer |
|---|---|
| Conseguí un Airbnb con descuento y ya lo vendí | 🛒 Nueva Venta |
| Encontré una oportunidad y quiero que alguien la trabaje | 📦 Pedidos → 📝 Crear Pedido |
| Me llegó notificación de un pedido | Presiona ✅ Aceptar en la notificación |
| Ya hice la compra del pedido que acepté | 📦 Pedidos → ✅ Mis Pedidos → ✔️ Ya lo completé |
| Quiero ver cuánto gané este mes | 📅 Resumen del Mes |
| Se gastó dinero de la inversión | 💸 Gasto Inversión |

---

## ❌ Cancelar en cualquier momento

En cualquier paso puedes presionar el botón **❌ Cancelar** para salir sin guardar nada.

Para regresar al menú principal desde cualquier pantalla presiona **🏠 Menú Principal**.

---

*Cualquier duda con LAVR* 🤙
