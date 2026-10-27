# Navegación: carga repetida del fondo

26/10/2026 20:13 ET. Usuario pregunta por lentitud al navegar.

Se identificó en `_dashboard_background_data_uri` y
`_render_dashboard_visuals` una imagen PNG de 1.396.700 bytes incrustada
dos veces como base64 en cada ejecución completa de la interfaz. Estaba
cacheada su lectura en Python, pero eso no eliminaba el contenido enviado
en los mensajes de renderizado.

`app.py` conserva exactamente imagen, gradientes y estilos y usa ahora la
URL relativa `app/static/trading-bull-candles-bg.png`, con static serving
ya habilitado. No se publica ninguna carpeta privada. La imagen se separa
del renderizado y mantiene una URL estable durante la navegación.

Medición de los tres mensajes markdown reales del renderizador aislado:
3.727.274 → 2.770 bytes (99,926% menos). Comparación exacta confirma que
solo cambia la representación de la URL; mismo SHA de imagen. Respuesta
200 tanto local como HTTPS Tailscale. El servidor no devuelve 304 para la
prueba If-None-Match aunque ofrece ETag: no afirmar caché persistente ni
una única descarga entre recargas completas. La reducción medida es del
payload visual, no de la latencia total del teléfono.

Pruebas: py_compile; 23 tests de preparación múltiple/conexión y 4 de
navegación OK. Recarga únicamente interfaz 20:11:49 ET, health200,
identidad de los procesos de mercado conservada. Ninguna modificación en
detector, motor de entradas, autenticación, registros de operaciones,
deduplicación, Telegram ni estado de órdenes reales deshabilitadas.

Otra espera identificada por lectura del código, sin medición de red en
este bloque: el editor consulta Schwab síncronamente al caducar la caché
de conexión de 30 segundos y antes de armar. No se cambió ni se eliminó
esa verificación. Pendiente medir navegación completa en teléfono y, si
persiste la demora, desacoplar el indicador de conexión del formulario
conservando la comprobación fresca obligatoria antes de autorizar.

Evidencia privada: `exports/trade_review/2026-10-26_navigation_latency/`
con fuente previa, medidor y measurement.json. Sin commit/push.
