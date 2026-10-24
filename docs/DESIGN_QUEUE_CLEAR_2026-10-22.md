# Fondo original y limpieza de la cola

Petición del usuario22/10: conservar el diseño e imagen anteriores y permitir
quitar todas las filas en cola y ejecutadas de Operar Automáticamente.

La portada reutiliza `_render_dashboard_visuals()` sin alterar la imagen
`static/trading-bull-candles-bg.png`, el banner ni sus colores. Conserva las
tres pestañas, el ancho móvil y el refresco sin atenuación. El encabezado
compacto anterior se omite para evitar duplicarlo con el banner restaurado.

**Borrar operaciones** actúa únicamente al pulsarlo. Archiva las filas visibles
elegibles y pausa sus entradas sin ejecutar. Usa `QueueStore.archive`, que
revalida cada fila dentro de la transacción: si el worker ya la tomó o hay
exposición abierta/pendiente/incierta, se conserva y se informa el recuento.
No vende posiciones, cancela solicitudes ni vuelve a armar compañías.

Las filas de compras ya cerradas se pueden quitar de la cola, conservando
órdenes, fills, intentos, resultados y notificaciones. **Mis operaciones**
continúa mostrando el historial persistente. La consulta existente de cola
está limitada a250 filas; cada pulsación procesa esa instantánea, sin tocar
filas nuevas añadidas concurrentemente. No borra físicamente bases ni dedup.

Pruebas aisladas: armado/pausa/vaciado/idempotencia, protección de compra
pendiente, posición abierta y venta pendiente; eliminación después del cierre
con ledger byte a byte e intentos conservados; botón real AppTest que solo
actúa al pulsar. Se mantienen las regresiones de navegación y resultados.
La carga comprobada y sus límites se registran en el diario y contexto vigente.
