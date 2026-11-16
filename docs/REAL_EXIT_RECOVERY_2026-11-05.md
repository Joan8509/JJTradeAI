# Recuperación controlada de salidas y confirmación inmediata

El usuario exige resolver las ventas automáticas al objetivo de cada compañía
y el stop20%. La confirmación local perdida se corrige en
[recuperación de acuses](REAL_ACK_RECOVERY_2026-11-05.md). Esta entrega endurece
las salidas posteriores y mantiene esas correcciones generales.

## Rechazo de una salida

Antes, cualquier hijo REJECTED bloqueaba todas las salidas posteriores, incluido
el stop. No bastaba con comprobar el Bid para recuperar una posición aún abierta.
Ahora se permite una única nueva venta tras un rechazo definitivo sin fills,
con evidencia fresca de Schwab: identidad, posición OPTION explícita exactamente
igual al remanente propio, ausencia de cortos y de otras órdenes activas del
contrato, y GET de órdenes que confirma cada rechazo conocido. La lectura debe
ser posterior a observar el rechazo y tener menos de5s. Posiciones omitidas no
se interpretan como cero, y cantidades externas incompatibles no se adoptan.

El monitor pide una actualización en segundo plano sin hacer HTTP de cuentas
en su ruta de precios. La prueba se vincula a cuenta/posición/cantidad/rechazos,
se consume atómicamente al reservar la nueva venta y se vuelve a verificar al
despachar, después de OAuth/esperas. No autoriza un segundo POST de una orden
incierta. Si la nueva venta también es rechazada, no crea un bucle. Solo se
libera el permiso cuando se demuestra que HTTP nunca se intentó o que la
reserva PREPARED venció sin enviar. El stop queda persistido aunque rebote el Bid.

Las ventas manuales externas, cantidades reservadas, fills durante cancelación,
primera entrada, exclusiones y objetivo mínimo siguen vigentes. El porcentaje
de la preparación se calcula sobre el costo ejecutado; no se cambia por10% fijo.

## Fallos de envío, avisos y tiempos

Una venta EXPIRED por HTTP no intentado se identifica como fallo de salida,
en lugar de presentar el monitor como sano. Respeta una espera local corta para
no llenar el journal de intentos sin enviar. El objetivo nativo sin enviar se
reporta pendiente y espacia su preparación. Las incidencias de salida tienen
aviso propio, deduplicado e independiente; un cierre confirmado suprime alertas
obsoletas pendientes. No se generan avisos nuevos de posiciones ya cerradas.

Los acuses de envío/cancelación despiertan al observador de órdenes. Los fills
confirmados despiertan objetivo y avisos sin esperar sus intervalos periódicos.
La compra no espera Telegram. Se conservan los límites y esperas del transporte.

## Alcance

No incorpora órdenes STOP/OCO nativas ni cambia el disparador local20% al Bid.
No cambia estrategia, rangos, cantidades, objetivos, sesión o simulación. No se
reactiva la cola durante la reparación. Pruebas aisladas cubren rechazo, proof
ausente/antiguo, venta manual, cantidades incompatibles, segundo rechazo, envío
incierto, vigencia al despachar, objetivo, avisos y despertares de los monitores.
Recuentos, carga y evidencia efectiva se registran en CURRENT_CONTEXT/diario.
