# Preparación de entradas antes de la apertura

El usuario prioriza la apertura/mañana sin pedir cambiar la estrategia ni
limitar la operativa al horario matutino. Se mantienen las señales intravela
y operaciones únicamente dentro de sesión regular, mínimo1%/ambas bandas,
datosIEX3s/cotizacionesSchwab30s, rangos/spread0.08/OTM5 y stop10. RealesOFF.

## Preparación anticipada

El hilo existente de la cola prepara el calendario completo de CALL y PUT
solo para filas **ARMED**, entre4y2minutos antes de su apertura oficial.
Para9:30ET, es09:26≤hora<09:28. No hay hora local fija: usa opens_at del
plan validado contra calendario oficial. No crea tarea ni conexión Alpaca.

Una consulta como máximo por ciclo, separadas al menos5s entre inicios,
manteniendo el transporte compartido mínimo1s/Retry-After. Cada lado queda
preparado una vez mientras siga vigente el TTL existente5min del calendario.
Se detiene el inicio de consultas2min antes de abrir para dejar margen al
arranque regular; una respuesta externa anormalmente lenta puede aún demorar.
También vuelve a comprobar el reloj después de consultar exposición.

No prepara si el monitor no está listo, hay posiciones/órdenes pendientes,
la cola está vacía/pausada/en mantenimiento o hay backoff del proveedor.
Los errores no arman, consumen ni pausan planes y no crean claims/órdenes;
se guardan códigos sanitizados y se conserva la consulta normal de respaldo.

**Prepara calendario e identidad, no un precio de compra.** No aumenta su
TTL5min ni permite usar precios viejos. A la señal regular, consulta la cadena
del vencimiento aplicable con precios actuales y revalida todos los controles.
Si aún son subsegundo, se conserva la reutilización segura ya implementada;
si no, refresca el contrato. Expiración/regla de14ET no se alteran.

No garantiza preparar toda una cola grande dentro de la ventana ni una compra
instantánea: las consultas externas pueden tardar. Ninguna fila que no haya
logrado prepararse queda autorizada por eso: conserva el camino normal y
las mismas comprobaciones. Cada fila sigue autorizando una sola compra.

## Evidencia y operación

`opening_preparation.py` no compra, envía avisos ni toca la estrategia. El
QueueRunner lo llama únicamente si no hubo entrada regular en ese ciclo.
La preparación se registra como PREOPEN_CATALOG_READY/FAILED sin cambiar
el estado/autorización. El status privado informa revisión preopen_catalog_v1.
No se alteran Telegram ni su deduplicación; no se activan órdenes reales.

Pruebas aisladas: ambos lados/espaciado/no claims, límites de ventana, monitor,
pausa/directquotes, exposición, reloj que avanza,429y consulta de precios
regular obligatoria. La prueba de apertura compra simulada conserva un solo
claim y no inventa un fill a partir de una cotización anterior a la orden.

La revisión de historial de la próxima sesión usa exactamente TickGeometry
._history sin construir un writer: consultas RO, referencia REGULAR y períodos
oficiales. Los resultados privados y la carga efectiva figuran en continuidad.
No sustituye trades actuales, conexión reciente ni apertura real por símbolo.
Preparar empresas antes de09:26 permite aprovechar toda la ventana; armarlas
después sigue permitido y utiliza las consultas normales cuando llegue señal.
