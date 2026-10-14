# Volatilidad de Bollinger en Hora y Diario al aparecer la salida de 15 minutos

Corte: 2026-10-13T20:06:26.471016-04:00. Se reutiliza el playback de 365 días y las 17 compañías, sin exigir coincidencia con Bollinger de 1 minuto.

Se mide si ambas bandas se abren y si el punto medio acompaña la dirección de la salida de 15m. Un aumento de ancho por una sola banda no equivale a apertura de ambas. No se exige que el precio esté fuera de Bollinger en Hora o Diario.

Se separa la vela de Hora/Diario que contiene el minuto de la señal (en formación o recién cerrada) de la última vela cerrada disponible. Para la vela en formación se usan 19 cierres anteriores y el precio observado, sin su cierre futuro. Las referencias se verifican con calendario y el último minuto observado del periodo. La última hora corta de la sesión se cierra al cierre programado del mercado.

La cohorte posterior tiene 3388 casos sin solapamiento dentro de compañía/fuente y 15 minutos completos. Los porcentajes a 1, 2, 5 y 15 minutos indican precio del subyacente a favor del observado en la señal; no ganancia de opciones ni precios de ejecución.

Hora observada:
En periodo anterior, a 2 minutos: 52.5% de 691 casos con ambas bandas abiertas y centro a favor, frente a 48.8% de 2050 sin esa combinación. Diferencia con intervalo exploratorio del 99%, por fecha de mercado: -2.4 a 9.6 puntos porcentuales.
Dentro de compañía, lado, exposición de 15m, fase de sesión y edad de vela: 14 grupos comparables; diferencia descriptiva a 2m 13.7 puntos porcentuales.
En 30 días siguientes, a 2 minutos: 53.3% de 60 casos con ambas bandas abiertas y centro a favor, frente a 47.7% de 176 sin esa combinación. Diferencia con intervalo exploratorio del 99%, por fecha de mercado: -16.8 a 26.5 puntos porcentuales.
No hubo grupos suficientes para comparar ambos estados dentro de esas características.
En 30 días recientes, a 2 minutos: 61.0% de 41 casos con ambas bandas abiertas y centro a favor, frente a 53.6% de 153 sin esa combinación. Diferencia con intervalo exploratorio del 99%, por fecha de mercado: -19.2 a 34.6 puntos porcentuales.
No hubo grupos suficientes para comparar ambos estados dentro de esas características.
La comparación supera el control descriptivo fijo de muestra e intervalo en entrenamiento y validación: no.

Diario observado:
En periodo anterior, a 2 minutos: 51.1% de 552 casos con ambas bandas abiertas y centro a favor, frente a 50.0% de 2342 sin esa combinación. Diferencia con intervalo exploratorio del 99%, por fecha de mercado: -4.8 a 6.4 puntos porcentuales.
Dentro de compañía, lado, exposición de 15m, fase de sesión y edad de vela: 4 grupos comparables; diferencia descriptiva a 2m -7.4 puntos porcentuales.
En 30 días siguientes, a 2 minutos: 47.8% de 23 casos con ambas bandas abiertas y centro a favor, frente a 51.1% de 229 sin esa combinación. Diferencia con intervalo exploratorio del 99%, por fecha de mercado: -32.1 a 23.1 puntos porcentuales.
No hubo grupos suficientes para comparar ambos estados dentro de esas características.
En 30 días recientes, a 2 minutos: 50.0% de 20 casos con ambas bandas abiertas y centro a favor, frente a 58.1% de 148 sin esa combinación. Diferencia con intervalo exploratorio del 99%, por fecha de mercado: -36.6 a 32.0 puntos porcentuales.
No hubo grupos suficientes para comparar ambos estados dentro de esas características.
La comparación supera el control descriptivo fijo de muestra e intervalo en entrenamiento y validación: no.

Última Hora cerrada:
En periodo anterior, a 2 minutos: 53.6% de 394 casos con ambas bandas abiertas y centro a favor, frente a 49.1% de 2344 sin esa combinación. Diferencia con intervalo exploratorio del 99%, por fecha de mercado: -1.8 a 10.7 puntos porcentuales.
Dentro de compañía, lado, exposición de 15m, fase de sesión y edad de vela: 1 grupos comparables; diferencia descriptiva a 2m 16.7 puntos porcentuales.
En 30 días siguientes, a 2 minutos: 56.2% de 32 casos con ambas bandas abiertas y centro a favor, frente a 48.0% de 204 sin esa combinación. Diferencia con intervalo exploratorio del 99%, por fecha de mercado: -5.7 a 26.4 puntos porcentuales.
No hubo grupos suficientes para comparar ambos estados dentro de esas características.
En 30 días recientes, a 2 minutos: 44.0% de 25 casos con ambas bandas abiertas y centro a favor, frente a 56.5% de 168 sin esa combinación. Diferencia con intervalo exploratorio del 99%, por fecha de mercado: -39.0 a 23.9 puntos porcentuales.
No hubo grupos suficientes para comparar ambos estados dentro de esas características.
La comparación supera el control descriptivo fijo de muestra e intervalo en entrenamiento y validación: no.

