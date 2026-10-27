# Entrada: caché compartida sin espera de red

27/10/2026 ET. Usuario insiste en compra al detectar la estrategia, priorizando
eliminar la entrada tardía. Esto no autoriza cotizaciones antiguas, primas o
spreads fuera de lo aprobado ni órdenes reales.

Se encontró otra serialización después de reparar el bloqueo del workflow:
get_chain, get_catalog_chain y get_entry_chain mantenían el mismo Lock del
cliente de mercado durante HTTP. La espera de un contrato o compañía impedía
leer una caché lista o iniciar la consulta de otra entrada/salida.

Ahora se toma una instantánea bajo lock, se consulta fuera y se publica bajo
lock. Una respuesta antigua en vuelo no sustituye otra más reciente. La caché
completa/calendario continúa separada de la parcial y de contratos seleccionados.
No se altera fecha de cotización del proveedor. Un fallo tardío no acorta un
Retry-After ya mayor; éxito paralelo no borra backoff.

SchwabTransport sigue espaciando inicios de petición al menos un segundo y
aplicando429/Retry-After. No se crean trabajadores ni streams adicionales;
se permite avanzar a los ya existentes sin esperar la respuesta ajena. Entrada
continúa revisando señal3s, opción/spot30s, calendario, prima, spread y OTM5,
con claim durable único antes de dispatch y fills posteriores observados.

Código: manual_trade_service.py; telegram_manual_runtime.py publica
market_cache_revision=nonblocking_market_cache_v1 para acreditar carga.
Pruebas nuevas: tests/test_market_cache_concurrency.py, escenarios full-chain,
catálogo y quote seleccionado con HTTP retenido, caché utilizable durante espera,
no retroceso de respuesta nueva y respeto del mayor Retry-After.

Validación inicial:83tests de mercado/cola/monitor/practice OK;24tests de
concurrencia/quote seleccionado/runtime OK. No son medición de latencia en mercado.
Carga y comprobación efectiva se registran en continuidad y evidencia privada
exports/trade_review/2026-10-27_entry_cache_lock/. No declarar activa antes
de confirmar market_cache_revision del nuevo proceso. No reiniciar colector.

14:58ET: ACTIVA desde14:56:53ET, revisión acreditada en nuevo radar; permanece
network_outside_workflow_lock_v1 de la reparación anterior. Sin exposición ni
órdenes pendientes antes/después; barrera de claims durante recarga. Dos estados
UNCERTAIN conservados y ausencia de orden probada en ambos registros. Hashes de
contabilidad, claims, autorizaciones y estrategia iguales;154dedup originales
intactos, colector/interfaz y definición de tarea conservados. Cero órdenes o
mensajes del agente. Auditoría14:57:52: HTTPS200, monitor listo, Telegramautenticado.

Tanda adicional126tests de cola/backoff/OAuth/riesgo/contratos OK. Tres pruebas
específicas finalesOK; la tercera usa motor real aislado y datos ficticios:
despacha una compra con señal/contrato válidos mientras otra consulta sigue
retenida, y otra pasada no duplica la compra. No implica fill instantáneo ni
latencia de mercado medida. Mantener medición con nuevas señales.

El primer guard falló sin demostrar monitor detenido. Revisión posterior mostró
heartbeat actualizado. Se corrigió el reloj del guard para muestrearlo después
de leer status, evitando diferencias negativas al recibir heartbeat nuevo entre
lecturas. No se amplió tolerancia ni se eludió la validación previa a cargar.
No cambios de estrategia, stop ni primas; no commit/push. Evidencia privada y
copias de fuentes previas conservadas para recuperación/sincronización.
