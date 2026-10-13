# Estado del 13 de octubre de 2026

## Investigacion de latencia
Radar optimizado para reutilizar contexto SMA por barra exacta, simbolo, fuente, lado y precio. Se conserva la apertura obligatoria de ambos disipadores y el resto de condiciones de deteccion. No se elimina el contexto antes de avisar y no se habilitan operaciones. Prueba local readonly: 16 contextos de se?ales guardadas, primer pase 14496.72ms total / mediana887.721ms; segundo pase con claves identicas 0.02ms total / mediana0.001ms. No es una medicion de la latencia real del telefono ni del costo de nuevas barras.

Se corrige attempted_at para reflejar inicio de preparacion/envio de cada aviso, en vez del inicio comun del tick. detected_at tambien registra momento real de deteccion. Nueva tabla privada bollinger_notice_timing: cierre nominal barra, received_at capturado (ultima persistencia, no primera llegada garantizada), deteccion, inicio/final envio, fecha mensaje devuelta por Telegram, duracion contexto/ciclo/envio y estado. Telegram date acredita fecha del mensaje en servidor, no llegada/lectura en telefono. En pruebas con as_of el reloj de pared es determinista; perf_counter mide tiempos reales.

Se revalida la antiguedad de la barra antes de enviar, conservando el limite existente de 1 a 3 minutos. Evita enviar una se?al que envejecio durante calculos largos. El lease de radar conserva exclusividad y la clave de deduplicacion de avisos no cambia. Pasaron las 746 pruebas. Radar reiniciado sin detener buscador. Buscador sigue con 52 suscripciones hasta reiniciarlo con las claves; radar filtra 17.

Los datos personales de las capturas y su analisis quedan locales en exports/trade_review/, excluidos de Git. Revisiones historicas no permiten atribuir todo retraso a red, estrategia o usuario. Acceso a Schwab sigue pendiente de revision del portal; sin cotizaciones/autorizacion no hay compra/venta desde nuestra app. El enlace de Telegram abre revision, no ejecuta orden.


## Estudio de retrocesos de las 17 companias
Nuevo informe retracements_20261013_193747: 180 dias, 2906 salidas reconstruidas, 1998 casos completos no solapados y pareados con demora adicional0/1 minuto. Primer retroceso entre cierres en <=2 minutos ~74% en los tres periodos; no equivale a reversi?n. Salidas pequenas <1% ancho reentran mas que >=3% ancho en los tres periodos y 13 companias con muestra comparable. Ninguna salida fija simulada paso el contraste pareado de periodos; no se da objetivo universal ni se confunde porcentaje subyacente con prima. Datos intraminuto ausentes y omisiones IEX limitan la inferencia. Memoria interna de retrocesos por compania/fuente/direccion/exposicion con corte temporal, umbrales de muestra y sin nuevos filtros/UI; historicos posteriores al instante de la se?al no se usan.
