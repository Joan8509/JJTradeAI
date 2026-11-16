# Revisión del recorrido de entrada del 15 de noviembre

La prioridad autorizada es operar inmediatamente al cumplirse la estrategia,
con objetivo10% elegido y stop20%, conservando primera compra única por cola.
Esta revisión no cambia señales, contratos permitidos, rangos ni porcentajes.

El recorrido actual consta de publicación del detector, aviso local al ejecutor,
lectura conjunta de señales, validación completa, búsqueda/precios del contrato,
preview de Schwab, revalidación, reserva persistente y envío único. Las salidas
y Telegram se procesan en hilos separados. No se espera cierre de vela ni se
añade confirmación por medias/volumen.

Las mejoras anteriores ya anticipan catálogos desde9:00 para las compañías ARMED,
renuevan metadata, priorizan precios frente a preparación, evitan leer compañías
sin señal y refrescan por quotes los vencimientos completos de hasta49contratos.
Un vencimiento mayor conserva la cadena habitual sin recortar oportunidades.
Las respuestas siguen necesitando validación y timestamps del proveedor.

Se encontraron y corrigieron dos costes adicionales:

- El refresco de cada contrato recorría y copiaba todos los vencimientos del
  catálogo. Ahora el validador recibe únicamente la identidad de ese contrato;
  después se reúnen todos los contratos refrescados. Se conservan calendario
  completo, inventario para contar OTM, orden, resultados y timestamps. No se
  omite ninguna validación de identidad/mercado ni se añade una consulta HTTP.
- Los transportes GET, preview y orden llamaban a sleep(0) aun con turno libre.
  Se elimina esa cesión innecesaria al planificador. Toda espera positiva,
  intervalo mínimo, Retry-After, guardas anteriores/posteriores y comportamiento
  de entrega incierta se mantienen. No se habilitan reenvíos automáticos.

Prueba sintética local con49contratos seleccionados y10.000 de otros vencimientos:
mediana anterior218,03ms, actual12,84ms, resultados idénticos. Es una prueba de
procesamiento en un catálogo grande, no una medición de compra real ni94% de
reducción del tiempo total. No se atribuye a sleep(0) una cantidad medida.

Quedan dependencias de recepción del mercado y respuesta/ejecución de Schwab.
No se sustituyen por cotizaciones históricas ni se elimina preview para mejorar
una cifra. Se debe medir la próxima entrada por fases y conservar primer fallo,
tiempo de búsqueda, preview, envío y fill, sin generar compras de prueba.

Opciones de mayor alcance como conexiones HTTP persistentes o streaming de
opciones requieren pruebas propias de reconexión y envíos inciertos; no se
introducen como cambio de transporte sin verificación antes de la apertura.
Esta sesión entrega optimizaciones comprobadas del camino ya operativo.

Validación efectiva, estado de carga y preservación de la cola en CURRENT_CONTEXT
y SESSION_STATE_2026-11-15. Evidencia detallada privada en
exports/trade_review/2026-11-15_processing_cost/.

La revisión integral añadió un índice SQLite parcial de primera salida por
símbolo y hora, limitado a eventos EXIT. La consulta anterior usaba solo hora
y recorría eventos de otras compañías. Se conserva exactamente la consulta,
su primer resultado y el reloj original; no se renueva una señal vencida.
Sobre50.000filas copiadas a memoria y12consultas, mediana20,062ms->0,016ms
con resultados idénticos. Es una medición SQL local, no de ejecución en Schwab.

Índice aplicado a la base actual a21:31ET en transacción9,071s, sin reinicio,
preservando200.000filas, cuenta, cola, journal y PIDREAL. Diez filas ARMED
permanecieron iguales. No se enviaron órdenes ni avisos de prueba. El código
de creación de esquema también conserva el índice en nuevas instalaciones.

Cobertura revisada: publicación y despertar IPC, lectura conjunta y prioridad
de señales nuevas, preparación anticipada, límites de peticiones, refresco de
precios, selección de contratos, preview exacto, revalidación, reservas,
entrega incierta, avisos en hilo independiente y supervisión de salidas.
Se mantienen las dependencias externas y las validaciones de vigencia.

Comprobación21:32ET: monitores actuales sin errores, colector y radar activos,
datosSchwabGET recibidos. La autorización de CUENTAS exige reconexión:
REAUTHORIZATION_REQUIRED, blocker LIVE_ACCOUNT_REFRESH_UNAVAILABLE. Este
resultado sustituye el estado listo observado19:51; no atribuirlo al índice.
Se pidió al usuario renovar JJTradeAI-Cuenta. No rearmar ni modificar cola.
Salud HTTP local200 verificada sin proxy; el comprobador anterior usó el
proxy del entorno y no pudo verificar esa URL, no demuestra caída de UI.
Evidencia adicional en exports/trade_review/2026-11-15_full_entry_audit/.

Validación final de los cambios:172pruebas de entrada, preparación, contrato,
gateway, preview, ciclo real, avisos y cierres pasan en22,621s.7pruebas de los
dosfixtures corregidos pasan6,242s.23decontención SQLite/WAL pasan7,981s tras
actualizar mocks de observe para el argumento references_pending y verificar
el orden persistido de barras sin imponer almacenamiento síncrono a trades.
Estos ajustes de pruebas no modifican la aplicación cargada.

La batería amplia ejecutó2200tests en486,404s (496,4s incluyendo imports):
17fallos y3errores, no resultado global aprobado. Seis incidencias de mocks/
orden síncrono quedaron resueltas en la corrida dirigida de23 mencionada.
Las restantes incluyen fixtures de UI manual con stop10% incompatible con20%
vigente, expectativas antiguas de límite objetivo alBid en vez de mínimo del
objetivo elegido, ensayo sintético de detector y estudio stop sin señal,
y una prueba DPAPI no permitida en sandbox. Deben conciliarse por separado;
el resultado no justifica quitar guardas ni alterar porcentajes aprobados.
No se repitió toda la batería después de las correcciones de fixtures.
Lista y trazas exactas: suite.json y suite_details.txt en evidencia privada.
