# Roadmap de fuentes de datos

## Objetivo

Reducir errores de exportación manual sin romper el MVP actual basado en
TXT/CSV TC2000.

## Decisión de arquitectura

La app debe conservar TC2000 TXT/CSV como fuente validada y agregar una segunda
fuente mediante proveedores de datos intercambiables.

Fuente inicial:

- `TC2000_TXT`: carga local auditada.

Fuente futura:

- `MARKET_DATA_API`: descarga velas para 15m, 1H y 1D desde un proveedor externo.

Base implementada:

- `data_providers.py` centraliza la preparación de indicadores y la carga
  TC2000 desde archivos locales o uploads de la app.
- `DataBundle` conserva `provider`, `datasets` y `metadata` para que una API
  futura pueda reportar fuente y temporalidades sin cambiar el motor.
- `data_source_metadata()` convierte cada `DataBundle` en una salida segura para
  reportes: solo conserva `provider`, `timeframes` y `files`; no propaga
  credenciales ni campos arbitrarios del proveedor.
- Los reportes generados por la app, `validation_runner.py` y
  `validation_batch.py` pueden incluir `data_source` con proveedor y archivos
  usados.

## Reglas para la fase API

- La API no debe saltarse `data_quality`.
- `data_quality` debe validar coherencia OHLC aunque los datos no pasen por el
  cargador TC2000.
- Los datos descargados deben producir las mismas columnas canónicas que el
  cargador TC2000: `date`, `open`, `high`, `low`, `close`, medias móviles,
  volumen y Worden si está disponible.
- Si el proveedor no entrega una columna metodológica, debe quedar
  `NO_DISPONIBLE`; no se inventa.
- La app debe permitir comparar una evaluación TC2000 TXT contra una evaluación
  API del mismo símbolo y sesión antes de reemplazar el flujo manual.
- Las credenciales de API no deben guardarse en reportes JSON ni en el diario.

## Candidatos a evaluar

- Polygon.io
- Alpaca Market Data
- Tradier
- Interactive Brokers

## Primera implementacion Alpaca

La base inicial incluye `live_market.py` para validar y agregar barras,
`alpaca_market_data.py` para historial REST y WebSocket de acciones, y
`market_data_probe.py` como diagnostico de solo lectura.

Las credenciales se leen exclusivamente desde variables de entorno:

```powershell
$env:ALPACA_API_KEY="tu_clave"
$env:ALPACA_API_SECRET="tu_secreto"
$env:ALPACA_DATA_FEED="iex"
```

Para comprobar historial o recibir barras cerradas de un minuto:

```powershell
.\venv\Scripts\python.exe market_data_probe.py --symbol SPY --days 10
.\venv\Scripts\python.exe market_data_probe.py --symbol SPY --stream
```

`iex` sirve para desarrollar, pero la validacion final debe usar `sip` para
representar el mercado consolidado. Este adaptador no contiene endpoints de
ordenes. Aun faltan la integracion visual y la seleccion de contratos de
opciones.

## Persistencia y continuidad

`market_store.py` conserva cada barra de un minuto en SQLite usando proveedor,
feed, simbolo y timestamp como identidad unica. Una barra corregida se
actualiza sin duplicarse. El diagnostico usa por defecto
`exports/market_data.db`, recupera por REST desde el minuto posterior a la
ultima barra guardada y muestra cuantos posibles huecos internos existen. En
activos sin operaciones durante un minuto, la ausencia puede ser legitima; el
sistema nunca inventa una vela para ocultarla.

Cada barra recibida por WebSocket produce un evento `closes_15m` y
`closes_1h`. Solo esos eventos habilitaran la ejecucion automatica del scanner;
las barras abiertas se rechazan expresamente.

El stream se suscribe tanto a `bars` como a `updatedBars`. Las actualizaciones
tardias oficiales de Alpaca reemplazan la misma barra por timestamp antes de
las reconciliaciones posteriores; no se relajan tolerancias ni se inventan
precios para forzar coincidencias.

`live_strategy_service.py` realiza backfill al arrancar, mantiene el WebSocket,
reconstruye el `DataBundle` al cierre de 15 minutos, ejecuta el motor
autoritativo y guarda el reporte en `strategy_alerts`. Una restriccion unica
impide duplicar la alerta si el proveedor repite o corrige la misma vela.

