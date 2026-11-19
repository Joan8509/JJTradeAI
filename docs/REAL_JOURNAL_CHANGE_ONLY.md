# Conciliacion sin escrituras repetidas

Cada GET de una orden sigue normalizandose y validandose contra el journal
cifrado actual bajo el mismo bloqueo. Una respuesta que conserva estado,
fills, errores y modo de evidencia ya persistidos no vuelve a cifrar/reemplazar
el archivo ni agrega otro evento identico. Los heartbeats del worker conservan
la comprobacion de actividad; updated_at del journal expresa un cambio.

Cada cambio real sigue siendo durable antes de continuar: nuevos fills aun
en el mismo estado parcial, error nuevo, recuperacion, cancelacion terminal.
Errores de disco y de identidad siguen impidiendo continuar. Ninguna lectura
se sirve desde cache y no se libera una reserva por una cancelacion pendiente.
No se elimina historial anterior ni se reenvian operaciones inciertas.

Esto reduce escrituras y competencia por el archivo cifrado; no elimina el
tiempo de red ni garantiza un precio de stop. Se conserva objetivo LIMIT en
Schwab y stop local20% al Bid, con confirmacion de cancelacion y cantidad propia.
Revision diagnostica journal_change_only_revision=1; carga y pruebas efectivas
en CURRENT_CONTEXT. Evidencia privada bajo exports/trade_review/.

Al confirmar fills o estado terminal de cancelacion/rechazo/expiracion, el hilo
de ordenes despierta el monitor de salida. El evento solo adelanta su consulta:
no autoriza vender, liberar reservas ni omitir revalidaciones de precio/cantidad.
El ciclo periodico200ms permanece como respaldo.
