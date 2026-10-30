# Reglas estables de JJTrade AI

Confirmadas por el usuario en el mensaje de continuidad de la PC del
15/10/2026. Este contrato fija el comportamiento; el estado operativo y la
evidencia vigente se consultan en [CURRENT_CONTEXT.md](CURRENT_CONTEXT.md).
Una prueba unitaria no demuestra funcionamiento en mercado ni entrega real.

## Estrategia

- Versión `v5_apertura_dentro_bandas_actuales`, velas de 15 minutos,
  Bollinger 20 períodos, desviación 2, `ddof=0`.
- Aclaración expresa del usuario26/10/2026, tras captura y pregunta concreta:
  apertura real de esa misma vela dentro de las **bandas del momento de la
  salida**, calculadas con19cierres anteriores y el precio conocido ahora.
  Apertura fija/oficial; bandas evolucionan intravela, sin usar cierre futuro.
  Sustituye el veto de bandas congeladas al primer instante de v4. Apertura
  desconocida o todavía fuera de las bandas actuales no autoriza señal.
- Ambas bandas se expanden frente a la vela anterior: superior sube e inferior
  baja. Mayor anchura o movimiento de una sola banda no bastan.
- Decisión28/10: comparar5% de forma observacional manteniendo ACTIVO3%.
  La comparación no veta ni demora entradas y no cambia órdenes o avisos.
  [Alcance y límites](ENTRY_BAND_COMPARISON_2026-10-28.md).
- Actualización autorizada26/10/2026: mínimo **3% por cada banda** respecto
  del ancho anterior, inclusive. Tanto el avance de la superior como el
  descenso de la inferior, divididos por el ancho anterior y multiplicados
  por100, deben ser >=3. Sustituye el mínimo1% autorizado22/10;
  no es3% del precio ni del crecimiento total del ancho. Sigue intravela,
  sin esperar cierre. [Detalle](BAND_EXPANSION_FILTER_2026-10-22.md).
- Salida superior: precio sobre banda superior y apertura, punto medio subiendo.
  Salida inferior: precio bajo banda inferior y apertura, punto medio bajando.
- Un cierre anterior fuera no veta una nueva vela con apertura propia dentro.
  No reintroducir ese veto ni tolerancias de apertura. No autoriza una apertura
  que permanezca fuera de las bandas del momento de detección.
- SMA20/40/100/200, Hora/Diario, niveles y memoria son descriptivos. No son
  nuevos filtros, aprobaciones, probabilidades ni umbrales de fuerza.
- Sin datos futuros, barras inventadas, sustitución de períodos ausentes por
  otros antiguos o mezcla de versiones de estrategia. Consultar calendario
  oficial para períodos cerrados, sesión previa y cierre anterior requerido.

## Recepción y avisos

Actualización29/10/2026 autorizada para ejecución simulada:30s desde el primer
EXIT auditado por el detector, no desde que la cola esté preparada; sin evidencia
no se renueva el reloj. Nuevos stops simulados venden al siguiente Bid válido,
aunque la pérdida supere20%; objetivos mantienen su mínimo de ganancia.
Cierre manual, estrategia y órdenes reales deshabilitadas se conservan.
[Políticas, límites y pruebas](EXECUTION_REPAIR_2026-10-29.md).

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


Actualización29/10/2026: usuario autoriza tantas compras SIMULADAS como sean
necesarias para nuevas oportunidades, sin máximo diario elegido. La opción
«Repetir con señales nuevas después de finalizar cada operación» se muestra
activada al preparar NUEVAS autorizaciones. Se guarda permiso explícito con
la fila; no se convierte retrospectivamente una autorización de compra única.
Cada fila sigue siendo una sola solicitud y conserva su claim. Solo tras
finalización local confirmada y conciliación, sin posición ni orden pendiente
en la compañía, se crea una fila sucesora con cantidad/objetivo/rango/tope
idénticos y referencia nueva. Espera una señal NUEVA posterior; no compra por
el aviso consumido ni por señales vistas mientras existía exposición. Sin
rearme tras estado incierto, fuera de sesión, pausa, eliminación o mantenimiento.
No se traslada al siguiente día. Pausar/eliminar cualquier miembro desactiva
su permiso y pausa sucesores armados, conservando solicitudes/operaciones.
La fila anterior queda en historial y se oculta de la cola al crear sucesora.
Esto sustituye la restricción histórica de compra única solo para autorizaciones
que incluyen repetición. No hay refuerzos, ampliación de riesgo por compra,
frescura/ventana renovada para la misma señal ni órdenes reales habilitadas.

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

Actualización28/10/2026 autorizada expresamente: la oportunidad de compra
automática caduca a los **30 segundos**, inclusive, desde el trade de la
primera señal válida del detector (corrección29/10: antes se contaba desde
su observación por la cola). Ese inicio se guarda en SQLite
por identidad de señal; otro trade, retroceso, consulta, plan o reinicio no
renuevan el plazo. Una señal caducada no compra; la fila puede esperar otra
señal nueva sin rearmarse ni repetir una compra consumida. La orden de compra
caduca al menor de10s desde su registro y el fin de esos30s; tampoco se llena
después de ese límite. Compras parciales conservan su posición y plan de
salida; solo se cancela el remanente. No afecta a la referencia manual por
aviso, a las ventas, ni a la detección/notificación de Bollinger. No garantiza
rentabilidad y puede descartar señales válidas que tardan en tener contrato.
Ver [ventana y pruebas](SIGNAL_ENTRY_WINDOW_2026-10-28.md).

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
