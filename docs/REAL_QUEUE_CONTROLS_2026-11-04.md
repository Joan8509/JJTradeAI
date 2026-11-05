# Activación única y controles de espera REAL

Petición del usuario: activar las compañías desde Preparar compañías, simplificar
Cola real y poder pausar/reactivar o retirar las compañías que esperan.

## Recorrido

1. Cuenta: consultar y elegir una cuenta verificada una sola vez.
2. Preparar compañías: elegir compañías, cantidades y objetivos. **Activar
   preparación** guarda esa selección y arma la cola REAL en la misma acción
   explícita. Al terminar abre Cola real y muestra las compañías bajo el radar.
3. Cola real: ver únicamente filas pendientes o en seguimiento. No muestra una
   preparación guardada como si ya estuviera activa, ni filas retiradas/caducadas.

La activación comprueba disponibilidad del ejecutor, identidad de cuenta y selección
vigente. Si ya existe una cola activa/en revisión, no se sustituye silenciosamente.
Un fallo no se presenta como activación confirmada. Visitar/cargar una pantalla
o recuperar una preparación guardada no arma ni reanuda compras.

## Controles de Cola real

- **Quitar compañía de la cola real:** retira una fila pendiente sin solicitud,
  reserva o claim; conserva las demás y su historial.
- **Pausar / Activar:** un solo control cambia de nombre con el estado real.
  Activar reanuda las filas PAUSED elegibles de la misma cola y sesión; conserva
  ID, armado original, señales usadas, reservas e historial. No renueva los
  30 segundos de una señal. No reactiva retiradas, excluidas tras primera compra,
  operaciones completadas ni estados de revisión. Requiere cuenta/ejecutor actuales.
- **Eliminar todas las compañías en espera:** una transacción retira solo filas
  ARMED/PAUSED sin solicitud/claim/propiedad de entrada, y pausa nuevas compras.
  No cancela órdenes, vende contratos ni elimina sus registros. Una solicitud
  ya iniciada conserva su monitorización y conciliación.

Una cola de sesión finalizada no se reanuda para otro día: requiere activar una
nueva preparación explícitamente. La primera compra confirmada, incluso parcial,
sigue excluyendo las demás compañías de esa cola. Las salidas siguen activas
durante la pausa o después de limpiar las filas pendientes.

La cola usa un fragmento de interfaz de 2 segundos, con lecturas locales del
estado cifrado; se elimina Actualizar estado de cola real. El temporizador no
recarga todo el dashboard ni hace consultas al broker. Las acciones actualizan
la vista inmediatamente. Se conserva la visualización de posiciones y cierres.

Los métodos nuevos de reanudar/retirar se ejecutan desde el control de la UI.
Los métodos existentes del host, incluida adquisición atómica de una entrada,
son iguales al respaldo por AST. Solo la interfaz necesita recargarse. El estado
de carga y las pruebas efectivamente completadas se registran en el contexto y
el diario; las pruebas no activan la cola productiva.
