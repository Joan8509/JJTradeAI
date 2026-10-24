# Reducir demora entre detección y compra simulada

Petición22/10: detectar pronto y ejecutar rápidamente las compañías armadas.
No implica autorización para nuevas compañías, órdenes reales ni cambiar
la estrategia. La compra de CALL/PUT sigue requiriendo una fila armada con
sesión/cantidad/objetivo y una señal nueva vigente, incluyendo bandas1%.

## Cambios

- La cola consulta señales cada200ms, antes500ms. Eso es la espera entre
  ciclos, no una promesa de latencia total ni de ejecución en200ms.
- Si el catálogo recién recibido contiene el contrato elegido y tanto su
  cotización como el spot y la respuesta tienen menos de1s, reutiliza esa
  evidencia en vez de hacer siempre otra consulta. Calendario completo debe
  seguir vigente; no se extiende su TTL5min. Caso contrario mantiene el GET
  del contrato/spot. Los usuarios manuales con force=True mantienen refresco.
- No se eliminan validaciones finales de señal/spot/contrato/rango/spread/
  strike/vencimiento/costo/monitor ni el claim durable antes de dispatch.
  Reutilizar precios no los actualiza artificialmente ni cambia sus fechas.
- Tras fallar por frescura/conexión o cambio de señal ANTES del dispatch,
  espera200ms para permitir un trade nuevo en vez de la pausa fija5s.
  Sigue necesitando señal actual; no reintenta una compra enviada o incierta.
  Rechazos de contratos/errores HTTP y Retry-After conservan sus pausas.
- Registro ORDER_REGISTERED añade duración de procesamiento y distancia
  desde trade inicial/final; ENTRY_REFRESH_RESULT indica si reutilizó catálogo.
  Estado privado informa revisión subsecond_catalog_poll200_v1 e intervalo.

El transporte HTTP compartido conserva mínimo1s entre inicios y Retry-After;
no hay otra conexión Alpaca ni colector. Telegram sigue en hilo separado:
no hay que esperar que el aviso llegue al teléfono para comenzar la compra.
El usuario debe poner en cola explícitamente cada compañía que quiera operar.

## Pruebas y límites

Pruebas aisladas con motor real local y cotizaciones sintéticas: una sola
consulta y un claim, datos justo1s obligan refresco, force manual, recuperación
con nuevo trade antes5s,429sin multiplicar consultas y polling200ms sin Telegram.
Regresiones de rango/Ask cambiante se ejercitan con spot de catálogo antiguo
para exigir GET y confirmar rechazo de precios fuera de rango.
No se llena una orden con una cotización anterior a crearla.

Red lenta, datos escasos enIEX, ausencia de contratos aptos, límites del
proveedor, múltiples compañías y precios que cambian pueden seguir causando
demora o impedir entrada. Un filtro1% puede cumplirse más tarde que una mínima
apertura: no se quita para acelerar. Las mediciones de mercado quedan para
la próxima sesión regular; reducir latencia no demuestra rentabilidad.
El estado real de carga y las pruebas ejecutadas se consultan en continuidad.