Último Diario cerrado:
En periodo anterior, a 2 minutos: 49.3% de 420 casos con ambas bandas abiertas y centro a favor, frente a 50.4% de 2474 sin esa combinación. Diferencia con intervalo exploratorio del 99%, por fecha de mercado: -7.9 a 5.1 puntos porcentuales.
Dentro de compañía, lado, exposición de 15m, fase de sesión y edad de vela: 1 grupos comparables; diferencia descriptiva a 2m -1.9 puntos porcentuales.
En 30 días siguientes, a 2 minutos: 40.9% de 22 casos con ambas bandas abiertas y centro a favor, frente a 51.7% de 230 sin esa combinación. Diferencia con intervalo exploratorio del 99%, por fecha de mercado: -36.0 a 14.8 puntos porcentuales.
No hubo grupos suficientes para comparar ambos estados dentro de esas características.
En 30 días recientes, a 2 minutos: 57.9% de 19 casos con ambas bandas abiertas y centro a favor, frente a 57.0% de 149 sin esa combinación. Diferencia con intervalo exploratorio del 99%, por fecha de mercado: -24.1 a 41.4 puntos porcentuales.
No hubo grupos suficientes para comparar ambos estados dentro de esas características.
La comparación supera el control descriptivo fijo de muestra e intervalo en entrenamiento y validación: no.

Hora y Diario observados simultáneamente:
En periodo anterior, a 2 minutos: 54.3% de 151 casos con ambas bandas abiertas y centro a favor, frente a 49.5% de 2581 sin esa combinación. Diferencia con intervalo exploratorio del 99%, por fecha de mercado: -4.9 a 15.1 puntos porcentuales.
No hubo grupos suficientes para comparar ambos estados dentro de esas características.
En 30 días siguientes, a 2 minutos: 55.6% de 9 casos con ambas bandas abiertas y centro a favor, frente a 48.9% de 227 sin esa combinación. Diferencia con intervalo exploratorio del 99%, por fecha de mercado: -54.2 a 52.4 puntos porcentuales.
No hubo grupos suficientes para comparar ambos estados dentro de esas características.
En 30 días recientes, a 2 minutos: 75.0% de 4 casos con ambas bandas abiertas y centro a favor, frente a 56.2% de 146 sin esa combinación. Diferencia con intervalo exploratorio del 99%, por fecha de mercado: -14.4 a 54.3 puntos porcentuales.
No hubo grupos suficientes para comparar ambos estados dentro de esas características.
La comparación supera el control descriptivo fijo de muestra e intervalo en entrenamiento y validación: no.

La Hora observada mostró diferencias favorables a dos minutos en los tres periodos. Los intervalos y los tamaños de muestra anteriores limitan la conclusión; este resultado no certifica una mejora de entradas.

La ventaja inicial tampoco implica continuidad más larga: a cinco minutos en el periodo reciente, el precio seguía a favor de la señal en 36.6% de 41 casos con esa combinación de Hora, frente a 49.7% de 153 sin ella. No se deriva un tiempo óptimo de salida de esta comparación.

Diario no superó el control en el criterio principal. La coincidencia de Hora y Diario tuvo 9 casos en validación y 4 recientes; esa coincidencia no confirma por sí sola continuidad.
Ninguna de las cinco comparaciones pasó el control fijo en entrenamiento y validación.

El control exige al menos 100 casos por grupo y 20 fechas en el periodo anterior; 50 casos por grupo y 10 fechas en validación; diferencia positiva cuyo intervalo del 99% quede por encima de cero en ambos periodos. Es un control exploratorio, no una autorización de filtro ni una validación futura.

El tamaño del movimiento y los retrocesos se estudian por separado de la apertura de bandas. Los máximos favorables y adversos se miden entre cierres observados de minuto, son retrospectivos y no identifican un precio ejecutable de salida. El resumen incluye una exploración de apertura de bandas por sí sola, sin exigir alineación del centro; no forma parte del control fijo de selección.

Hora y Diario pueden aportar contexto distinto: unas bandas abiertas sin centro a favor, unas bandas que solo se desplazan, o bandas estrechándose no son el mismo estado. Un contexto mayor todavía en formación puede cambiar antes de cerrar.

No se pudieron evaluar NIO: el playback fuente no tuvo señales con referencias de 15m verificables. Las compañías con pocas observaciones mantienen sus límites de muestra; no se trasladan los porcentajes de compañías más líquidas a ellas.

Limitaciones: IEX, ausencia de minutos finales de referencia, historial previo insuficiente, ajustes del proveedor y selección de casos completos. Los estados desconocidos no se cuentan como falta de volatilidad. Se analiza el precio a cierres de minuto, no el primer tick ni los retrocesos intraminuto. Los periodos recientes ya se exploraron antes y no son validación futura independiente.

La regla de 15m mantiene obligatoriamente ambas bandas abriéndose. Este estudio no modifica alertas, Telegram, órdenes, dashboard ni reglas de aprobación. Los resultados son apoyo para investigación, no garantía de continuidad.
