# Continuidad de JJTrade AI

Actualizado 27/10/2026 ET. Solicitud vigente: guardar las mejoras en GitHub.
Instrucciones actuales del usuario prevalecen. Leer AGENTS.md y
docs/GITHUB_CHECKPOINT_2026-10-27.md; consultar Git antes de modificar.
Los diarios operativos locales docs/SESSION_STATE_*.md y la continuidad extensa
conservada en exports/trade_review/2026-10-27_github_checkpoint/ no se publican.

## Estrategia y controles

Solo SIMULACIÓN LOCAL con cotizaciones Schwab; no es paperMoney. Perfil
MARKET_DATA_ONLY, órdenes reales OFF. No iniciar otro colector por clonar Git.
Bollinger15m20/2ddof0:19cierres previos+trade conocido, sin cierre futuro.
Apertura real de misma vela dentro de bandas DEL MOMENTO DE SALIDA, versión
v5_apertura_dentro_bandas_actuales. Ambas bandas expanden>=3% CADA UNA sobre
ancho previo; direcciones de precio/apertura/media conservadas. Ver
STRATEGY_OPERATING_CONTRACT.md y DYNAMIC_OPENING_BANDS_2026-10-26.md.
IEX/REGULAR, trade3s, opciones/spot30s, correcciones/cuarentena/calendario.
Extendida pendiente de cobertura; gráficos externos no son equivalentes por defecto.
CALLsuperior/PUTinferior; ITM o primeros5strikesOTM inclusive, ATMexcluido.
Ask en rango aprobado, spread<=0.08. Vencimiento listado más próximo;
después14ET salta el mismo día. AAPLAsk0.45–0.95, otras52referencias iguales;
19símbolos en radar, SPCX sin rango aprobado. Ver config/option_price_ranges.csv.
Nuevos planes stop20%, objetivos10/20/35/100/manual; planes anteriores inmutables.

## Entrada, salida y notificaciones

Fila explícita compañía/cantidad/objetivo/sesión; una compra por autorización.
Claim durable antes de dispatch; incertidumbre nunca se reintenta. Entrada
automática al techo de rango autorizado, fill al Ask posterior con tamaño,
caducidad10s del remanente. Pausa/consentimiento/revalidación no se omiten.
Señales nuevas tienen prioridad; consultas REST fuera de locks compartidos,
calendarios preparados, caché subsegundo solo con tiempos originales válidos.
Informes/recibos MiniApp separados de compra; registro y monitor no esperan UI.
Ventas pendientes tienen prioridad/GETnuevo, sin consultas redundantes de posición.
Salida exige quote posterior, tamaño, Bid>=límite y sesión/conciliación válidos.
La venta conserva límite del Bid que disparó; otro Bid>=objetivo pero inferior
al límite puede esperar. Cambiar esa política no está aplicado; el stop tampoco
garantiza pérdida exacta. Journal privado asíncrono y acotado de no-match/latencia.
Ejecución, seguimiento y Telegram independientes. Avisos de estrategia sin
botones; avisos de compra/cierre solo con fills confirmados y enlace dashboard.
Preservar154dedup originales, incluidos16inciertos, aliases e identidades;
nunca reenviar históricos ni rearmar automáticamente filas consumidas.

## Interfaz y conexión

Tres pestañas: Estrategia en Vivo, Operar Automáticamente, Mis operaciones.
Edición por lotes, objetivos/cantidades comunes o individuales, borrador y
consentimiento; guardado atómico tras GETSchwab nuevo. Indicador de conexión
en fondo, caducidad basada en checked_at; editar no pausa entradas. Sin
refresco automático al editar; seguimiento visual opcional. Fondo estático,
ancho móvil y referencias descriptivas de resultados, sin aprendizaje decisor.
Tokens DPAPIAdministrator, refresh porAPI; pestaña de login web no acelera.
Nueva autorización interactiva en navegadorVPS por callback127.0.0.1.
Watchdog preventivo implementado; tarea persistente no acreditada, comprobar
antes de declararla activa. No automatizar contraseñas/MFA ni prometer renovación perpetua.

## Validación, estado y siguientes pasos

Las revisiones de entradas/salidas/UI tienen pruebas aisladas y recibos locales.
CheckpointGit solicitado:355testsOK158.411s; paquete revisado sin claves,
cuentas o bases privadas. Publicación pendiente de confirmar contra SHAremoto.
Última carga comprobada27Oct19:09ET: background_entry_presentation_v1,
fresh_pending_exit_quotes_v1, nonblocking_market_cache_v1 y
network_outside_workflow_lock_v1. HTTP200/monitorREADY y autenticaciónTelegram
comprobados19:09:40ET; esto no demuestra estado presente o recepción futura.
Rangos actualizados19:35ET por lectura directaCSV, sin reinicio.
Guardar en Git no reinicia servicios ni ejecuta órdenes o avisos.
Falta medir tiempos con mercado abierto tras últimas cargas; no prometer
ganancias ni atribuir toda demora histórica a un solo fallo. No hay serie
completa de cotizaciones de opciones de los casos anteriores. Mantener
los controles cuando falten datos/contratos o conexión. Pruebas de recuperación,
reinicioWindows/RDP y cobertura extendida pendientes; no reiniciar por este guardado.
Credenciales, cuentas, bases, respaldos, infraestructura y operaciones privadas
se conservan locales; los datos y herramientas privadas no se suben a GitHub.
