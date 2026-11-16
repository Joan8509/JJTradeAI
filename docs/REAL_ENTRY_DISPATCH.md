# Atención rápida de señales reales

13/11/2026: la cola REAL incorpora una lectura conjunta de las señales ya
publicadas por el detector. Antes se realizaba la lectura completa de estado
por cada compañía ARMED, incluso cuando ninguna tenía señal. Una compañía al
final podía esperar detrás de esas lecturas locales.

El host consulta los símbolos ARMED mediante un único SELECT indexado y omite
en ese turno aquellos cuyo último estado indica que no hay salida. No cambia
el orden relativo de las compañías que sí tienen señal. No consulta opciones,
cuentas, preview ni envía órdenes para elaborar esta selección preliminar.

Una señal positiva sigue pasando por el proveedor completo: estrategia,
dirección, apertura, frescura, plazo original, contrato, cotización, fondos y
preview. También conserva reserva atómica, pausa, eliminación y exclusión de
las demás compañías tras la primera compra. Este dato preliminar no autoriza
una compra. Los monitores de salidas y avisos mantienen hilos independientes.

La lectura abre SQLite en modo de solo lectura con espera máxima configurada
de 50 ms y presupuesto de consulta de 50 ms. Esto limita espera de base de
datos; no es una garantía de duración total bajo suspensión o carga del sistema.
Si falla, hay JSON inválido o no se reconoce el resultado, se conserva el
recorrido completo anterior. Un símbolo sin fila también conserva su validación
completa. Un resultado vacío no se reutiliza: el siguiente turno vuelve a leer
la base; siguen vigentes la notificación local y sondeo de respaldo de 200 ms.

Solo el host REAL habilita este mecanismo. Las rutas de simulación y estrategia
permanecen iguales. Diagnóstico del worker: `entry_signal_hints_revision=1`.
La reducción comprobada es de consultas redundantes a compañías sin señal;
no demuestra por sí sola un ahorro específico en la ejecución futura de Schwab.

Código: real_entry_signal_hints.py, real_automatic_queue.py,
real_execution_runtime.py y real_execution_host.py. Pruebas aisladas y estado
de carga efectivo en CURRENT_CONTEXT y diario del 13/11/2026.
