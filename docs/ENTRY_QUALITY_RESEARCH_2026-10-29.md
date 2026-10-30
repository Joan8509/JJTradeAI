# Calidad de entradas: investigación y evidencia de ejecución

El usuario pide estudiar y construir mejoras que reduzcan pérdidas, manteniendo
la estrategia y la entrada rápida. Esta implementación distingue tres tareas:
detectar la estrategia, ejecutar con sus controles y comprobar qué cambios
mejoran resultados. No hay garantía de beneficio ni nueva autorización real.

`entry_quality_research.py` calcula BandWidth/medio, distancia de salida como
porcentaje del ancho, edad de vela y coste relativo del spread. Sus resultados
son observaciones, nunca autorizaciones o filtros de órdenes/avisos.
`scripts/study_entry_quality.py` compara seis propuestas prefijadas sobre datos
congelados de19compañías/60sesiones. Usa referencias de10a20sesiones anteriores,
misma compañía y cuarto de hora; excluye muestras del día o aún no disponibles.
Una referencia desconocida permanece desconocida, sin sustitución ni relleno.

La selección usa40sesiones y el contraste20, con resultados por compañía/lado,
mañana/resto, horizontes1/3/5/10min y cuatro bloques cronológicos de cinco días.
Son datos retrospectivos ya examinados; no llamarlos validación independiente.
No se recalculan entradas más tarde para hacer cumplir un filtro nuevo.
Ninguna propuesta añada espera, cotización ni llamada de red al camino de compra.

El contraste no respalda activar las propuestas ensayadas. El ancho sobre
percentil20 histórico descartó54movimientos favorables y37desfavorables a cinco
minutos en las mañanas. Mayor anchura por sí sola no demostró mayor continuidad.
La propuesta elegida en desarrollo, salida de al menos1% del ancho, tampoco
superó el contraste de mejora y estabilidad. No se cambian3% por banda ni su
observador5%, objetivos, stop20%, frescura, selección de contratos o avisos.

Se añade un recibo `ENTRY_QUALITY_OBSERVATION` al trabajador opcional de la cola,
después de guardar orden/claim y despertar el monitor. Conserva geometría y
cotización elegida, tamaños, antigüedad, expansión descriptiva y tiempo desde
primera señal. No consulta historial/proveedor, no decide ni reintenta órdenes.
La cola opcional sigue acotada: puede perder evidencia si está llena; esto
debe contarse y no reinterpretarse como ausencia de señal u orden. Un fallo
de diagnóstico no vuelve incierta una orden ya registrada. No copia secretos,
URL de autorización ni datos de cuenta al recibo. Referencia histórica en vivo
todavía no precargada: se registra `NOT_PRELOADED`, no una validación ficticia.

La memoria guarda pérdidas y ganancias; no aprende a cambiar automáticamente
reglas con estos datos. Para comparar salidas de opciones siguen haciendo falta
varias sesiones de Bids/Asks, tamaños y tiempos. Un movimiento favorable de la
acción no equivale al beneficio de un contrato. El estudio de objetivos previo
solo dispone de seis caminos de opciones completos desde cerca de compra.

Evidencia detallada privada en
`exports/trade_review/2026-10-29_entry_quality_deep/`: protocolo previo,
features, CSV, auditoría de38operaciones, resultados/pruebas y recuperación.
Estado de carga y comprobaciones operativas: CURRENT_CONTEXT y diario. Tener
el código en disco no demuestra que el radar lo haya cargado o emitido recibos.