## Cadena de opciones

`option_market_data.py` consume exclusivamente el endpoint de solo lectura
`/v1beta1/options/snapshots/{underlying_symbol}`. La consulta se limita en el
servidor por CALL/PUT, rango de strikes y rango de vencimientos, y pagina hasta
obtener todos los snapshots aplicables.

Fuentes oficiales:

- https://docs.alpaca.markets/us/reference/optionchain
- https://docs.alpaca.markets/us/docs/historical-option-data

El selector evalua bid, ask, spread, tamanos, distancia al strike, vencimiento,
costo y delta. Todos los umbrales proceden de controles explicitos del usuario.
Una cotizacion `indicative` nunca queda `eligible`; solo OPRA puede superar esa
compuerta. No se consulta ni se invoca ningun endpoint de ordenes.

## Enriquecimiento opcional de alertas

`option_opportunity.py` carga una politica JSON estricta. Todos los campos son
obligatorios y no se aceptan nombres desconocidos. El archivo de ejemplo usa
`null` deliberadamente y no activa la seleccion hasta que el operador lo
complete.

Cuando `live_strategy_service.py` recibe `--option-policy`, una alerta con
decision o sesgo tentativo CALL/PUT consulta la cadena y agrega
`option_selection` antes de persistir el reporte. Una alerta neutral registra
`SIN_SESGO` sin hacer una llamada de opciones. Sin ese argumento, el
comportamiento anterior permanece intacto.

## Reconexión y salud

El calendario oficial descargado durante el preflight se conserva en SQLite,
incluidos los cierres tempranos. La vista de alertas combina ese calendario con
el último preflight y el heartbeat del scanner. Solo considera una vela
retrasada durante una sesión abierta; fuera de horario muestra
`LISTO_EN_ESPERA`. Una desconexión explícita permanece `BLOQUEADO` aunque el
mercado esté cerrado.

La pestaña de alertas usa un fragmento Streamlit que se actualiza cada 15
segundos. Las alertas sin primer acuse se cuentan como nuevas y generan un
aviso visual una sola vez por sesión de interfaz. Los acuses `VISTA`,
`ATENDIDA` y `DESCARTADA` se conservan como versiones independientes;
`DESCARTADA` exige una explicación. El refresco no envía mensajes externos ni
ejecuta operaciones.

Para controlar ruido, cada cierre se clasifica de forma determinista:

- `INCIDENTE_DATOS`: frescura o reconciliación no aprobada;
- `SETUP_CONFIRMADO`: al menos una estrategia con criterios confirmados;
- `SETUP_DETECTADO`: existe estrategia detectada todavía incompleta;
- `SIN_SETUP`: escaneo informativo sin estrategia.

Los tres primeros requieren acuse. `SIN_SETUP` se conserva en SQLite, pero no
incrementa pendientes, no genera aviso y se oculta por defecto. Esta taxonomía
solo organiza eventos; no modifica la decisión del motor.

`live_service_runtime.py` supervisa el WebSocket con backoff exponencial entre
1 y 60 segundos. Antes de cada reconexion ejecuta recuperacion REST desde la
ultima barra persistida, por lo que el proceso no supone que la conexion fue
continua.

El estado se guarda en `live_service_health`: conexion actual, ultima conexion,
ultima vela, contador de reconexiones y ultimo error. Streamlit lo presenta en
la pestana **Alertas en vivo**. El estado no contiene claves ni secretos.

## Compuerta de frescura

`live_freshness.py` verifica que la barra este cerrada, que el feed sea IEX o
SIP en vivo, que no exceda tres minutos y que coincida con la ultima barra
persistida. `delayed_sip` se rechaza expresamente como evidencia actual.

El reporte conserva edad, feed, coincidencia con SQLite, posibles huecos de los
ultimos 15 minutos y motivos de rechazo. Solo una frescura `APROBADO` permite
que `data_current_review` sea verdadero; una alerta rechazada puede conservarse
para auditoria, pero no desbloquea la decision.

## Velas cerradas por temporalidad

