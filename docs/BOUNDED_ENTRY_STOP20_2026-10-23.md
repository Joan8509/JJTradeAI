# Entrada automática oportuna y stop20

Petición23/10: priorizar entrada junto a detección, stop20% y reducir
oportunidades perdidas. Sustituye stop10% para NUEVAS operaciones; planes
de posiciones ya ejecutadas son inmutables. Cierre manual y objetivos
10/20/35/100/MANUAL conservados. Solo simulación local; órdenes reales OFF.

La detección sigue intravela y separada de Telegram. Solo filas explícitamente
armadas con cantidad, objetivo y sesión autorizan comprar. No se amplían
bandas1%, frescuraIEX3s/Schwab30s, spread0.08, rangos ni primeros5strikesOTM.

La orden automática nueva lleva límite máximo igual al techo del rango
autorizado y reserva cantidad×100×ese techo. Se elige el contrato más cercano
apto con Ask vigente; el fill sigue al Ask real de una cotización estrictamente
posterior a crear la orden, con tamaño visible. Nunca se fabrica fill al techo
ni se usa el precio anterior a enviar. Precio mejorado inferior al rango puede
seguir completando una orden válida: preserva el comportamiento previo.
Solo ManualPracticePolicy admite esta autorización tipada; manual conserva
su confirmación exacta y límite al Ask revisado. No afecta órdenes antiguas.

Antes del matching automático se revisan spread y distancia ITM/OTM5 frente
al spot Schwab. Un techo de precio no autoriza contrato lejano ni quote viejo.
La orden nueva caduca a los10s desde registro, inclusive; se comprueba antes
y después de REST. Se cancela solo el remanente con reconocimiento del broker
LOCAL y conciliación. Lo ya comprado conserva stop/objetivo; el vencimiento
de compra nunca cancela la venta. No rearma ni duplica la señal consumida.
Una señal válida es el disparador; no se exige recuperar EXIT durante esos
10s para completar la orden, preservando retracciones breves. No es permiso
para entradas históricas o varios minutos después.

Registrar una compra despierta inmediatamente al monitor de ejecución, sin
esperar el intervalo o Telegram. El evento se limpia antes de observar para
no perder solicitudes durante una consulta lenta. Pendientes automáticos
piden cotización nueva del contrato seleccionado; HTTP/429/backoff vigentes.
No se abre otro stream ni se aumenta el sondeo de reposo del monitor.

Persisten límites externos: proveedor/REST, precio fuera de rango, spread,
ausencia de contrato, datos o monitor no aptos. No garantiza todas las entradas,
beneficio ni un fill exactamente en el porcentaje del stop. No se ampliarán
filtros para ocultar estas causas. Estado de carga y pruebas en continuidad.
