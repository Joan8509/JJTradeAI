# Continuidad de conexión y automatización REAL

Revisión solicitada el 03/11/2026: compra automática rápida, objetivo elegido y
stop del 20%. La pausa solicitada anteriormente sigue vigente; esta revisión
no autoriza rearmar la cola ni enviar operaciones de prueba.

## Correcciones

- Preparar el transporte TLS de órdenes al conectar el ejecutor, antes de las
  señales. Carga certificados y crea el cliente; no envía solicitudes ni adelanta
  una compra. La autenticación y las comprobaciones finales siguen vigentes.
- Recuperar el protocolo de previsualización en un hilo independiente. Una
  respuesta lenta no detiene la publicación del estado del host. Solo hay una
  comprobación simultánea; una comprobación pendiente no autoriza entradas.
- Tras verificar el formato de Schwab, actualizar tanto el cliente de entrada
  como el del objetivo antes de declarar el protocolo disponible.
- Conservar los avisos de ejecuciones rechazados explícitamente por Telegram
  con 429 aunque posteriormente cambie la cantidad ejecutada. Reintentar tras
  Retry-After, conservando deduplicación y el evento original. Retirar avisos
  de estado del objetivo que ya quedaron obsoletos. Una entrega incierta sigue
  sin reenviarse automáticamente.

## Recorrido comprobado en pruebas aisladas

La señal válida y actual prepara la compra con los controles de contrato,
presupuesto y caducidad existentes. Una reserva persistente impide duplicar
compras. La primera entrada consume la cola de las demás compañías.

El objetivo se calcula sobre el precio medio realmente ejecutado. Los casos
10%, 20%, 35% y 100% conservan exactamente el porcentaje seleccionado y requieren
previsualización vinculada al precio/cuenta/contrato/cantidad. Tras la compra
final confirmada se prepara la venta LIMIT DAY en Schwab. WORKING confirma su
colocación; FILLED confirma la venta. Una respuesta de recepción no es un fill.

El stop se activa al Bid <= 80% del costo medio real, incluso con entradas
pausadas. Si hay un objetivo pendiente, primero se cancela y confirma el
remanente mediante Schwab, y después se envía la venta LIMIT al Bid disponible.
Los casos de desconexión, ejecución parcial y carrera entre cancelación y fill
no liberan cantidades sin confirmar ni crean una segunda venta de lo vendido.

Las observaciones de órdenes, precios, entradas, avisos, preparación y objetivo
tienen bucles independientes. Un error de red se vuelve a observar, conservando
las reservas. Una orden cuyo envío es incierto requiere conciliación; no se
repite su POST a ciegas.

## Alcance y verificación

Pruebas completas: 239 casos, sin credenciales de producción ni órdenes/avisos
reales. Evidencia privada: `connection_continuity_validation.json` en
`exports/trade_review/2026-11-03_real_readiness/`.

Los recibos de conexión y estados de cuenta permanecen privados. Una lectura
histórica no demuestra disponibilidad actual.

La carga y la comprobación final se registran en CURRENT_CONTEXT y el diario;
no inferirlas de este documento ni de una prueba aislada. La primera colocación
auténtica del nuevo objetivo LIMIT sigue pendiente de una futura posición
autorizada: no se fabrica una compra para demostrarla.

El stop sigue en la VPS; no se ha instalado un STOP/OCO nativo en Schwab. El
20% es el disparador de salida, y el precio final depende de cotización,
conexión y ejecución. El objetivo LIMIT, cuando Schwab confirma que está activo,
permanece allí sin esperar que la VPS detecte el toque. La renovación OAuth
normal es automática; si Schwab exige nueva autorización del usuario, la app
debe mostrarlo y se requiere reconexión. Ninguna corrección modifica SIM,
la regla de bandas del 3%, los porcentajes ni las compañías elegidas.
