# Plazo desde la primera estrategia completa: activado17Nov

Estado comprobado 2026-11-17T20:07:43.996648-05:00: V9 cargada en colector, radar y REAL.388pruebas
ROOT aprobadas; verificaciones de carga y conservacion en CURRENT_CONTEXT.

Actualizacion posterior: el usuario autoriza expresamente "activala, me gusta
esa mejora". Se aplica el candidato con respaldo exacto de las fuentes
anteriores, sin descartar cambios locales. La validacion en la instalacion y
la carga de procesos se documentan en CURRENT_CONTEXT y la evidencia privada
complete_clock/activation. Las notas siguientes describen la preparacion
anterior a esa autorizacion; no representan el estado posterior de carga.

El usuario pregunta el17Nov si las mejoras para conservar los movimientos
estudiados ya estan preparadas. Se preparo una implementacion V9 en una copia
aislada. No se modificaron los archivos operativos, servicios ni colas.
La regla vigente sigue siendo V8 y el plazo desde primer cruce autorizado06Nov.

La alternativa comienza los30s cuando se cumplen juntas apertura dentro de
bandas anteriores/iniciales/actuales, salida, direccion/media y3% por ambas
bandas. La primera señal completa puede actuar inmediatamente: no espera30s.
Se conserva el instante del primer cruce como evidencia, pero no como vencimiento.

El primer instante completo se guarda en SQLite en la misma transaccion que
publica la señal, antes del despertar IPC. No se renueva por retraccion,
pausa, reinicio o reconexion. Si falta evidencia al reconectar, no se inventa.
SIM y REAL usan el plazo completo; se mantienen frescura3s, controles de
contrato/cotizacion/fondos/preview, deduplicacion, primera entrada y salidas.
La lectura del primer instante es una consulta por clave, sin nueva llamadaHTTP.

Validacion aislada:388pruebas aprobadas en65.067s. Incluye maduracion posterior
al cruce, entrada inmediata, vencimiento exacto30s, memoria/persistencia,
rechazo de relojes alterados, readerSIM/REAL y autorizacion de la cola SIM.
Se prohibieron conexiones externas; los testsHTTP locales usan datos sinteticos.
Los cambios se contrastaron con hashes de los originales operativos.

El parche se comprobo sin aplicarlo mediante git apply --check
--ignore-space-change, por los finales de linea Windows. La comparacion de
exportaciones y las limitaciones permanecen en la revision privada tc_exports.

Activar esta alternativa sustituiria expresamente la regla06Nov que excluye
rupturas cuya expansion madura tarde. Puede admitir una estrategia completa
varios minutos despues del primer cruce; no es solamente una mejora de red.
Los archivos15m no prueban una ejecucion o resultado de opcion en ese instante.
La autorizacion de activacion y las guardas operativas actuales siguen pendientes.

Artefactos privados: exports/trade_review/2026-11-17_complete_clock/ con
candidate.patch, candidate/, sources.json, validation.json, apply_check.json,
README.md y SHA256SUMS.txt. Ninguno se aplico a la instalacion activa.
