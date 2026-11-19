# Reglas estables de JJTrade AI

Refuerzo17/11/2026 de salida STOP20%: limpieza atomica de ventas propias
PREPARED vencidas/sin enviar, prioridad del stop sobre objetivo no enviado y
cancelacion de objetivo aceptado tras STOP persistido aun sin nueva quote.
Venta nueva requiere Bid valido y cantidad propia libre/confirmada. Esperas
prolongadas o inciertas del stop generan revision/aviso, sin reenviar POST
inciertos ni liberar reservas de envios posibles. No cambia umbral20%, objetivo,
V9 de entrada ni primera entrada. Sigue STOP local, no nativo. Detalle
REAL_STOP_REINFORCEMENT.md; carga efectiva en CURRENT_CONTEXT.

Actualizacion17/11/2026, autorizacion expresa "activala, me gusta esa mejora":
V9 cuenta el plazo maximo30s desde la PRIMERA estrategia COMPLETA por
feed/alcance/simbolo/vela/lado. Intenta entrar inmediatamente; no espera30s.
Sustituye el vencimiento desde primer cruce autorizado06Nov, conservado abajo
como historia. El primer cruce queda como evidencia, no como veto temporal.
El reloj completo se persiste junto con la senal antes del despertarIPC y no
se renueva por retraccion, pausa o reconexion. Sin evidencia no se inventa.
Se conservan apertura dentro de bandas previas/iniciales/actuales,3% por cada
banda, precio fuera/direccion/media, frescura3s, contratos, fondos, preview,
dedup y primera entrada; objetivos y stop20% sin cambios. Version
v9_primera_estrategia_completa_30s. Carga efectiva solo en CURRENT_CONTEXT;
detalle STRATEGY_COMPLETE_CLOCK_PREPARED_2026-11-17.md.

Actualizacion17/11/2026: el usuario confirma que la apertura debe quedar dentro
de las bandas de la vela ANTERIOR, antes de recalcularlas con la vela nueva.
Version v8_apertura_dentro_bandas_previas. Abrir fuera invalida toda esa vela,
aunque despues reentre y salga o se ensanchen las bandas. Se conservan tambien
los controles de bandas iniciales/actuales, 3% por cada banda, direccion/media,
precio fuera, relojes originales30s y frescura3s. Sin espera de cierre ni red
adicional. Sustituye la suficiencia de referencia inicial06/11 descrita abajo.
No renueva eventos, avisos, identidad REAL v7 ni armado. Detalle en
STRATEGY_PREVIOUS_OPENING_2026-11-17.md; carga efectiva en CURRENT_CONTEXT.

13/11/2026: preparación REAL de catálogos ampliada a la sesión de la cola,
incluida recuperación de autorización de datos. Solo compañías ARMED, hilo
separado y metadata; conserva cotizaciones, preview, fondos y frescura originales.
No cambia estrategia ni salidas. Detalle: REAL_ENTRY_PREPARATION.md. Estado de
carga y comprobaciones en CURRENT_CONTEXT.

Actualizacion06/11/2026, peticion de corregir avisos tardios SPCX/META/AAPL/TSLA:
version v7_ruptura_temprana_30s limita nuevas oportunidades a30segundos desde la
PRIMERA salida observada por cada lado en esa vela, aunque todavia no cumpla3%.
Si el3% llega minutos despues, no publicar señal ni autorizar compra nueva.
Es un endurecimiento del inicio del reloj respecto a esperar la primera señal
con todas las condiciones; no describirlo como regla anterior ya implantada.
No esperar30segundos: una ruptura valida puede operar inmediatamente. Primer
instante no se renueva por retraccion, actualizacion de referencias, pausa o
reconexion. Persistir porfeed/alcance/simbolo/vela/lado, claves previas y dedup
intactas. Mantener tambien la caducidad de primera señal, frescura3s, apertura
inicial dentro, expansion3%, objetivos/stop20% y monitores de salidas. Estado de
carga en CURRENT_CONTEXT; hasta validarla no afirmar activo ni todosloscasos
resueltos. La evidenciaTSLA reciente no demuestra fallo de regla matematica.

Actualizacion06/11/2026: usuario confirma "Si, descartar esa vela" ante la pregunta
de si debe excluirse una vela que YA empieza fuera de Bollinger. Version nueva
v6_apertura_dentro_bandas_iniciales: apertura oficial dentro de bandas calculadas
con19cierres anteriores y esa apertura; una ampliacion posterior no la habilita.
Sustituye la interpretacion dinamica26/10 conservada abajo como historia. Mantiene
3% por cada banda, precio fuera/direccion/media, apertura tambien dentro de bandas
actuales, sin veto del cierre previo ni espera de cierre. Estado de carga efectiva
en CURRENT_CONTEXT. Detalle STRATEGY_ORIGIN_REVIEW_2026-11-06.md.

