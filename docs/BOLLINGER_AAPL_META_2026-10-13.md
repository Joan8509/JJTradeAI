# Revisión de AAPL y META: capturas y bloque 09:45–10:00 ET

Revisión realizada el 13 de octubre de 2026 después del cierre. El usuario
reportó movimientos con buena volatilidad en ambas compañías sin notificación.
No se modificaron reglas de entrada ni se reenviaron señales históricas.

## Corrección después de recibir las capturas

Las flechas del gráfico de 15 minutos apuntan a la segunda vela de la sesión,
no a la tercera. La secuencia y los OHLC coinciden con el bloque 09:45–10:00
de Alpaca. Esta alineación se infiere de precios y posición; las capturas no
incluyen un tooltip con el timestamp de la vela. El análisis inicial que
figura más abajo revisó el bloque siguiente, 10:00–10:15, y no debe confundirse
con las velas señaladas por el usuario.

META, bloque 09:45–10:00: abre en 751.31, dentro de las bandas calculadas a
esa apertura (739.5856758637218–752.2988241362781). El veto procede del cierre
anterior 751.63, apenas por encima de su banda superior 751.5113244385666.
El cierre de minuto de las 09:45 ya muestra salida superior, avance desde
la apertura, punto medio alineado y ambas bandas abriéndose.

AAPL, mismo bloque: abre en 342.09 frente a banda superior de apertura
341.7061765669357. Además, el cierre anterior 342.115 ya estaba fuera.
El mínimo del minuto de las 09:46 es 341.12: al recalcular las bandas con
ese precio resulta dentro. Desde el cierre de las 09:47 hay precio superior
expuesto, avance desde la apertura, punto medio alineado y ambas bandas
abriéndose. OHLC evidencia el regreso dentro durante ese minuto, pero no
permite identificar el segundo exacto ni reconstruir todos los cruces.

Los minutos de las 09:45–09:48 de AAPL registran recepción a las
09:52:24.934755; los de META a las 09:51:51.482805. También había una demora
importante en el sistema antiguo. Son marcas de la versión almacenada, no
un historial completo de primeras recepciones y correcciones.

Una reconstrucción local exploratoria separa apertura dentro de una nueva
salida tras volver dentro. Esa variante no está aplicada al radar. Hace falta
definir si el segundo escenario pertenece a la estrategia solicitada. La
apertura de ambas bandas permanece obligatoria en los escenarios evaluados;
el gráfico estático final no sustituye los precios disponibles en tiempo real.

Fuente primaria de fórmula y parámetros Bollinger, consultada el 13/10/2026:
[TC2000 Bollinger Bands](https://help.tc2000.com/m/69404/l/744931-bollinger-bands).
TC2000 admite distintos tipos de media y desplazamientos. La leyenda 20/2
visible no verifica por sí sola todos los ajustes ni la igualdad de feeds.

## Análisis inicial del bloque siguiente: 10:00–10:15

Se reconstruyeron las velas de las 09:30, 09:45 y 10:00 con las barras locales
Alpaca/IEX, sesión regular, Bollinger de 20 cierres y dos desviaciones estándar
poblacionales. Las veinte velas anteriores a cada bloque tienen su minuto de
cierre oficial y el primer minuto de cada bloque está guardado. La revisión
usa la versión final almacenada de las barras; no reconstruye sus revisiones
ni el orden de los ticks que ocurrieron durante la sesión.

Para AAPL a las 10:00, la apertura guardada es 345.08 y la banda superior
recalculada a esa apertura es 343.8413168523237. La vela anterior cerró en
345.11, por encima de su banda superior 342.84448837657123.

Para META a las 10:00, la apertura guardada es 768.91 y la banda superior
recalculada a esa apertura es 763.3656068646371. La vela anterior cerró en
769.64, por encima de su banda superior 758.8420829566518.

En AAPL, los quince cierres de minuto de la vela de las 10:00 están por encima
de la banda superior y muestran ambas bandas abriéndose frente a la vela
anterior. En META, catorce de los quince cierres cumplen esas dos propiedades;
el cierre de las 10:13 está dentro. Estas propiedades solas no cumplen toda
la regla actual: ambas aperturas y ambos cierres anteriores están fuera.

No existen eventos detectados ni intentos de notificación de estas compañías
el 13 de octubre. El registro del día contiene 70 notificaciones enviadas a
otras compañías. No es evidencia de recepción en el teléfono.

Los minutos guardados de las 10:00 registran recepción a las 10:01:46.656903
para AAPL y 10:02:13.105996 para META. Son marcas almacenadas de recepción;
sin un historial de versiones no identifican necesariamente la primera llegada.
No se dispone de ticks históricos de esa mañana en el archivo local.

## Interpretación y seguimiento

La reconstrucción con los datos finales descarta las dos velas por las reglas
de apertura dentro y cierre anterior dentro, pese a la apertura de ambas
bandas. Esta exclusión abarca continuaciones sin un gran salto entre cierre
y apertura: no demuestra por sí misma que haya ocurrido un gap de precio.
El flujo rápido fue activado a las 21:09 ET, después de estos movimientos.
Su activación no cambia esas reglas geométricas.

Las capturas posteriores permiten alinear las velas señaladas y la dirección
superior, según la corrección al principio del documento. Quedan pendientes
los parámetros completos y la definición de salida tras volver dentro.
Ninguna hipótesis se convierte aquí en un nuevo filtro o una aprobación de
operación. El profit reportado no se verifica sin las ejecuciones de opciones.
