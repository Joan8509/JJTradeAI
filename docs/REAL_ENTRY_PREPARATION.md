16/11/2026 - Seleccion REAL segun efectivo disponible:
El filtro previo usa efectivo liquidado menos reservas y costes ya registrados,
con evidencia vigente y sin reutilizar fondos de fills recientes. Conserva el
orden de contratos elegibles existente. Si el preview del elegido falla
explicitamente por fondos, puede evaluar una sola alternativa estrictamente
mas barata en el mismo ciclo, eligiendo el Ask menor entre los candidatos
permitidos restantes. Maximo dos previews por llamada; nunca un bucle de envios.
Antes del segundo preview revalida senal, identidad, reloj y elegibilidad; el
reloj de ruptura/primera senal, cantidad, rango, vencimiento, ITM/5 OTM y spread
siguen vigentes. El preview exacto sigue incluyendo cargos y proyecciones:
no se inventa una comision ni se convierte prima asequible en permiso de compra.
Advertencias, rechazos distintos de fondos y errores de transporte cortan,
sin buscar otra opcion para eludirlos. SEV25 permanece bloqueado por decision
del usuario. Guarda resultados acotados de ambos previews en diagnostico del
host cifrado y acumula su duracion. Revision entry_funding_selection_revision=1.
Pruebas, carga y limitaciones de evidencia en CURRENT_CONTEXT y diario16Nov.

# Preparación anticipada de contratos reales

Revisión 3 del 15/11/2026: para la apertura, la preparación de las compañías
ARMED empieza treinta minutos antes de la sesión oficial (9:00 ET para apertura
a9:30). Sustituye el inicio anterior de9:25. Una selección hecha después se
atiende al siguiente turno disponible. No arma la cola ni traslada una cola
consumida a otra sesión: el usuario debe activar la preparación correspondiente.
Conserva renovación desde3min, TTL5min, un trabajo por turno, cesión a precios
urgentes, autenticación y todas las validaciones. Las cotizaciones anticipadas
no autorizan comprar: cada entrada exige datos y señal actuales. Diagnóstico
entry_preparation.revision=3 y lead_minutes=30. Prueba/carga en CURRENT_CONTEXT.

Prioridad de consultas 13/11: el preparador REAL cede el turno si el limitador
de datos está ocupado o todavía hay que esperar para la próxima petición. No
espera dentro del lock ni reserva un turno futuro por delante de los precios de
entrada/salida. Una cesión no es un fallo del proveedor: no publica cooldown ni
penaliza el instrumento quince segundos; el hilo vuelve a intentarlo en sus
turnos habituales. Un HTTP ya iniciado no se cancela ni adelanta otro request
por debajo del intervalo. Retry-After y el segundo mínimo permanecen vigentes.
Solo GET de chains admite esta prioridad local; nunca se añade como parámetro
a Schwab y nunca se utiliza para órdenes o token. SIM conserva su configuración.
Estado del preparador: YIELDED_TO_LIVE_REQUEST; host actualizado publica
entry_background_yield_revision=1. Código probado/carga en CURRENT_CONTEXT.

Ampliación 13/11 por demora SLV: solo en el cliente del host REAL, con calendario
completo vigente, el vencimiento elegido puede refrescarse mediante un único GET
de cotizaciones (subyacente y todos sus contratos). Se usa cuando caben hasta 49
contratos más el subyacente en el límite existente de 50 símbolos. No se recortan
strikes ni se filtran por precios históricos. Vencimientos mayores conservan la
consulta de cadena existente; sin calendario vigente se exige la búsqueda completa.
Un contrato ausente, detenido o inválido se excluye sin recuperar su precio viejo;
un fallo de transporte mantiene cooldown. Los timestamps del proveedor, rangos,
spread, reglas ITM/OTM, fondos, preview y revalidación de señal siguen vigentes.
La caché conserva su plazo existente de cinco segundos, sin ampliación. SIM no
habilita esta ruta. Diagnóstico `entry_quote_batch_revision=1` en host actualizado.
Esto reduce el volumen de consulta donde aplica; el ahorro real debe medirse con
una próxima señal, y no permite atribuir un tiempo futuro a partir del caso SLV.

Actualización del 13/11/2026, autorizada tras el estudio de oportunidades rápidas.
La preparación anterior se limitaba a los cinco minutos previos a apertura y
terminaba veinte segundos antes. Una selección activada durante la sesión o
una autorización renovada después quedaba sin esa preparación anticipada.

La revisión 2 histórica trabajaba desde cinco minutos antes de abrir hasta el cierre de
la sesión de la cola. Solo atiende compañías ARMED de esa cola y sus lados
CALL/PUT. Una cola pausada, reservada por una entrada o ya consumida detiene la
preparación. Consultar la app no arma una cola ni prepara compañías ajenas.

La autorización de datos se comprueba mediante el estado que ya mantiene el
ejecutor. Mientras falta, la preparación espera; al recuperarse vuelve a
atender las compañías pendientes sin rearmarlas. No ejecuta su propio login.

Se realiza como máximo un trabajo de catálogo por turno del hilo independiente
(intervalo existente de dos segundos). Los catálogos faltantes y más antiguos
tienen prioridad. Se intenta renovarlos desde tres minutos de antigüedad para
anticiparse a su límite existente de cinco minutos. Un error de instrumento
tiene espera local de quince segundos para dejar atender a otros; permanecen
las esperas globales y Retry-After del proveedor. El ritmo real de renovación
depende de cantidad de compañías, tiempos de respuesta y límites del proveedor.

Solo se prepara metadata del calendario y cadena completa. Al entrar siguen
vigentes la selección de vencimiento, strikes, rango, spread, fondos, cotización
y preview actuales. El límite del catálogo no hace actuales las cotizaciones.
No se extienden sus timestamps ni los tres segundos de frescura de la señal.
El comportamiento por defecto de preparación usado por simulación se conserva.

Las llamadas HTTP no mantienen ocupado el lock de la caché. El hilo de entrada
no espera al preparador; si no hay catálogo válido conserva su camino normal.
No se añaden umbrales de volumen, medias o expansión, ni se modifican las ventas.

Diagnóstico: `entry_preparation.revision=2`, estado de espera/preparación,
`selected_count` (trabajos compañía/lado) y `ready_count` (catálogos vigentes).
Estos contadores no certifican una cotización apta ni una compra autorizada.

Archivos: `real_entry_preparation.py`, `manual_trade_service.py` y conexión desde
`real_execution_host.py`. Validación: 179 pruebas aprobadas, incluyendo actividad
durante sesión, recuperación de autorización, renovación, precios históricos
rechazados, fallos por compañía, concurrencia, entradas y salidas. Estado cargado
y límites de verificación en CURRENT_CONTEXT y diario del 13/11.
