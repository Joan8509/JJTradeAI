# Incorporación solicitada: SPX y SPCX

Revisión del 13 de octubre de 2026. Se agregó SPCX a config/watchlist.json,
manteniendo los 17 símbolos anteriores: 18 configurados tras este cambio.
La detección conserva v4, apertura propia dentro, salida direccional y ambas
bandas abriéndose. No cambia el feed IEX ni el transporte automático.

SPCX identifica actualmente SpaceX, cuya cotización comenzó el 12/06/2026,
según su [página oficial](https://ir.spacex.com/faqs-and-contact/).
El ETF que antes usaba SPCX cambió a SPCK el 07/04/2026, según su
[emisor](https://spcketf.com/). No se sustituye SPCX por SPCK.

stock_instruments.py identifica SpaceX y fija un límite inicial del historial
en 12/06/2026 UTC. El adaptador de Alpaca limita tanto la petición como las
barras recibidas a esa identidad, excluyendo precios del antiguo ETF incluso
si el proveedor devuelve filas anteriores. Las consultas previas al comienzo
devuelven ausencia de datos sin consultar al proveedor. No existían barras
SPCX en la base local al verificarlo, por lo que no se borró historial.

Telegram usa SPCX · SpaceX. No se inventó un rango de primas: mostrará
Sin rango definido hasta incorporar una referencia del usuario. Las SMA o
referencias largas sin suficiente historial quedan desconocidas.

SPX permanece en excluded_symbols como pendiente de una fuente del índice.
La [publicación de Alpaca del 02/09/2026](https://alpaca.markets/blog/alpaca-launches-index-options-via-trading-api/)
confirma que sus datos de mercado todavía no incluyen el nivel del índice.
Opciones sobre SPX no equivalen a barras del índice. No se usa SPY como alias
de SPX ni se presenta SPX como vigilado. Se preguntó si la solicitud se refiere
al índice o a SPX Technologies, cuyo símbolo es SPXC según su
[página oficial](https://spx.com/investor-relations-hub/).

El buscador existente conserva la suscripción de 17 símbolos hasta reiniciar
desde la app con la lista de 18 y las credenciales privadas de Alpaca.
La recepción de barras/trades y la suscripción SPCX deben verificarse después
del reinicio. Agregado a configuración no significa conexión ya comprobada.

Validación: pasaron las 794 pruebas del conjunto completo. Las nuevas
regresiones cubren solicitud previa al IPO sin acceso al ETF antiguo,
filtrado de respuesta con ticker reutilizado y Telegram con nombre correcto
sin inventar rango de primas. El radar se reinicia con esta identificación;
las 17 compañías existentes continúan hasta cargar la nueva lista del scanner.