Actualización05/11/2026, recuperación de salidas: un rechazo sin fills no debe
anular silenciosamente el stop. Solo se autoriza una nueva venta acotada tras
verificar posiciones y órdenes actuales de Schwab, cantidad propia exacta y
ausencia de salida activa. Reserva y prueba quedan vinculadas; nunca repetir
un envío incierto ni crear un bucle de rechazos. Stop20% persistente y avisos
de fallos de salida separados. Detalle REAL_EXIT_RECOVERY_2026-11-05.md; carga
efectiva y estado de cola en CURRENT_CONTEXT. No añade STOP/OCO nativo.

Actualización05/11/2026: regla general REAL para todas las compañías. La compra
válida tiene prioridad y no espera Telegram. El aviso de compra confirmada se
emite después de verificar los fills de Schwab, en su hilo independiente. La
venta por ganancia conserva el porcentaje de esa fila al activar la preparación,
calculado sobre el costo medio efectivamente ejecutado; no sustituirlo por10%
fijo ni por un objetivo de otra compañía. Tras compra final y preview exacto se
coloca la LIMIT DAY en Schwab, redondeada hacia arriba cuando corresponda. Las
ediciones de preparaciones posteriores no cambian posiciones ya abiertas.
Se conserva stop20% y pausa/exclusión después de primera entrada. Una selección
MANUAL explícita conserva su significado. Recuperación de acuses y estado de
carga: REAL_ACK_RECOVERY_2026-11-05.md y CURRENT_CONTEXT.

Actualización04/11/2026, controles de la cola REAL: el usuario autoriza que
«Activar preparación» guarde y arme las compañías seleccionadas en una sola
acción explícita. Cola real conserva quitar una pendiente, Pausar/Activar la
misma cola y eliminar todas las pendientes sin claim/solicitud iniciada. Reanudar
no renueva señales ni reinicia primera entrada/claims; no revive excluidas,
retiradas, completadas o revisiones, ni pasa una cola vencida a otro día. Limpiar
espera no cancela órdenes ni vende posiciones; monitores de salida continúan.
Visitar páginas/consultar cuenta no arma. Refresco local de interfaz no consulta
broker ni activa operaciones. Ver [controles](REAL_QUEUE_CONTROLS_2026-11-04.md).

Actualización03/11/2026, cierre manual externo: el usuario autoriza detectar y
conciliar ventas desde thinkorswim/Schwab del contrato exacto comprado por la
app en la cuenta seleccionada. Pausar nuevas compras, conservar exclusiones y
primera entrada, retirar solo órdenes propias y confirmar estados terminales
antes de atribuir ejecuciones. SINGLE MARKET/LIMIT con fills completos; una
venta parcial conserva gestión del remanente y la cola pausada. Evidencia
incierta/compleja exige revisión; nunca adoptar compras externas, inferir un
cierre de posiciones omitidas, duplicar ventas ni rearmar por haber cerrado.
Sustituye confirmación individual previa cuando la evidencia es verificable.
Estado de carga en CURRENT_CONTEXT; detalle en
[cierres manuales externos](REAL_EXTERNAL_MANUAL_CLOSES_2026-11-03.md).

Confirmadas por el usuario en el mensaje de continuidad de la PC del
15/10/2026. Este contrato fija el comportamiento; el estado operativo y la
evidencia vigente se consultan en [CURRENT_CONTEXT.md](CURRENT_CONTEXT.md).
Una prueba unitaria no demuestra funcionamiento en mercado ni entrega real.

## Estrategia

- Actualización autorizada 02/11/2026 tras revisar QQQ: mínimo vigente
  **3% por cada banda**, inclusive, respecto del ancho anterior. Sustituye
  el mínimo de 5% autorizado el 30/10, que se conserva abajo como historia.
  No cambia Bollinger 20/2, apertura dentro, dirección ni ventana de entrada.
  Cambiar este umbral no rearma la cola REAL. El armado o la pausa vigentes
  y la carga efectiva se comprueban en CURRENT_CONTEXT y en el estado actual.
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
- Actualización autorizada30/10/2026 tras revisar entrada marginal: mínimo
  **5% por cada banda**, inclusive, respecto del ancho anterior. Sustituye
  el3% autorizado26/10 y la decisión28/10 de mantener5% solo observacional.
  Es la nueva regla autorizada para señales/entradas nuevas; su activación
  efectiva depende de cargarla sin interrumpir posiciones existentes. Consultar
  CURRENT_CONTEXT y no deducir carga del valor en disco. No altera stops,
  objetivos, cierres ni operaciones ya registradas. No espera cierre de vela.
  La comparación histórica3%vs5% se conserva separada de la auditoría5% activa.
