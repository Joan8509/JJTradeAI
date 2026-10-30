# Nuevas oportunidades después de una operación simulada

El usuario autorizó «las que sean necesarias hasta encontrar el mejor
movimiento» al preguntarle el máximo de compras por compañía/día. Se interpreta
como repetición sin un máximo diario en SIMULACIÓN, para señales nuevas tras
finalizar cada operación. No significa que la app pueda saber de antemano cuál
será el mejor movimiento ni que deba perseguir la misma señal.

En la preparación de cola se muestra la opción de repetición, activada por
defecto para las NUEVAS selecciones. Autorizar la cola guarda explícitamente
ese permiso por fila. Desmarcarla conserva compra única. Cambiar la opción
borra el consentimiento del formulario; no altera planes ya guardados.
No se transforma retrospectivamente ningún plan antiguo.

Tras cierre confirmado o cancelación/rechazo confirmado sin exposición, el
monitor concilia y crea una sucesora de la fila. Copia cantidad, objetivo,
rango y tope. Conserva la fila original, orden, llenados, aviso y claim; oculta
la fila anterior de la cola, manteniendo el resultado en Mis operaciones.
La sucesora captura nueva referencia y hora: solo acepta una señal distinta
y posterior. La ventana de30s de cada identidad no se reinicia. Una oportunidad
vista mientras estaba abierta la operación no se compra retrospectivamente.

No se rearma mientras haya posición o solicitud pendiente en esa compañía,
ni desde DISPATCHING/UNCERTAIN, mantenimiento, cierre, sesión terminada o rango
modificado. Un bloqueo de conciliación también impide el rearme. Como máximo
una sucesora por padre, con inserción atómica. Pausar o eliminar cualquier
miembro desactiva el permiso de toda esa cadena y pausa sucesores armados.
No cancela órdenes ya registradas ni cierra posiciones; estas siguen gestionadas.
Durante una operación existe el botón «Detener próximas entradas».

El trabajo no hace REST y usa adquisición no bloqueante del bloqueo de
ejecución, después de la observación de salidas. No añade espera al recorrido
del detector ni a sus búsquedas paralelas. Sin cambio de estrategia, spread,
frescura, rangos, stop20%, horario ni órdenes realesOFF. No implica límite
diario de pérdida nuevo ni recomendación de activar esto en real.

Pruebas en bases temporales: compra única por defecto en API, permiso explícito,
espera con compra/posición/venta pendientes, cierre y nueva vela con segunda
compra, cancelación sin fill sin repetir señal, pausa/eliminación, conservación
del historial/claims, inciertos, mantenimiento/fin de sesión, rango cambiado,
concurrencia y pausa durante la comprobación. AppTest comprueba presentación,
consentimiento y envío de la opción. Estado de carga en CURRENT_CONTEXT/diario.
