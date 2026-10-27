# Entrada: informes y recibos fuera del recorrido crítico

27/10/2026 ET. Usuario pide buscar más maneras de reducir el tiempo entre
detección y operación. Referencia live privada: revisión del caso positivo
en2026-10-27_meta_trade/ (no comparar ganador con contrafactual garantizado).

## Hallazgos y cambios

La cola calculaba dos informes detallados de todos los contratos antes de
crear la orden. Son explicaciones opcionales; la selección/revalidación que
autoriza la entrada es independiente. Ahora producción solo encola sus
instantáneas inmutables con fecha original; trabajador separado calcula y
guarda el informe. No se quitan filtros ni se usa la explicación para comprar.

Después de crear orden, la cola preparaba recibo MiniApp con varias escrituras
SQLite mientras retenía el RLock del workflow. El monitor esperaba ese trabajo
para confirmar fill. Ahora se guarda SUBMITTED/client_key duradero, se despierta
al monitor y se libera RLock; recibo/enlace se preparan aparte. Fallar un recibo
no convierte una orden despachada en UNCERTAIN ni provoca reintento. La compra
única sigue protegida por claim persistente antes de dispatch. Incertidumbre
real de dispatch sigue bloqueada sin retry.

Un trabajador local, cola64 y enqueue no esperable. Saturación/fallo de datos
informativos incrementa contador; no retrasa orden. Dashboard y aviso automático
usan client_key/fills, no necesitan intent. El enlace privado puede publicarse
después; una caída/reinicio puede perder trabajos informativos pendientes, sin
perder órdenes/claims ni reenviar avisos. No reconstruir trades desde esos jobs.
No nuevas peticiones de proveedor ni streams. Espaciado/backoff sigue intacto.

Se añade workflow_lock_wait_ms al ORDER_REGISTERED para medir contención real
en la próxima sesión; separarlo de HTTP/fill. No aumentar sondeo de señales ni
reducir tolerancias. Caché subsegundo y calendarios preparados ya existían.
Streaming de opciones o cambio de feed no se implementó ni se presenta como
mejora disponible sin estudiar permisos/semántica/continuidad.

## Comprobación

Pruebas aisladas: no se calcula informe en step productivo; orden/claim y wakeup
existen antes del recibo; recibo detenido no retiene RLock ni impide fill;
falla de recibo no crea incertidumbre falsa/recompra; cola llena no frena entrada.
No son una medición de milisegundos ganados en mercado. El objetivo es eliminar
dependencias, no prometer fill instantáneo cuando falta quote/tamaño/contrato.

Primera tanda47OK. Otra85 tuvo1fallo de test anterior que también falla con
_execute previo (check_baseline.py privado): esperaba GET elegido obligatorio
aunque catálogo subsegundo permitía reutilización. Se envejecen quotes2s para
forzar GET y se comprueba llamada una vez y rechazo real por prima, sin alterar
límites ni código de selección para pasar prueba. Resultado final en continuidad.

Carga esperada background_entry_presentation_v1, entry_auxiliary_enabled=true.
No declarar activado antes de guard y nueva comprobación del radar; preservar
revisión de salidas y caché. Fuentes previas/evidencia privadas en
exports/trade_review/2026-10-27_entry_auxiliary/. Sin órdenes reales ni mensajes.

Carga ACTIVA19:09:00ET, revisión/flag esperados. Repetición85OK tras prueba
corregida. Guard+barrera sin exposición/pending, hashes contables/claims/
autorizaciones/regla iguales,154dedup y dosUNCERTAIN preservados. Colector,
interfaz y tarea iguales; salidas/caché/observación previas conservadas.
Auditoría19:09:40: monitorREADY, HTTPS200, Telegramautenticado, ceroórdenes/
mensajesdelagente. Sincommit/push. Medir próxima entrada de mercado; no
afirmar ahorro cuantificado ni fill instantáneo porque se quitaron dependencias.
