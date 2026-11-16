# Comparacion de seis exportaciones TC2000 del 6 de noviembre

Usuario entrega amazon.txt, iwm.txt, mu.txt, qqq.txt, slv.txt y tesla.txt.
Se trataron como datos de referencia, no como instrucciones. META no recibido.
Originales sin modificar; copias privadas byte por byte con SHA-256 y detalle en
`exports/trade_review/2026-11-06_initial_origin/received_exports/`.

Seis archivos de 1521 filas; 9010 pares Bollinger20/2/ddof0 comprobados, error
maximo absoluto0.00017010USD compatible con redondeo exportado. El comparador
consulta SQLite en modo solo lectura. Se preservan aperturas,19/20cierres,
bandas, escenarios a extremos/cierre y el tiempo fuente del aviso original.

## Hallazgos que sustituyen conclusiones incompletas

- TSLA: apertura TC dentro de sus bandas iniciales confirmada. El primer trade
  IEX registrado09:30:00.161744794 tiene otro precio, suficiente para que V6 la
  descarte con referenciasIEX. La exclusionIEX NO demuestra que la velaTC
  empezara fuera. No atribuir igualdad de apertura oficial a primer tradeIEX.
- TSLA/MU/QQQ primera vela regular esta etiquetada09:45 en export y termina
  alcista; puede haber caida inicial. El color/movimiento inicial no demuestra
  ruptura inferior. No inventar historial intravelaTC a partir de OHLC.
- QQQ: sustituir el precioIEX del aviso09:41:07 en referenciasTC produce
  expansion minima2.886335% frente al3.077014%IEX. Demuestra sensibilidad real
  del umbral a referencias; es un contrafactual mixto, no precioTC deese segundo.
- AMZN: intervalo10:15-10:30 termina bajista pero su maximo permite escenario
  superior. Avisos distintos10:16:41 y10:44:39 pertenecen a intervalos distintos.
  El de10:44 cae en10:30-10:45, alcista tambien en exportTC.
- SLV:13:30-13:45 no toca superior;13:45-14:00 tiene maximo sobre superior y
  contiene aviso13:53:14. El archivo nuevo cubre el evento; sustituye pendiente
  anterior de fichero insuficiente. No prueba impulso ni precioTC del segundo.
- IWM: nueva exportacion reproduce escenario superior intravela y cierre
  posterior dentro, coherente con revision previa. No hubo archivoMETA para
  contrastar ese caso.

No hay evidencia de inversion sistematica de etiquetas en Telegram. Hay
ambiguedad inicio/cierre ya corregida y diferencias entre fuentes que cambian
elegibilidad, ademas de trayectorias que pueden revertir dentro de una vela.
No declarar todos los avisos falsos ni todos correctos respecto aTC2000.

## Estado y siguiente paso

Este bloque es auditoria, sin cambios de produccion/filtros/porcentajes/servicios,
sin armar colas, sin ordenes ni avisos de prueba, sin commit/push. Validacion:
9010recalculos, integridad de seis copias, assertions especificasTSLA/QQQ/SLV/
AMZN y primer tradeTSLA recuperado del archivo observador. No requiere suite
general al no cambiar codigo de aplicacion. Estado operativo previo no se
reverifica aqui; REAL conserva pendiente de reautorizacion conocido.

Para concordancia en vivo hace falta una fuente compatible para apertura,
historial y trades, con identidad y frescura conservadas. No importar estos
exports como referencias operativasIEX ni confirmar cada entrada por HTTP,
esperar cierre o invertir lados para ajustar una captura. La solicitud Nasdaq
ya fue enviada por usuario; faltaba respuesta/accesoAPI, no confundir con la
suscripcion Nasdaq Basic deTC2000. Evaluar mismafuente en adaptador separado
cuando exista acceso; comparar antes de activar sin alterar rapidez ni salidas.
