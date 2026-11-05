# Avisos de ejecución y seguimiento independiente de salidas reales

Correcciones de avisos de ejecución y seguimiento de salidas. Las operaciones
individuales y sus evidencias permanecen privadas.

## Confirmaciones reales

`real_trade_notices.py` observa únicamente ejecuciones confirmadas del diario
REAL de la cuenta seleccionada. Envía cuatro líneas para compra y venta,
identificando REAL, compañía, lado, cantidad acumulada, precio medio y hora ET.
La compra muestra el objetivo elegido y el stop del 20%; la venta informa el
resultado bruto de esa ejecución, separado de comisiones.

El emisor carga directamente el perfil privado DPAPI de Telegram que usa el
radar. La tarea REAL no hereda el entorno privado inyectado al radar y no existe
una conexión genérica `exports/telegram/connection.json` en esta instalación.
No copia claves al entorno ni al diario de notificaciones.

Un hilo independiente evita que Telegram bloquee compras o ventas. Cada aviso
tiene una reserva durable previa al envío, por cuenta/solicitud/cantidad
ejecutada. Reinicios no repiten entregas aceptadas o inciertas. Un rechazo
explícito HTTP429 respeta Retry-After; no equivale a un envío incierto.
La primera instalación marca las ejecuciones anteriores como históricas,
sin presentarlas como operaciones nuevas. El corte se conserva en reinicios.

La evidencia de la prueba autorizada permanece privada. La aceptación del
servidor no demuestra lectura del mensaje en el teléfono.

## Objetivo y stop

La comprobación de precios y la observación de órdenes tienen hilos y bloqueos
separados. Un GET lento de orden no retiene el monitor del precio. El recorrido
rápido comprueba posiciones cada 200 ms, reutilizando cotizaciones de menos de
un segundo y respetando el espaciado REST existente. Esto no significa que se
reciba una cotización nueva cada 200 ms. La espera del ciclo descuenta el tiempo
ya consumido por su trabajo.

El objetivo se calcula sobre el precio medio realmente ejecutado. Con entrada
a $0.50 y objetivo10%, un Bid válido de $0.55 activa la venta automáticamente,
sin esperar cierre de vela, interfaz, aviso de estrategia o envío de Telegram.
El Ask o Last del contrato no sustituyen al Bid ejecutable para activarla.
Stop20%, reservas de cantidad, cancelación antes de reemplazo y prohibición de
reenviar órdenes inciertas permanecen. La conciliación concurrente conserva un
fill terminal aunque llegue durante una cancelación.

Estado de esta primera entrega: el monitor de la VPS gestionaba el disparo y
el ejecutor enviaba la LIMIT. La actualización posterior del mismo día incorpora
la [venta objetivo colocada en Schwab](REAL_BROKER_PROFIT_LIMIT_2026-11-03.md).
Stop20% permanece en la VPS y no se añade OCO. La ejecución efectiva la confirma
Schwab. No se enviaron operaciones reales para probar estas incorporaciones.

## Validación y activación

Las pruebas cubren la confirmación de fill frente a un simple acuse de orden,
fills parciales, reinicios, deduplicación, tiempo de espera de Telegram,
rechazo429, separación de hilos, objetivo10% exacto y el caso de precios de la
operación auditada. Se conservan las regresiones anteriores de stop y cola.
El recuento final, la carga efectiva y la cola pausada se registran en
`CURRENT_CONTEXT.md` y el diario. La evidencia privada queda en
`exports/trade_review/2026-11-03_real_readiness/`.
