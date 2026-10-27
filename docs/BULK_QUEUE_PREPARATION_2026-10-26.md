# Preparar varias compañías

Petición26/10: seleccionar compañías primero y aplicar cantidades/objetivos
sin repetir el formulario completo. Modo principal «Varias compañías»;
«Una compañía» conserva la preparación individual.

Seleccionar varias, aplicar cantidad y objetivo comunes opcionalmente y
personalizar cada fila. Objetivos10/20/35/100/manual y cantidades explícitas.
Rango y máximo de primas por compañía y suma del grupo visibles. Una selección
sin rango o sin cantidad/objetivo completos no se pone en cola.

Autorización explícita del grupo/sesión; cambiar compañía, cantidad, objetivo
o sesión retira consentimiento. GET de conexión Schwab sin caché antes de
guardar. La selección se conserva si falla. Tras leer baselines se verifica
otra vez que ese recibo siga vigente y se consulta el calendario oficial.

QueueStore.arm_many valida todo y guarda en una transacción: todas o ninguna.
Conflicto ARMED/DISPATCHING/UNCERTAIN en cualquier fila revierte el grupo.
No modifica planes existentes, no reintenta claims ni compra durante armado.
Arm individual usa el mismo validador. Esquema y lector del radar compatibles:
solo interfaz necesita recarga, no colector ni radar.

No modifica estrategia3%, rangos, contratos, stop20%, avisos, deduplicación,
sesión oficial o simulación local. Sin órdenes reales. Pruebas y carga efectiva
se registran en CURRENT_CONTEXT y diario26/10.
