# Recepción rápida y guardado ordenado de velas

Petición29/10: priorizar detección→entrada inmediata manteniendo estrategia y
controles. Medición del receptor antes del cambio: evento de velas alcanzó
4.013s en el hilo que también procesa trades; no atribuye por sí solo toda la
demora histórica. Separación probada primero en bases y quotes sintéticas.

Un único worker ordenado guarda las velas oficiales. El hilo de trades solo
encola; recibe confirmación después del commit y entonces actualiza referencias
y entrega el callback de análisis. No hay otra WebSocket ni copia de colector.

Las velas pendientes que afectan referencias o apertura impiden generar EXIT
con referencias previas. Se sigue capturando la apertura del primer trade apto,
sin sustituirla por otro observado al terminar SQLite. Tras commit se recupera
la referencia; únicamente un trade nuevo, fresco y apto puede generar salida.
Velas de minutos intermedios de la vela actual no afectan los19cierres previos
ni la apertura y no invalidan una salida vigente por ese solo guardado.

Colas acotadas y escritura canónica obligatoria: fallo de almacenamiento o
saturación detiene el receptor; no se omiten barras ni se fabrican referencias.
Esto separa el procesamiento de trades del I/O de velas, pero SQLite sigue
compartiendo un escritor con publicación. Medir publicación bajo carga; no
afirmar que todos los atrasos o el arranque lento estén resueltos.

SIGNAL_READY,CHECK_FAILED yORDER_REGISTERED opcionales usan el worker auxiliar
ya existente en producción. No se espera ese diagnóstico antes de comprar;
timestamps representan el evento original. Claim durable, ventana30s, controles
y actualización SUBMITTED siguen siendo obligatorios y síncronos. Evidencia
opcional puede perderse si cola llena o cierre; no reconstruirla como si existiera.

Se mantienen3% activo y5% observacional, v5, frescura3s/30s, stop20%, límites de
contratos/rangos/spread y protecciones de avisos/dedup. RealesOFF. Pruebas y
carga efectivas se registran en CURRENT_CONTEXT y diario, no se infieren de este
documento. Evidencia privada exports/trade_review/2026-10-29_fast_ingest/.
