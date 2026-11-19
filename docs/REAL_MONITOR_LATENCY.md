# Latencia del monitor REAL

16/11/2026: investigacion de una muestra con heartbeat de salidas atrasado10.427s.
No se conservo su stack exacto; una recuperacion posterior no demuestra su causa.
El muestreo independiente posterior sin variables locales encontro8de40stacks
del hilo de salidas consultando next_official_session. La cola estaba consumida
y el journal no tenia exposicion propia: se consultaba el calendario antes de
descubrir que las compras historicas ya estaban completamente cerradas.

Correccion: _exit verifica primero fills de compra y de ventas hijas contra el
journal actual. Si no queda cantidad propia, limpia la observacion correspondiente
y retorna sin consultar calendario ni cotizaciones. Una venta parcial conserva
revision de sesion oficial y todos los controles del remanente. No se presume
cierre por estado terminal solamente ni por una lista de posiciones omitida.

Cuando queda posicion, host REAL usa exit_official_session: mismo calendario
almacenado, sin cache de resultados y sin inventar horarios. Espera SQLite por
lock50ms y presupuesto de ejecucion SQL50ms. Un error sigue siendo visible y
bloquea esa evaluacion; no autoriza vender con datos antiguos. El presupuesto
no limita suspensiones de Windows, apertura de archivos o tiempo de red.
La consulta habitual del dashboard conserva su configuracion anterior.

El worker ahora informa duracion del turno en curso y conserva los turnos que
superen1s. Si el host observa un turno lento, guarda hasta8frames con funcion,
archivo y linea, nunca variables locales, respuestas, tokens ni cuentas. No hay
nuevo hilo de red, escritura sincrona o llamada a broker por este diagnostico.
No se amplian los limites de salud ni se ocultan monitores atrasados. Se conserva
el fallo hasta la siguiente evaluacion valida; los turnos lentos quedan visibles
tras recuperarse. Revision worker monitor_latency_revision=1; host
exit_calendar_latency_revision=1. La documentacion no demuestra carga efectiva.

Pruebas cubren cierre completo sin calendario, cierre parcial con stop20% sobre
remanente, fallo de calendario visible sin venta, nuevos commits, bloqueo SQLite
sin reutilizar exito anterior y diagnostico de turno bloqueado sin datos privados.
Mantener objetivo elegido, reserva durable, conciliacion, ordenes inciertas,
exclusiones y simulacion. No repetir HTTP ni reducir controles para mejorar tiempo.

La mejora elimina una dependencia innecesaria demostrada. No establece que toda
demora historica viniera de esa consulta ni promete latencia cero. Guardar stack
si vuelve a aparecer un turno lento; medir compra y salida por fases en eventos
naturales. Evidencia privada:2026-11-16_monitor_delay. Estado cargado y validacion
efectiva en CURRENT_CONTEXT y diario local.