Al cierre de cada bloque de 15 minutos, el scanner de producción compara sus
15 barras WebSocket persistidas contra barras REST del mismo proveedor y feed.
Compara timestamps, OHLC y volumen con tolerancias explícitas, reintenta hasta
tres veces por el posible retraso de publicación REST y nunca sobrescribe
precios silenciosamente. Un resultado `RECHAZADO` o `NO_DISPONIBLE` rechaza la
frescura efectiva de la alerta y conserva las diferencias en
`market_data_reconciliation`.

La comprobación se persiste primero en `market_reconciliations`, antes de
ejecutar detectores o construir la alerta. Así, un error posterior del
evaluador no elimina la evidencia de integridad. La interfaz muestra el
historial y el monitor degrada el estado durante mercado abierto si la última
reconciliación quedó rechazada o no disponible.

El preflight conserva por separado símbolos objetivo y benchmarks. Durante una
sesión activa, el monitor consulta la reconciliación más reciente de cada
símbolo objetivo; una aprobación posterior de otro activo no puede ocultar un
rechazo. Existe una gracia de 20 minutos desde la apertura para completar el
primer bloque. Después, un símbolo sin reconciliación o con más de 20 minutos
de antigüedad degrada el estado operativo.

`retain_closed_aggregates` impide que una agregacion parcial entre al motor. Un
cierre 15m no cierra automaticamente la vela de Hora ni la Diaria. Hora queda
disponible al completar sus bloques anclados a las 9:30; el ultimo bloque
parcial termina a las 16:00. Diario solo se incorpora al finalizar la sesion.

Cada `DataBundle` Alpaca publica `closed_through` por temporalidad y los
reportes conservan ese dato. Esto permite demostrar exactamente cual fue la
ultima vela confirmada que uso cada detector.

## Calendario oficial

`market_calendar.py` consulta `/v2/calendar` y obtiene apertura y cierre por
fecha, incluidos cierres tempranos. El scanner sincroniza el rango historico y
30 dias futuros antes de empezar; la carga Alpaca de Streamlit usa el mismo
calendario. Si no puede obtenerse, la carga se detiene en vez de afirmar que
una sesion abreviada termina a las 16:00.

## Contexto de benchmarks

`market_context.py` agrega SPY, QQQ, IWM y DIA como referencias configurables.
Cada alerta conserva cierre 15m, cambio porcentual, direccion y si el benchmark
estaba sincronizado con la vela disparadora. La salida permanece
`REQUIERE_REVISION`: coincidencia o divergencia aporta contexto, pero no crea
una entrada ni aprueba panorama automaticamente.

## Noticias recientes

`news_context.py` consulta `/v1beta1/news` por simbolo y las 24 horas previas a
la alerta. Conserva titular, fuente, URL, timestamps y simbolos relacionados,
sin descargar el contenido completo. La salida siempre requiere revision
humana: cero articulos no demuestra que el calendario macro este libre.

## Revision humana de alertas

Cada alerta puede recibir revisiones versionadas de camino libre, noticias y
panorama. `PENDIENTE`, `SI` y `NO` permanecen diferenciados; un rechazo exige
notas. Las revisiones se agregan en `alert_human_reviews` y nunca sobrescriben
el reporte original ni aprueban por si solas la compuerta de riesgo.

`alert_reevaluation.py` reconstruye estrategias e invalidaciones desde la
alerta y aplica una revisión concreta. El resultado se guarda aparte en
`alert_reevaluations`, con identidad única alerta+revisión. Riesgo y gobierno
conservan su estado original, por lo que aprobar panorama no autoriza operar.

Los contratos elegibles requieren seleccion humana explicita y se versionan en
`alert_contract_selections`. La reevaluacion puede aprobar riesgo solo si el
candidato guardado era elegible y su evaluacion de riesgo fue `APROBADO`.
Gobierno operativo permanece independiente y no se crean ordenes.

IEX, SIP y cualquier proveedor futuro se almacenan por separado para impedir
que una serie historica mezcle fuentes incompatibles. Los huecos no se rellenan
con precios artificiales: se vuelven a solicitar al proveedor.

La elección dependerá de costo, disponibilidad de velas intradía, cobertura de
opciones, límites de uso y retraso de datos.
