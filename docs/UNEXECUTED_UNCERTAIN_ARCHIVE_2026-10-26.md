# Retirada de intentos inciertos sin orden

Usuario26/10 observa tarjeta restante después de Borrar todas. La protección
anterior conservaba cualquier UNCERTAIN, incluso sin orden registrada.

Nueva retirada explícita solo después de cierre de sesión+1min y claim de
más de1min. Plan y único intento UNCERTAIN deben carecer de client_key;
aviso WAITING nunca despachado. Se comprueban identidad LOCAL y cuenta manual
en ledger y broker independientes. No puede existir orden alguna para clave
determinista de ese intento en ninguno de los dos, ni orden pendiente o
posición abierta de la compañía; ledger reconciliado. Error/ausencia de
archivo/identidad o datos dudosos impiden retirar. No consulta Schwab real.

Solo inserta queue_archives y decisión de comprobación. No cambia UNCERTAIN,
claim, notice_state ni filas de operación/fill. No permite rearme del intento,
no borra dedup y no reenvía avisos. Una incertidumbre con orden sigue protegida.
«Borrar operaciones» aplica esta comprobación a intentos vencidos; botón
individual «Comprobar y retirar» usa el mismo procedimiento. Archivar oculta
la tarjeta; no afirma ejecución ni pérdida ni cancelación de una orden.

No cambian QueueRunner/QueueNotifier ni detector. Solo recargar interfaz;
radar/colector siguen con código de entrada sin modificación funcional.
Procedimiento privado crea respaldo consistente de cola y compara ledger,
broker, planes, intentos y154dedup antes/después. Estado en contexto/diario.
