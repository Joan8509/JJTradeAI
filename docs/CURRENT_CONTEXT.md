# Continuidad actual de JJTrade AI

Actualizado 2026-11-16T13:49:57-05:00. Usuario solicita guardar en GitHub todas las mejoras.
Checkpoint tecnico: [GITHUB_CHECKPOINT_2026-11-16.md](GITHUB_CHECKPOINT_2026-11-16.md).
Publicacion pendiente hasta comprobar SHA remoto; no afirmar push antes.

## Reglas y prioridades vigentes

Leer [STRATEGY_OPERATING_CONTRACT.md](STRATEGY_OPERATING_CONTRACT.md).
Entrada inmediata al cumplir estrategia, sin esperar Telegram ni cierre de vela.
V7: apertura dentro de bandas iniciales y actuales, expansion3% por cada banda,
precio fuera/direccion/media, reloj30s desde primer cruce y primera senal,
frescura3s. No renovar relojes ni rearmar colas consumidas. ITM/primeras5OTM,
sin ATM, spread<=0.08, rangos/autorizaciones actuales y vencimiento vigente.
Preview exacto con fondos/cargos, reserva durable, nunca reenviar lo incierto.
Primera compra excluye otras companias. Objetivo por fila sobre fill real con
LIMIT DAY en broker; stop20% LOCAL al Bid cancela/confirma objetivo antes de
cerrar remanente. No STOP/OCO nativo. Ventas manuales externas se concilian.
SEV25 permanece bloqueado: excepcion implementada sin consentimiento activado.

## Mejoras recientes y evidencia

[REAL_ENTRY_PREPARATION.md](REAL_ENTRY_PREPARATION.md): catalogos desde9:00ET,
renovacion metadata y prioridad de cotizaciones; no autoriza por precios viejos.
[REAL_ENTRY_DISPATCH.md](REAL_ENTRY_DISPATCH.md): lectura conjunta e IPC.
[ENTRY_LATENCY_REVIEW_2026-11-15.md](ENTRY_LATENCY_REVIEW_2026-11-15.md):
normalizacion limitada al contrato, no sleep(0) y primer EXIT indexado.
[REAL_ENTRY_STATE_READER.md](REAL_ENTRY_STATE_READER.md): conexionROporhilo,
snapshot nueva cada llamada; benchmark local2.6296->0.2271ms, no tiempo broker.
Alternativa por fondos: maximo2previews, segunda opcion estrictamente mas barata,
sin eludir advertencias ni renovar senal. Revision financiacion1.
[REAL_ACK_RECOVERY_2026-11-05.md](REAL_ACK_RECOVERY_2026-11-05.md) y
[REAL_EXIT_RECOVERY_2026-11-05.md](REAL_EXIT_RECOVERY_2026-11-05.md).
[OPTION_TARGET_EVIDENCE.md](OPTION_TARGET_EVIDENCE.md): observador asincrono de
quotes ya recibidas; modelo delta/spread y estudios SOLO investigacion, sin
nuevos filtros de entrada. No subir3%a5% ni esperar confirmacion por estudios.

Ultima verificacion operacional HISTORICA16Nov13:40:58-13:41:02ET: host REAL
lectorrevision1 y monitores actuales, sin bloqueos reportados. No acredita estado
actual ni recepcion Telegram/fill nuevo. Registro quotes sin nuevas muestras
durante aquella comprobacion; medir proxima entrada natural por fases. No se
verifican procesos/conexiones de nuevo por la tarea de GitHub ni se altera cola.
CompanionSIM tenia BOT_NOT_READY separado; no declarar toda SIM saludable.

## Validacion y continuidad privada

Este guardado: 503 pruebas dirigidas aprobadas en 87.955 segundos; escaneo de secretos sin hallazgos.
No es suite completa global verde; ver revision15Nov para fallos pendientes.
149tests anteriores de lector/ejecucion pasaron antes de su recarga16Nov.
Recibos, hashes, benchmarks y validacion detallada estan en revisiones privadas.

Leer docs/SESSION_STATE_2026-11-16.md (local ignorado), ultimo diario disponible
y contexto completo previo en
exports/trade_review/2026-11-16_github_checkpoint/CURRENT_CONTEXT.before.md.
Se preservan originales y diarios anteriores. No inferir estado privado desde
GitHub. Siguiente: verificar publicacion y medir proxima operacion natural sin
activar compras de prueba. No repetir tareas completadas por compactacion.
