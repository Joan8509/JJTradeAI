# Objetivo de ganancia colocado en Schwab tras la compra

Petición del usuario: automatizar la venta por ganancia directamente en Schwab
para eliminar la espera de que la VPS detecte el toque y envíe la orden.
Se mantiene el stop20% gestionado por la VPS. No se añade STOP nativo ni OCO.

## Recorrido

1. La compra conserva su ruta rápida y su autorización vigente.
2. Con la compra ya terminal y sus ejecuciones finales confirmadas, se calcula
   el objetivo sobre el precio medio realmente pagado y la cantidad pendiente.
3. Un hilo separado prepara una propuesta SELL_TO_CLOSE LIMIT y pide al
   endpoint preview de Schwab que valide exactamente cuenta, contrato,
   cantidad y precio. La confirmación queda vinculada mediante una huella.
4. Con preview aceptado y posición todavía disponible, se reserva esa cantidad
   en el diario y se envía la venta DAY. La orden queda esperando en Schwab,
   sin depender de una cotización posterior de la VPS para su disparo.
5. Una lectura WORKING de Schwab habilita la confirmación «Objetivo real
   colocado en Schwab». Un acuse de recepción por sí solo no demuestra WORKING.
   La ejecución efectiva conserva su aviso de venta confirmado separado.

Ejemplo hipotético: precio medio0.50 y objetivo10% → propuesta LIMIT0.55.
Si el porcentaje produce fracciones de centavo, la propuesta redondea hacia
arriba para no reducir el objetivo. Ese redondeo NO certifica un incremento
admitido para el contrato: requiere aceptación del preview del precio exacto.
Un rechazo no habilita probar incrementos inventados.

## Coordinación y recuperación

- El precio previewado obtiene el modo `SCHWAB_PREVIEWED_LIMIT`, exclusivo
  para cierres propios con padre, prueba vinculada y permiso efímero. No
  habilita compras, precios arbitrarios ni la recuperación de un envío incierto.
- La vigencia corta de la propuesta controla el momento de enviar. La orden
  DAY ya aceptada no se cancela por caducar aquella propuesta o su cotización.
- El stop20% y el cierre manual tienen prioridad. Se cancela la venta de
  ganancia y se espera una lectura definitiva de sus fills antes de vender
  únicamente el saldo. Un fill durante la cancelación no genera otra venta.
- Preview y POST de la ganancia no retienen el bloqueo del monitor de precios.
  Si el stop aparece durante la preparación, la guarda final impide enviar el
  objetivo. Si ya se envió, se concilia/cancela antes de reemplazar.
- Reinicios conservan el ID de broker y la reserva. Una propuesta PREPARED
  vencida, probadamente no enviada, puede liberarse; SUBMITTING/UNCERTAIN no se
  reenvía. Rechazos o respuestas inciertas generan revisión y aviso específico.
- Si falla solo la preparación del objetivo, antes de crear una orden, la VPS
  conserva su salida por precio y su stop. Se muestra y avisa que la venta por
  ganancia todavía no está confirmada en Schwab.
- Para cerrar manualmente desde la app se utiliza el cierre existente, que
  cancela primero la venta pendiente. Una venta manual desde el broker exige
  revisar las órdenes de cierre ya activas sobre ese mismo contrato.

## Validación

219 pruebas aisladas pasaron en11.391s, incluyendo el objetivo antes de tocar
precio, costo real frente al Ask, preview rechazado o cambiado, reserva,
reinicio, orden incierta, vigencia DAY, stop y fill durante cancelación, espera
HTTP independiente, serialización de la orden y avisos sin duplicados.
No se enviaron nuevas órdenes ni avisos reales para probar esta incorporación.

El estado actual requiere una consulta nueva. No se puede
demostrar una venta real de objetivo nueva sin una próxima operación real;
esa primera confirmación debe comprobarse con la respuesta auténtica de Schwab.
La presencia de una LIMIT adelanta su envío y conserva el precio mínimo; no
convierte el toque del gráfico en una garantía de ejecución.

El estado de carga y sus comprobaciones quedan en CURRENT_CONTEXT y el diario.
Evidencia privada: exports/trade_review/2026-11-03_real_readiness/.
