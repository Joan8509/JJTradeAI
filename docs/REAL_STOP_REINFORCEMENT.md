# Recuperacion del stop20%: refuerzo17Nov

El usuario pide reforzar el cierre automatico por perdida tras incidentes que
requirieron cierre manual. Se conserva el disparador LOCAL al Bid <=80% del
costo medio confirmado. La venta LIMIT al Bid requiere confirmacion de fills;
no se convierte en STOP/OCO nativo ni se cambia el objetivo por ganancia.

Ademas de la correccion de actividad CANCELED documentada en
REAL_CANCEL_ACTIVITY.md, se cubren reservas locales que pueden impedir seguir:

- Toda venta propia PREPARED vencida, con parent_id, se libera mediante la
  comprobacion atomica existente del ledger. Antes solo se limpiaban objetivos
  BROKER_TARGET; una salida ordinaria sin enviar podia conservar su reserva
  tras perder el proceso. No se libera SUBMITTING/UNCERTAIN ni una orden con ID.
- STOP puede abandonar inmediatamente un objetivo PREPARED que aun no se envio,
  sin esperar a que venza. Si begin_submit gana la carrera, conserva la reserva.
- Un STOP ya persistido puede cancelar el objetivo aceptado sin depender de
  otra cotizacion. Para enviar la nueva venta sigue necesitando Bid valido,
  sesion, cantidad propia y cancelacion terminal confirmada.
- Si una salida del stop queda incierta o lleva5s activa sin confirmacion,
  el monitor informa revision y el aviso identifica el stop20%. Se deduplica
  por posicion/estado. No informa una venta ejecutada hasta confirmar fills.

Se conservan fills parciales, cantidades reservadas, cierre manual externo,
rechazos y recuperacion acotada, objetivos elegidos, SEV25 bloqueado y cola
consumida/pausada. Los fallos de transporte no autorizan repetir POST inciertos.
Esta auditoria identifica riesgos adicionales; no atribuye retroactivamente
estos riesgos a un incidente sin su evidencia.

Pruebas nuevas usan broker y almacen sinteticos: reinicio con salida sin enviar,
rebote despues de STOP, umbral exacto, liberacion contra envio concurrente,
cancelacion con fallo de quotes, demora/ejecucion parcial y aviso deduplicado.
Revision de carga: worker.stop_exit_recovery_revision=1. Resultados efectivos,
recarga soloREAL y verificaciones posteriores se registran en CURRENT_CONTEXT.
Evidencia privada: exports/trade_review/2026-11-17_stop_reinforcement/.

Validacion final:401pruebas aprobadas90.278s. Recarga soloREAL20:37ET
con revision1 comprobada, guardas broker/cola y tres muestras finales actuales.
Primera lectura antigua preservada; repeticion sin reinicio aprobada.
No se envio una operacion real de prueba; detalle y limites en CURRENT_CONTEXT.
