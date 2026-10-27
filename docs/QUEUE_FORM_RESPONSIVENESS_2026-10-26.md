# Formulario de cola: conexión no bloqueante

26/10/2026 20:31 ET. Usuario sigue observando carga lenta y cursor prohibido
en Poner seleccionadas en cola tras completar varias compañías.

La corrección del fondo no cubría la consulta síncrona de Schwab. Se
comprobó en código que el indicador de conexión se solicitaba antes de
dibujar el formulario y su vigencia decidía si el botón estaba deshabilitado.
También se reproducen datos comunes elegidos sin aplicar: las filas aún
incompletas deshabilitan el botón. No hay evidencia suficiente para atribuir
el caso exacto del teléfono a una sola de esas dos condiciones.

Cambios:

- `schwab_queue_readiness.BackgroundConnectionProbe`: una sola consulta de
  lectura en vuelo, realizada en un hilo independiente. Poll no espera al
  proveedor; solo almacena recibo saneado. Intervalo 30 segundos después de
  completar/recordar resultado; errores sin texto privado. Un resultado viejo
  que termine tarde no sustituye la comprobación nueva del envío.
- `automatic_entry_panel`: indicador en fragmento independiente de 2 segundos.
  Editar compañías no espera la red. El botón depende de datos completos,
  no del recibo visual. **Antes de cualquier guardado** sigue siendo obligatoria
  una consulta autenticada nueva, recibo reciente, autorización explícita,
  calendario oficial, baselines y transacción de lote todo-o-nada.
- Se explica junto al botón cuándo falta aplicar valores comunes, completar
  filas o marcar consentimiento. No se aplican valores ni se autoriza por
  el usuario automáticamente. Rango no aprobado sigue bloqueado.

Medición local de solo lectura: calendario24,46ms, rangos25,60ms, estados de
las18 compañías aproximadamente105ms en total; sin conflictos para próxima
sesión en la instantánea. No medir estas cifras como navegación del iPhone.
La duración real de Schwab no se cronometró en este bloque. Lectura de memoria
del sistema por CIM denegada en sandbox; no se concluye falta de RAM.

35 pruebas OK en tres tandas:29 en17,006s,5 en2,957s y1 en0,449s.
Incluyen proveedor pendiente sin bloqueo ni segunda consulta en vuelo,
caducidad/errores/respuesta vieja, formulario de todas las compañías,
guardado de lote real en SQLite temporal sin órdenes, autorización perdida,
valores aún no aplicados, edición/navegación y consentimiento.
py_compile y diffcheck OK.

Recarga solo interfaz20:29:48 ET, health200 y mismos procesos de mercado.
No cambios de detector, QueueRunner, QueueNotifier, estrategia, tolerancias,
stop20, DB activa/dedup, Telegram ni órdenes realesOFF. Prueba móvil posterior
en curso al crear este documento; no declarar latencia final ni caso del
usuario resuelto visualmente sin recibo. Sin commit/push.

Evidencia privada: `exports/trade_review/2026-10-26_queue_responsiveness/`.
Siguiente paso: confirmar selección móvil y que el usuario pueda guardar su
propia cola; no armar la cola activa durante las pruebas del agente.

Actualización20:44 ET: 36 pruebas distintas tras añadir el caso de volver
a la pestaña con futuro terminado hace40 segundos. La caché ahora calcula
su vencimiento desde checked_at, no desde la recogida tardía del futuro;
recibo antiguo dispara actualización inmediata. Un CONNECTED caducado se
muestra como comprobación en curso, no como fallo del proveedor. Se añaden
solo códigos de error de enumeración cerrada, sin exception text.

Schwab comprobado bajoAdministrator: GETquotes principal634ms y en hilo
1747ms OK. Mediciones de CPU:88% puntual, memoria libre1561/8192MB; muestra
posterior2s no acredita consumo sostenido parecido. No se detuvo proceso.
Primera lectura móvil sinconfirmar podía corresponder a timestampviejo;
no confundirla con fallo de autenticación. Verificador privado también
necesitó revertir una recodificación accidental de sus etiquetas, sin
afectar fuentes de producto. Interacción móvil390px OK,0excepciones,
cantidades y objetivos conservados, sinarmado. Última recarga exclusivamente
UI20:43:55 ET health200, procesos de mercado conservados. Validación móvil
final del indicador actual en curso al añadir esta nota.