- Referencia histórica26/10/2026: mínimo **3% por cada banda** respecto
  del ancho anterior, inclusive. Tanto el avance de la superior como el
  descenso de la inferior, divididos por el ancho anterior y multiplicados
  por100, debían ser >=3; el nuevo mínimo autorizado30/10 es >=5.
  No es5% del precio ni del crecimiento total del ancho. Sigue intravela,
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

Actualización03/11/2026 para REAL: confirmaciones de compra y venta por Telegram
basadas en ejecuciones auténticas de Schwab, separadas del aviso de estrategia.
Diario DPAPI y emisor independiente: no retrasa la entrada ni el monitor de
salida, no reenvía entregas aceptadas o inciertas. Rechazo explícito429 espera
Retry-After. No reemitir operaciones históricas al instalar ni resetear el corte
al reiniciar. El objetivo elegido se activa con el Bid del contrato respecto
del costo medio ejecutado; stop20% conservado. Ver
[implementación y límites](REAL_TRADE_NOTICES_AND_FAST_EXITS_2026-11-03.md).

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

Actualización03/11/2026: el usuario autoriza colocar el objetivo de ganancia
REAL como SELL_TO_CLOSE LIMIT DAY en Schwab tras confirmar la compra y su
costo/cantidad finales. Requiere preview auténtico del precio exacto, reserva
de cantidad, conciliación persistente y aviso de WORKING distinto de fill.
Stop20% sigue en la VPS: cancelar y confirmar la ganancia antes de reemplazar,
sin duplicar ventas ni repetir envíos inciertos. Compras pausadas no se rearman.
No cambia la simulación ni añade STOP nativo/OCO. Ver
[objetivo colocado en broker](REAL_BROKER_PROFIT_LIMIT_2026-11-03.md).

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
- Desarrollo de conexión y simulación Schwab autorizado el16/10/2026.
  Actualización30/10/2026: el usuario autoriza avanzar en la activación real,
  con cantidades y objetivos elegidos y parámetros iguales a simulación.
  Sustituye la restricción anterior de autorización solo preparatoria.
  Actualizacion01/11: integracion del ejecutor real y armado por cuenta/sesion,
  con cantidades/objetivos elegidos y opcion explicita de repeticion. El estado
  efectivo de habilitacion se consulta en CURRENT_CONTEXT; no pedir de nuevo
  permiso generico ni confundir seleccion de vista con armar ordenes.
  Antes de habilitarlo verificar cuenta, fondos/costos, contratos, despacho,
  conciliación y salidas. Estado efectivo en CURRENT_CONTEXT, sin órdenes reales
  en ensayos sintéticos ni avisos históricos. Consola de recuperación y prueba
  de reinicio quedan pendientes operativos y no bloquean el desarrollo.

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


Actualizacion01/11/2026 posterior a integracion REAL: radar de varias companias,
una sola entrada total por cola armada. La solicitud inicial reserva el cupo
antesHTTP; primer fill incluso parcial excluye las demas y no repite al cerrar.
Solo rechazo/cancelacion terminal sin fills o prueba de ningun envio permite
seguir buscando; incertidumbre conserva reserva. Nueva cola solo por accion
explicita, no rollover automatico. Simulacion conserva sus reglas anteriores.

Actualizacion09/11/2026: lectura SMA de direccion y recorrido incorporada a
REAL/Estadoestrategia y tarjetasSIM. Mismas20/40/100/200HoraDiario ymetodologia
previa; fecha/preciooriginal yfaltantes visibles. Resumen de orden/pendiente,
conflictos y siguientes medias/roles/distancias es descriptivo. No convierte
medias en aprobacion/veto, prediccion de precio o targetautomatico; conserva
entrada independiente, reglaBollinger, objetivosseleccionados ystop20%. Noesperar
calculo de medias para enviar compra o aviso. Detalle BOLLINGER_MA_CONTEXT.md.

## Indicador paralelo de fuerza - 11/11/2026

Se incorpora observacion descriptiva de velocidad/aceleracion, continuidad,
expansion y volumen relativo. Las clasificaciones son experimentales, con
faltantes explicitos; no son requisito de entrada ni mueven objetivo/stop.
Observador propio y archivo independiente; sin llamadas al broker o Telegram
ni escrituras en la base de mercado. REAL y SIM muestran lecturas originales.
Detalle: [fuerza observada](MOVEMENT_STRENGTH_2026-11-11.md). Estado comprobado,
limitaciones y despliegue en CURRENT_CONTEXT, no inferir operatividad de esta nota.

Aviso actualizado 11/11/2026: el mismo mensaje añade ancho actual de Bollinger
y ritmo observado, sin filtros, espera o consultas adicionales. No confundir
ancho porcentual actual con expansión del 3% de cada borde. Datos insuficientes
se indican explícitamente. [Definiciones](BOLLINGER_NOTICE_BANDWIDTH.md).
