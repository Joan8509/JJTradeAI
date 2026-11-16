# Recuperación de confirmaciones de órdenes reales

Una compra puede ejecutarse en Schwab aunque falle la publicación local de su
confirmación. El journal conserva SUBMITTING y bloquea compras duplicadas, pero
sin número de orden/fills no puede iniciar avisos o salidas. La auditoría confirmó
una copia temporal cifrada ACKNOWLEDGED frente al journal definitivo SUBMITTING.
El código exacto del error Windows no quedó registrado; no se atribuye a una
causa de sistema concreta sin esa evidencia. Detalles operativos privados.

## Correcciones

- Las vaults REAL reintentan únicamente el reemplazo atómico ante errores Windows
  5/32/33, con espera acotada. No se repite el cuerpo de la transacción ni HTTP.
  Otros errores y un bloqueo persistente siguen propagándose.
- Cada respuesta de creación válida conserva un recibo cifrado independiente,
  vinculado a cuenta, solicitud, contrato, cantidad, precio y tiempos originales.
  Se conserva además una copia en memoria mientras vive el coordinador.
- El observador de órdenes recupera exclusivamente IDs de esos recibos exactos,
  incluso tras reinicio si fueron publicados. Después exige GET normal y fills
  auténticos antes de acreditar posición, objetivo, aviso o stop. No busca una
  compra parecida, no adopta compras externas y no repite POST.
- El resultado es idempotente si el observador recupera el acuse mientras la
  llamada de envío aún retorna. La cola conserva su solicitud/claim y consume
  primera entrada al comprobar fills, excluyendo las otras compañías.
- Una compra sin confirmación después de cinco segundos genera un aviso separado
  de revisión urgente aunque todavía no tenga fills. No la presenta como compra
  confirmada. Conserva deduplicación y tratamiento de entregas inciertas.

Si se pierde la respuesta antes de disponer del ID, no se inventa un recibo.
Si ambos guardados fallan, la copia en memoria necesita que siga vivo el proceso.
Esos casos conservan el bloqueo y requieren conciliación; la alerta no sustituye
una protección en el broker. El stop20% continúa local; no se añade STOP/OCO.

## Validación y carga

Pruebas con inyección de fallo de publicación, recuperación tras reinicio,
identidad cambiada, respuesta perdida, carrera del observador y ausencia de
duplicados. Tras recuperar: aviso de compra, objetivo LIMIT10% antes del toque
y stop al Bid80% del costo. Reproducción aislada de GET auténticos comprueba
compra/cierre manual sin cambiar producción. Recuentos finales y estado efectivo
en CURRENT_CONTEXT y el diario; recibos privados en la revisión del05/11.

Las pruebas no enviaron órdenes o avisos reales. La revisión no cambia estrategia,
cantidades, rangos, ventana de entrada ni simulación. Un proceso vivo o un heartbeat
anterior a la compra no prueba que se haya publicado su confirmación.

## Regla general de compra, aviso y objetivo

La corrección se aplica al ejecutor compartido de todas las compañías. Regresión
adicional: cuarenta combinaciones de cinco símbolos, CALL/PUT y objetivos10/20/
35/100 comprueban preparación por fila, compra antes del aviso, fill confirmado,
venta LIMIT calculada sobre el precio real y conservación del objetivo aunque
se edite una preparación posterior. No se espera Telegram para entrar ni el
toque del precio para colocar la LIMIT. Los avisos de ejecución se distinguen
de los avisos de estrategia y de confirmación pendiente.
