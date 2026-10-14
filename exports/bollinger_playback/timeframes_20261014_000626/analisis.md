# Bollinger 15 minutos y comportamiento en 1 minuto

La estrategia se evalúa en 15 minutos. Las bandas de 1 minuto describen otra ventana de precios y no tienen que mostrar la misma exposición.

Corte: 2026-10-13T20:06:26.471016-04:00. Historial: 365 días naturales; 17 compañías; ALPACA/IEX; regla fija v3_bandas_en_apertura.

Se reconstruyeron 5945 primeras detecciones por vela/lado. Tras comprobar los cierres de referencia de 15 minutos y una ventana íntegra de 20 minutos, quedaron 3947 señales con ambas temporalidades comparables. Hubo 136 señales con referencias de 15m verificables pero ventana de 1m desconocida. Las exclusiones detalladas quedan en summary.json.

En esas 3947 señales, 1m estaba fuera en la misma dirección en 2434 (61.7%); dentro de sus propias bandas en 1513 (38.3%); y fuera por el lado contrario en 0 (0.0%). Todos esos casos cumplían la regla de salida en 15m al cierre del minuto observado.

Para comparar el recorrido posterior se usaron 3291 casos con 15 minutos completos posteriores, sin solapamiento dentro de compañía/fuente. Son retornos del subyacente, separados de una entrada teórica en la primera apertura posterior. No son rentabilidad de opciones.

Periodo anterior: a 5 minutos, el precio terminó a favor del observado en la señal en 49.5% de los 1729 casos fuera en 1m y 49.0% de los 1092 casos dentro en 1m. Intervalo exploratorio de la diferencia fuera menos dentro, agrupando fechas de mercado: -3.5 a 4.5 puntos porcentuales.
Comparación dentro de compañía, lado, exposición en 15m, fase de sesión y edad de vela: 24 grupos con al menos cinco casos de cada estado. Diferencia ajustada descriptiva a 5m: -5.6 puntos porcentuales. No demuestra causalidad.

30 días siguientes: a 5 minutos, el precio terminó a favor del observado en la señal en 53.7% de los 147 casos fuera en 1m y 52.0% de los 100 casos dentro en 1m. Intervalo exploratorio de la diferencia fuera menos dentro, agrupando fechas de mercado: -10.7 a 12.4 puntos porcentuales.
No hubo suficientes grupos comparables para ajustar por esas características en este periodo.

30 días más recientes: a 5 minutos, el precio terminó a favor del observado en la señal en 45.6% de los 147 casos fuera en 1m y 51.3% de los 76 casos dentro en 1m. Intervalo exploratorio de la diferencia fuera menos dentro, agrupando fechas de mercado: -20.8 a 10.6 puntos porcentuales.
No hubo suficientes grupos comparables para ajustar por esas características en este periodo.

Mientras la vela original de 15m seguía expuesta, hubo 15707 cierres posteriores de 1m observables. En 12320 (78.4%) el precio estaba dentro de las bandas propias de 1m. Son observaciones repetidas dentro de movimientos; no son operaciones independientes.

Exigiendo además que siguieran cumpliéndose todas las condiciones originales de 15m, incluidas ambas bandas abriéndose, quedaron 15155 cierres posteriores. En 11782 (77.7%) el precio estaba dentro de las bandas de 1m. La divergencia también aparece mientras la regla completa de 15m continúa vigente.

Se observaron 1562 primeras transiciones de fuera a dentro de las bandas de 1m mientras 15m seguía expuesto. En 345 (22.1%) el precio no se movió en contra entre esos dos cierres; en 311 incluso avanzó en la dirección de la salida. Volver dentro de una banda móvil no equivale necesariamente a una reversión del precio.

Al restringir esas transiciones a la regla completa de 15m todavía vigente, hubo 1480 casos: 344 (23.2%) sin retroceso entre esos cierres.

Ejemplo ilustrativo: AAPL el 06/10/2026, barra de 09:47 AM ET, vela 15m de 09:45 AM. Salida inferior válida en 15m a precio 331.845, mientras estaba dentro de las bandas de 1m. La barra se conoce al terminar su minuto; no representa una alerta recibida al inicio de esa barra.

La comparación no se usa para activar un filtro nuevo. Una señal válida en 15m puede coexistir con precio dentro de 1m; exigir que ambos estén fuera eliminaría esas señales. La posición en 1m puede servir como contexto, pero todavía no demuestra una mejora estable de selección de entradas.

La cobertura íntegra de 1m fue insuficiente para comparaciones sólidas en BABA, DIA, GLD, NIO. No se fabricaron minutos ausentes ni se trasladan los porcentajes de las compañías más líquidas a esas compañías.

Limitaciones: cierres de un minuto, no ticks históricos; no se identifica la secuencia interna de la vela ni la duración exacta de exposición. IEX y casos completos pueden sesgar la muestra. La historia reciente ya se había explorado y no es una validación futura independiente. Ningún resultado autoriza operaciones ni predice una ganancia del contrato.

Las bandas usan 20 periodos, desviación 2 y ddof 0 en ambas temporalidades. La detección rápida preparada para la app actualiza Bollinger de 15m con precios nuevos; no requiere que el precio salga simultáneamente de Bollinger de 1m. Se mantienen las dos bandas de 15m abriéndose como requisito. No se cambió el dashboard ni el radar por este estudio.
