# Revisión de AAPL y META: capturas y bloque 09:45–10:00 ET

Revisión realizada el 13 de octubre de 2026 después del cierre. El usuario
reportó movimientos con buena volatilidad en ambas compañías sin notificación.
El diagnóstico inicial no modificó reglas. La corrección posterior de META
se documenta a continuación. No se reenviaron señales históricas.

## Corrección implementada después del diagnóstico

La versión `v4_apertura_dentro_sin_veto_previo` retira el veto independiente
de cierre anterior fuera. Exige la apertura propia dentro de sus bandas, la
salida observada, avance desde apertura, punto medio alineado y ambas bandas
abriéndose. No agrega reingresos, tolerancias o aperturas exteriores aceptadas.
La regresión numérica de META reproduce la primera salida del minuto 09:45 y
verifica que una sola banda abierta siga sin producir señal. La geometría de
ticks prueba el cambio en ambos sentidos y las pruebas de saltos se conservan.
La configuración y comparación de AAPL con TC2000 continúan pendientes; esta
corrección no establece que su cálculo ya coincida con el gráfico del usuario.
La memoria de v3 devuelve VERSION_MISMATCH para observaciones nuevas de v4.
Los procesos existentes necesitan reinicio para cargar el cambio.
Validación: 790 pruebas del conjunto completo pasaron. El playback de los
minutos guardados de META genera ahora la señal superior de ese bloque en
la primera vela de minuto, con disponibilidad nominal a las 09:46 ET. Eso no
equivale a una entrega histórica real: la recepción registrada fue posterior
y el archivo no contiene ticks de esa mañana.

## Estado tras la corrección del usuario

El usuario aclara expresamente que AMBAS velas señaladas abrieron dentro en
TC2000. Por ello, la interpretación anterior de AAPL como salida tras volver
dentro no constituye una descripción validada del caso del usuario. La
reconstrucción numérica con Alpaca/SMA queda como diagnóstico del cálculo
actual de la app, no como prueba de que el gráfico TC2000 abrió fuera.

También se retira cualquier propuesta de modificar la estrategia para
aceptar aperturas exteriores a partir de estas capturas. El objetivo continúa
siendo detectar la apertura dentro y la salida con ambas bandas abriéndose.
Se solicitó tipo de media y desplazamiento del Bollinger TC2000 para comparar
configuración. SMA de las medias 20/40/100/200 no verifica automáticamente
los ajustes de este otro indicador. Si coinciden, habrá que contrastar los
cierres de referencia y valores de bandas, distinguiendo instantáneas de
apertura de bandas finales. Ninguna diferencia se atribuye aún con certeza
al feed, horario o fórmula.

META tiene un veto reproducible independiente: la apertura del bloque
señalado está dentro incluso con el cálculo actual, pero la regla también
exigía el cierre anterior dentro. Ese veto se retiró en la versión v4, según
la corrección documentada al principio.

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

Una reconstrucción local exploratoria separaba apertura dentro de una nueva
salida tras volver dentro. Esa variante no está aplicada al radar y ha quedado
superada por la aclaración del usuario sobre la apertura de ambas velas. La
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
los parámetros completos y la comparación de bandas de apertura.
Ninguna hipótesis se convierte aquí en un nuevo filtro o una aprobación de
operación. El profit reportado no se verifica sin las ejecuciones de opciones.
