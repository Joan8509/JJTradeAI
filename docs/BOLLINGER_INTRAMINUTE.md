# Detección de Bollinger dentro del minuto

El scanner con transporte WebSocket suscribe `trades`, `bars` y `updatedBars`
en **una sola conexión** de Alpaca. Con las 17 compañías configuradas cabe
dentro del límite de 30 símbolos de Basic. No cambia el plan contratado.
El feed sigue siendo IEX: no representa todas las operaciones del mercado ni
garantiza coincidencia exacta con TC2000/thinkorswim.

`RealtimeBollingerWorker` recibe sin ejecutar los análisis pesados en el hilo
del socket. Persiste las velas oficiales y conserva la evaluación de estrategias
en una cola ordenada independiente. Esa evaluación lee la última revisión
oficial de la vela; no vuelve a escribir una versión antigua encolada.
Los errores o la saturación de las colas invalidan la detección rápida.

Para cada operación apta calcula Bollinger de 20 períodos, desviación 2,
`ddof=0`: 19 cierres anteriores de 15 minutos y el precio observado actual.
La referencia anterior usa sus 20 cierres ya terminados. Exige la última barra
de cierre oficial anterior; al abrir la sesión verifica la sesión previa del
calendario. No convierte una vela todavía abierta en una referencia cerrada.

La regla `v3_bandas_en_apertura` permanece compartida con el playback: cierre
anterior dentro de bandas, apertura dentro de las bandas recalculadas a la
apertura, **ambas bandas abriéndose**, exposición del precio, avance desde la
apertura y punto medio en la misma dirección. No se agregan umbrales de fuerza
sin evidencia. SMA, barreras y patrones históricos siguen siendo descriptivos.

Un stream conectado antes de comenzar la vela usa su primera operación apta
observada como apertura provisional. Cuando llega la primera barra oficial,
su apertura sustituye esa referencia. Tras una conexión a mitad de vela,
una apertura perdida o una operación anterior recibida fuera de orden, espera
la primera barra oficial: no usa arbitrariamente el precio de reconexión como
apertura. Operaciones tardías pueden revisar una apertura provisional; no
se puede conocer de antemano una corrección que aún no llegó del proveedor.

Se excluyen operaciones no aptas para precio según las condiciones documentadas
por Alpaca, incluyendo odd lots, referencias previas, ventas fuera de secuencia,
operaciones extendidas y condiciones desconocidas. Se descartan duplicados,
precios inválidos, fechas futuras y operaciones con más de 3 segundos de edad
al recibirlas o procesarlas. Este máximo es una protección de frescura, no un
filtro estadístico de rentabilidad. Correcciones y cancelaciones se guardan
como evidencia y ponen en cuarentena la vela actual del símbolo; no son una
nueva salida operable.

El receptor publica el último estado aproximadamente cada 100 ms; el radar
lo consulta cada 250 ms cuando el flujo está activo. No promete observar ni
notificar cada exposición que dure menos que esos intervalos. Inmediatamente
antes de enviar comprueba de nuevo que la salida siga presente y el precio y
la conexión estén recientes. El envío de Telegram y la llegada al teléfono
añaden demora externa. No se ha medido aún latencia real de este modo en sesión.

El contexto SMA y de playback se calcula en un hilo aparte, después de detectar,
con disponibilidad exacta al instante del tick. No se suma un minuto al tick
ni se incorporan resultados futuros. La evaluación posterior de un evento con
segundos usa la primera vela completa de un minuto posterior a la detección;
no pretende reconstruir el recorrido intraminuto con OHLC de un minuto.

`bollinger_tick_latest`, `bollinger_tick_runtime` y `bollinger_tick_audit` son
datos privados dentro de la base SQLite ignorada por Git. El registro bruto
conserva las últimas 200 000 observaciones, podadas cada minuto, y un máximo
temporal de 7 días comprobado al iniciar. Las colas son acotadas. La tabla
`bollinger_notice_timing.source_kind` distingue `TRADE` de `BAR` y mantiene
fecha real de recepción. La deduplicación de Telegram sigue siendo una por
chat/proveedor/feed/compañía/vela/lado, también después de reiniciar.

Si el flujo deja de estar conectado y reciente, se conserva el fallback de
velas de un minuto con sus reglas de frescura anteriores. Si el flujo está
activo, un minuto antiguo no puede resucitar una salida que ya se retrajo.
Listas de más de 30 símbolos con transporte `auto` continúan usando polling.

## Activación y verificación

El scanner que ya estaba ejecutándose mantiene el código cargado al iniciar.
Para cargar esta versión, detenerlo desde **Iniciar o detener buscador**,
introducir las claves de Alpaca en los campos privados de la app y volver a
iniciarlo con los 17 símbolos configurados. No enviar claves por el chat.
No detener el proceso actual desde la terminal sin claves de reemplazo.

El receptor nuevo deja `bollinger_tick_runtime.state=CONECTADO` únicamente
después de confirmar la suscripción a operaciones. El radar informa
`price_mode=TRADES` durante la sesión si ese heartbeat está reciente.
La ausencia de heartbeat o el modo `MINUTE_BARS` no confirman activación rápida.
Fuera de sesión no se generan avisos. No requiere aprobación de Schwab.

Validación: las 768 pruebas del conjunto completo pasaron. Las pruebas
incluyen primera vela de sesión, ambos lados, expansión
obligatoria, saltos, reconexión, retracción antes del envío, duplicados,
condiciones de operación, correcciones y bloqueo del analizador de barras.
Un ensayo de 1 000 operaciones sintéticas con historial ya preparado midió
mediana de geometría 0.0342 ms y p95 0.0468 ms. No mide socket, SQLite, Telegram,
teléfono ni rentabilidad. El resultado operativo requiere observar una sesión.

Fuentes primarias consultadas el 13 de octubre de 2026:

- [Alpaca Real-time Stock Data](https://docs.alpaca.markets/us/docs/real-time-stock-pricing-data)
- [Alpaca Stock Minute Bars: condiciones y disponibilidad](https://alpaca.markets/learn/stock-minute-bars)

No conecta ni envía órdenes al broker. El texto de Telegram conserva las
cuatro líneas y el botón que abre la revisión manual.
