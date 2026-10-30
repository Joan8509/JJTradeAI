# Correcciones de ejecución del 29/10/2026

Autorizadas tras la revisión privada de la sesión. No cambian v5, el mínimo
activo3% por banda, el estudio5%, rangos, spread, expiración, cantidad,
deduplicación, frescura ni habilitación de órdenes reales.

## Primera detección

La caducidad de30s incluye el tiempo antes de que el monitor/cola estuviera
preparado. El lector consulta el primer EXIT de símbolo/vela/dirección en la
auditoría intravela, dentro de su lectura SQLite limitada a2s. Usa el índice
de recepción existente y guarda el resultado en una caché acotada a512claves.
No añade llamadas al proveedor ni espera al envío de Telegram. Hay un costo
de consulta inicial medido en evidencia privada; no afirmar latencia cero.

Si falta evidencia o la retención no permite cubrir la vela, la cola bloquea
con SIGNAL_WINDOW_UNAVAILABLE; no inventa una hora nueva. La ventana durable
solo puede adelantarse, nunca renovarse con un trade más reciente. Se conserva
aunque haya caducado. Los intentos, avisos inciertos y autorizaciones son
independientes. No se vuelven a operar señales históricas al cargar el cambio.

## Salidas simuladas

El usuario eligió explícitamente: stop al siguiente Bid válido disponible,
aunque la pérdida supere20%; ganancia con mínimo igual al objetivo elegido.

Solo las nuevas salidas de simulación observada incorporan estas políticas:

- LOSS_LIMIT: NEXT_VALID_BID_STOP_V1 / SIMULATED_MARKET. Se ejecuta a Bid
  efectivamente observado después de crear la venta, con tamaño disponible,
  frescura y controles de contrato/sesión. No queda sujeto al Bid del disparo.
- TARGET: TARGET_FLOOR_V1 / LIMIT al objetivo calculado sobre compra real
  simulada. Un Bid superior al objetivo no eleva el mínimo de venta.
- Cierres manuales y órdenes anteriores conservan su autorización y límite.

El mismo pedido mantiene su identidad y cantidad remanente. El broker local
deduplica ejecuciones y liquidez; la conciliación acepta un precio menor que
el Bid de disparo únicamente para la política explícita de stop observado.
No cambia fills anteriores. Si un objetivo pendiente cae hasta el stop, registra
primero un disparo durable ligado a la compra; confirma su cancelación y concilia
antes de crear la venta por stop del remanente. Un reinicio conserva ese disparo,
incluso si el precio se recupera entre pasos. La operación anterior permanece
auditada como cancelada/parcial, nunca se modifica para aparentar otro precio.
Esto se aplica solo a TARGET_FLOOR_V1, no a límites manuales/legados.
No es envío a Schwab.
Una cotización inexistente/obsoleta o sin liquidez no produce un fill ficticio;
el stop es disparador, nunca garantía de precio o de pérdida máxima.

## Cotizaciones y errores

Los fallos de decodificación/identidad se aíslan por catálogo o contrato;
un catálogo inválido no congela las cotizaciones de posiciones sanas. Para
una posición con respuesta inválida se espera1s antes de reintentar; catálogos
conservan15s. No se usa la respuesta inválida como precio ni identidad.

Autorización, HTTP, transporte y errores no identificados siguen compartidos;
se conserva el máximo Retry-After del proveedor, sin acortarlo. Los diagnósticos
solo guardan códigos fijos y contadores, nunca respuestas ni excepciones
originales. OPTION_RESPONSE_INVALID distingue respuestas inutilizables de
RATE_LIMITED, TRANSPORT_FAILURE y HTTP_FAILURE. No prueba retrospectivamente
cuál causó un error genérico anterior.

## Validación y activación

Pruebas sintéticas y SQLite temporales: consumidor tardío, ventana que solo
se adelanta, parcialidad y deduplicación de stops, objetivo mínimo, aislamiento
de catálogos y respeto global de429/Retry-After. Validación real de primer EXIT
mediante consultas RO, sin reenviar avisos ni crear órdenes.

Estado de carga, resultados exactos y recibos: CURRENT_CONTEXT y diario actual.
Evidencia y respaldo de fuentes/estados en exports/trade_review/
2026-10-29_execution_repair/. No reiniciar colector para estos cambios.
