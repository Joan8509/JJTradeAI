# Reglas estables de JJTrade AI

Confirmadas por el usuario en el mensaje de continuidad de la PC del
15/10/2026. Este contrato fija el comportamiento; el estado operativo y la
evidencia vigente se consultan en [CURRENT_CONTEXT.md](CURRENT_CONTEXT.md).
Una prueba unitaria no demuestra funcionamiento en mercado ni entrega real.

## Estrategia

- Versión `v4_apertura_dentro_sin_veto_previo`, velas de 15 minutos,
  Bollinger 20 períodos, desviación 2, `ddof=0`.
- Apertura propia dentro de las bandas recalculadas con los 19 cierres
  anteriores y esa apertura. Apertura exterior o desconocida no autoriza señal.
- Ambas bandas se expanden frente a la vela anterior: superior sube e inferior
  baja. Mayor anchura o movimiento de una sola banda no bastan.
- Actualización autorizada22/10/2026: mínimo **1% por cada banda** respecto
  del ancho anterior, inclusive. Tanto el avance de la superior como el
  descenso de la inferior, divididos por el ancho anterior y multiplicados
  por100, deben ser >=1. Sustituye cualquier apertura positiva sin mínimo;
  no es1% del precio ni del crecimiento total del ancho. Sigue intravela,
  sin esperar cierre. [Detalle](BAND_EXPANSION_FILTER_2026-10-22.md).
- Salida superior: precio sobre banda superior y apertura, punto medio subiendo.
  Salida inferior: precio bajo banda inferior y apertura, punto medio bajando.
- Un cierre anterior fuera no veta una nueva vela con apertura propia dentro.
  No reintroducir ese veto, tolerancias de apertura ni entradas exteriores.
- SMA20/40/100/200, Hora/Diario, niveles y memoria son descriptivos. No son
  nuevos filtros, aprobaciones, probabilidades ni umbrales de fuerza.
- Sin datos futuros, barras inventadas, sustitución de períodos ausentes por
  otros antiguos o mezcla de versiones de estrategia. Consultar calendario
  oficial para períodos cerrados, sesión previa y cierre anterior requerido.

## Recepción y avisos

Actualización autorizada20/10/2026: preparar referencias con premarket y
after-hours para el gráfico TC2000 del usuario, manteniendo avisos/operaciones
en sesión regular. Implementación extendida preparada; activación supeditada
a cobertura real y comparación, sin inventar ni sustituir períodos. REGULAR
sigue activa por falta de datos extendidos. No cambia la fórmula ni las reglas
anteriores. [Estado y pruebas](EXTENDED_REFERENCE_ALIGNMENT_2026-10-20.md).

- Detección intraminuto por trades, una conexión de mercado compartida,
  recepción separada del análisis pesado. Mantener IEX; no cambiar feed para
  ocultar ausencia de datos. IEX no representa todo el mercado consolidado.
- Mantener condiciones de trade, orden temporal, exclusión de duplicados,
  reconexión y apertura oficial. Tras reconexión a mitad de vela no tomar el
  primer precio observado como apertura. La barra del primer minuto oficial
  confirma la apertura; un minuto posterior no la sustituye.
- Máximo de tres segundos al recibir/procesar; rechazar tiempos futuros.
  Correcciones y cancelaciones ponen la vela en cuarentena y quedan auditadas.
- Antes de enviar, revisar salida vigente, precio y conexión recientes. Un
  minuto antiguo no resucita una salida retraída con el stream activo.
- Deduplicación persistente por chat/proveedor/feed/símbolo/vela/lado, UTC
  canónico y alias históricos ET/UTC, entre reinicios y fuentes trade/barra.
  Conservar primer evento y auditoría. Un intento incierto o en curso también
  ocupa su clave: nunca reintentarlo automáticamente.
- Conservar los 154 registros originales: 138 ENVIADO y 16
  ENVIO_NO_CONFIRMADO. No borrar ni sobrescribirlos para habilitar avisos.
  Recuperación/backfill solo inserta datos oficiales faltantes, sin evaluar
  avisos históricos. Futuras señales se evalúan con datos actuales.
- Telegram conserva formato de cuatro líneas, último resultado
  y errores visibles. Autenticación, aceptación del servidor y lectura del
  teléfono son comprobaciones diferentes.
