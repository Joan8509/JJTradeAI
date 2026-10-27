# Monitor de simulación: consultas fuera del bloqueo de entradas

27/10/2026 ET. Petición: analizar pérdidas y corregir fallos demostrables,
sin cambiar la estrategia ni prometer eliminar pérdidas de mercado.

La lectura consistente de ledger/fills y el replay de geometría de las
entradas están en `exports/trade_review/2026-10-27_loss_review/` (privado).
La muestra es intradía, no una sesión completa ni evidencia para optimizar
filtros por resultado. Las entradas perdedoras revisadas cumplían la regla
vigente en sus registros. No hay trayectoria completa de cotizaciones de
cada opción para demostrar la primera oportunidad de salida perdida.

## Correcciones

`ManualWorkflow.observe` consultaba al proveedor manteniendo su RLock,
compartido con la fase final de entrada. Una espera HTTP podía bloquear esa
fase y envejecer el trade. Ahora cada consulta ocurre antes de tomar el
bloqueo de mutación; se releen estado de orden, posición, sesión y frescura
antes de actuar. Otro bloqueo serializa observadores, sin bloquear entradas
durante REST. Claims, deduplicación de liquidez y conciliación se conservan.

Un fallo de cotización abortaba el ciclo antes de gestionar otros contratos.
Ahora se gestionan los contratos con datos utilizables y al final se informa
el fallo: el monitor continúa no apto para nuevas compras si hay exposición
sin gestionar. No se casan compras pendientes tras un fallo de cotización.
Errores de conciliación/mutación no se silencian ni se consideran recuperados.

El status privado incluye revisión de observación, duración del ciclo y código
de error por lista fija. Nunca almacena texto arbitrario del proveedor ni URLs.
La misma tolerancia de diez segundos del heartbeat permanece intacta.

No cambia Bollinger, expansión mínima, apertura, feed, prima, spread, strikes,
stop20%, objetivos ni salida manual. Stop es disparador, no precio garantizado.
No órdenes reales, mensajes de prueba, reenvíos ni rearme de solicitudes inciertas.

## Validación y carga

Primera tanda: 91 pruebas OK, incluyendo bloqueo concurrente durante consulta,
cancelación mientras llega cotización, aislamiento de fallo y compra única.
La tanda de salidas detectó una expectativa antigua que también falla con
observe de HEAD: confundía disparar venta con llenar usando la misma cotización.
Se exige nueva cotización posterior y luego se comprueba cierre confirmado.
Ver evidencia de comparación `baseline.py` y resultado final en continuidad.

La carga exige comprobación nueva de exposición, solicitudes en curso,
claims y avisos. No reiniciar colector ni Windows para este cambio.
Revisión esperada de runtime: `network_outside_workflow_lock_v1`.

Actualización14:30ET: carga radar-only comprobada14:28ET sin exposición,
con barrera de claims y dos incertidumbres preservadas tras probar ausencia
de orden en ledger y broker. Hashes de contabilidad/autorizaciones/claims/
estrategia iguales; procesos colector/interfaz y tarea conservados.154dedup
originales intactos. Tandas91/77/52OK, más34repetidas para status saneado.
HTTPS200; TelegramgetMe/getChatOK sin enviar mensajes. Una consulta REST
Schwab14:30:30ET acredita quoteage0.896s; ningún stream adicional ni orden.
Falta medir bajo exposición nueva; monitor vacío rápido no demuestra latencia
real de gestión de posiciones. Sin commit/push solicitado ni ejecutado.
