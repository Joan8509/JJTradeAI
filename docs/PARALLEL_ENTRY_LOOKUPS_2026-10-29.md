# Entrada sin espera entre compañías

La búsqueda REST de una compañía se ejecutaba en el mismo trabajador que
recorría la cola. Una respuesta lenta retenía las señales de las demás.
Ahora el Companion habilita dos trabajadores de búsqueda, con máximo dos
trabajos pendientes/en curso y uno por plan. El coordinador continúa
recorriendo las compañías cada 200 ms y drena trabajo nuevo sin pausa adicional.
Los usos sin Companion conservan el comportamiento síncrono por defecto.

Los trabajadores comparten el mismo cliente, caché y transporte Schwab:
separación de solicitudes y Retry-After no cambian. No se aumenta el límite
de peticiones ni se abre otro flujo de mercado. Las consultas se realizan
fuera del bloqueo de ejecución; registrar la orden sigue serializado mediante
el bloqueo del workflow y la reclamación SQLite durable previa al despacho.
Una autorización modificada durante REST no permite ejecutar cantidad/objetivo
antiguos. Pausar o cerrar el Companion impide nuevos despachos posteriores
a sus comprobaciones; una reclamación ya comprometida requiere conciliación.

No cambia estrategia, horario, frescura, rangos, spread, selección de contratos,
stop ni ventana de 30 segundos desde la primera detección. Una autorización
continúa siendo una solicitud por compañía/sesión, sin rearme automático.
Las salidas, avisos y diagnósticos mantienen sus trabajadores independientes.
No garantiza encontrar contrato válido, ejecución inmediata ni rentabilidad.

Validación: tests/test_parallel_entries.py usa bases temporales y cotizaciones
sintéticas. Comprueba que la segunda compañía registra su orden mientras otra
búsqueda sigue bloqueada, capacidad máxima dos, ausencia de duplicados, pausa,
autorización editada, cierre, datos vencidos, backoff compartido y llenado solo
con cotización posterior. Se ejecuta además la regresión de cola, latencia,
auxiliares, Companion, ventana de señal, reparación de salidas y conexión.
La comprobación de carga y sus resultados se registran en el diario/contexto;
el paso de tests no acredita tiempos reales de una próxima sesión.