- Actualizacion21/10: aviso de estrategia SIN botones. Compra automatica
  simulada confirmada tiene aviso independiente con boton al dashboard; cierre
  conserva resultado. No cambia deteccion/dedup ni habilita ordenes reales.

## Operación y conservación

Actualización22/10/2026 posterior al spread0.08: usuario autoriza contratos ITM
y también los primeros **cinco strikes OTM distintos**, incluyendo el quinto,
del vencimiento elegido: CALL por encima del spot, PUT por debajo. Se cuentan
los strikes del mapa original del proveedor antes de filtrar precios/liquidez;
el sexto no se convierte en quinto por falta de cotizaciones aptas anteriores.
No equivale a cinco dólares. ATM exacto no se incorpora en esta autorización.
Rangos de Ask, spread máximo0.08, datos vigentes y demás controles permanecen.
La compra final revalida la posición respecto del spot; sin inventario verificado
no se autoriza OTM. Órdenes reales continúan deshabilitadas.


Actualización22/10/2026: spread máximo de entrada Ask menos Bid de **.08
inclusive**, autorizado por el usuario; sustituye el límite anterior de .05
en selección manual y automática. Rangos de Ask, ITM y demás controles siguen
vigentes. No cambia incrementos mínimos de cotización ni reglas de salida.


Actualización21/10/2026: el usuario autoriza una cola de entradas AUTOMÁTICAS
solo en SIMULACIÓN LOCAL. Cada compañía requiere sesión oficial, cantidad y
objetivo elegidos y armado explícito. Una solicitud por fila; caduca al cierre,
sin rearmado diario ni replay tras reinicio. Solo una señal nueva VIGENTE dispara
CALL/PUT, sin la excepción de referencia manual durante toda la sesión. Conserva
IEX3s, Schwab30s, ITM actual más cercano al spot, rango Ask/spread0.08, vencimiento,
stop20% para nuevas operaciones (actualización23/10), cierre manual, conciliación y deduplicación. El precio autorizado es el
Ask actual dentro del rango/tope de primas mostrado, cantidad x100 xAsk máximo;
las compras manuales conservan consentimiento exacto de precio. Pausar la cola
no cierra posiciones ni anula solicitudes ya registradas. Reales OFF. Ver
[cola y pruebas](AUTOMATIC_ENTRY_QUEUE_2026-10-21.md).

Actualización23/10/2026: entrada automática con límite máximo al techo del
rango de primas ya autorizado, sin superar cantidad ni costo máximo de la fila.
Fill únicamente al Ask real de una quote posterior a la orden; spread y
ITM/OTM5 se comprueban de nuevo. Caduca remanente sin llenar a los10s inclusive,
con cancelación local confirmada/conciliación, sin rearme ni repetir claims.
Registrar solicitud despierta monitor sin esperar Telegram. Nuevas operaciones
stop20%, las ya ejecutadas conservan el plan original. Manual conserva su Ask
exactamente confirmado. [Detalle](BOUNDED_ENTRY_STOP20_2026-10-23.md).

Actualización21/10/2026 por petición del usuario: en el ENSAYO MANUAL, un aviso
ENVIADO conserva su referencia durante su misma sesión oficial, aunque cambie
la vela o haya un retroceso. La fuente original sigue debiendo pertenecer a su
vela y no se modifica su clave ni dirección. Se preselecciona el ITM apto más
cercano al spot; la preparación queda conservada. Una cotización guardada es
solo visual: comprar exige precios actuales, ITM actual, Ask/rango y spread.
Esta decisión sustituye la caducidad por cambio de vela descrita a continuación;
la detección y los avisos no cambian. Solo ManualPracticePolicy, reales OFF.
[Detalle vigente](MINIAPP_RETAINED_ENTRY_2026-10-21.md).

Regla histórica del usuario19/10/2026, sustituida solo en su vigencia de vela:
un aviso ENVIADO, verificado del propietario/proveedor/feed/versión/vela/lado,
es la referencia de entrada durante su vela original de15min. Una retracción o
que el detector ya no marque EXIT no cancelan por sí solos esa compra manual.
No se espera otra salida para confirmar. La detección v4 y su frescura IEX3s
no cambian; no se fabrican snapshots EXIT. La entrada por aviso usa cotizaciones
actuales Schwab del subyacente y opciones (máximo30s), con ITM, Ask/rango,
spread0,08, vencimiento, cantidad/objetivo explícitos, monitor y deduplicación.
Permanece solo ManualPracticePolicy; la automatización genérica exige su señal
vigente y las órdenes reales están deshabilitadas. La sesión Telegram HMAC del
aviso usa el mismo máximo8h de la consulta, sin sustituir la vigencia de vela
ni de precios. Compras genéricas conservan120s. Stop20% para nuevas operaciones, objetivos y cierre
manual se aplican después del fill, independientemente de la señal de entrada.
Esta instrucción sustituye los documentos que exigían recuperar EXIT antes de
comprar manualmente desde ese aviso. [Detalle](MANUAL_ALERT_ENTRY_2026-10-19.md).

- Configuración privada DPAPI bajo Administrator; secretos solo por consola
  local oculta. Nunca texto, argumentos, registros, manifiestos, parches o Git.
- PC sin escritores durante operación VPS. Verificar procesos, heartbeat,
  suscripción, frescura por símbolo y persistencia; tarea habilitada o PID vivo
  no bastan. Evitar una segunda conexión simultánea al endpoint de mercado.
- Radar solo tras acreditar datos aptos y recepción estable. Autenticación
  Telegram sin mensajes puede avanzar aunque falte historia.
- Recuperaciones espaciadas, límites del proveedor y Retry-After respetados.
  Consultas SQLite activas cortas e indexadas: DELETE puede bloquear escritores
  aun con lectores readonly. Integridad y escaneos completos sobre copias.
- Conservar código/pruebas, diferencias locales, SHA-256 y backups SQLite
  verificables antes de cambiar lógica. No reemplazar avances por Git antiguo.
  Si una corrección conocida falta, pedir su paquete identificando el archivo.
- Probar desconexión RDP y reinicio de Windows de forma coordinada, con respaldo
  y recuperación preparados. Sesión 0/Password demuestra identidad de servicio,
  pero no sustituye una prueba real de desconexión o reinicio.
- Desarrollo de conexión y simulación Schwab autorizado el16/10/2026; órdenes
  reales continúan sin autorización de activación. Gate `orders_enabled=false`;
  no avisos históricos ni órdenes reales en ensayos. Consola de recuperación y
  prueba de reinicio quedan pendientes operativos y no bloquean el desarrollo.

## Evidencia de código y regresiones

| Protección | Código | Regresiones |
|---|---|---|
| Apertura, ambas bandas, dirección, cierre previo fuera | `bollinger_phone_worker.py:detect_values`, `bands_at_open` | `test_bollinger_phone_worker.py`, `test_bollinger_tick_stream.py` |
| Reconexión, condiciones, 3s, futuro, cuarentena | `bollinger_tick_stream.py:TickGeometry` | `test_bollinger_tick_stream.py`, `test_bollinger_contract.py` |
| Períodos oficiales, recuperación sin sustitución | `TickGeometry._history`, `_minute_reference_ready` | `test_bollinger_tick_stream.py`, `test_bollinger_contract.py` |
| Retracción y revisión al enviar | `bollinger_phone_worker.py:tick` | `test_bollinger_tick_stream.py`, `test_bollinger_contract.py` |
| Alias, dedup, primer evento e inciertos | `canonical_candle`, `candle_keys`, `claim_notice` | `test_bollinger_phone_worker.py`, `test_bollinger_tick_stream.py`, `test_bollinger_contract.py` |
| Contexto descriptivo y disponibilidad temporal | `bollinger_ma_context.py`, `bollinger_price_levels.py`, `bollinger_pattern_memory.py` | Pruebas homónimas, `test_bollinger_strategy_study.py` |

Documentos de detalle: [intraminuto](BOLLINGER_INTRAMINUTE.md),
[recuperación de avisos](BOLLINGER_NOTICE_RECOVERY.md),
[salud](RADAR_HEALTH.md), [SMA](BOLLINGER_MA_CONTEXT.md),
[niveles](BOLLINGER_PRICE_LEVELS.md), [recuperación VPS](VPS_RECOVERY_2026-10-15.md)
y [configuración privada](VPS_PRIVATE_TASKS.md). Sus estados históricos y cifras
de pruebas no sustituyen comprobaciones actuales; los textos que mencionan v3
en SMA/niveles no autorizan volver de v4 a una regla anterior.
