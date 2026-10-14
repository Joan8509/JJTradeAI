# AAPL y META: vela identificada por el usuario como 10:00 AM en TC2000

Revisión del 13 de octubre de 2026. El usuario reporta una salida superior
con buena volatilidad en las velas señaladas con flechas verdes, sin aviso.

## Referencia vigente del usuario

La última aclaración es explícita: la vela de las 09:45 abrió fuera y la vela
de las 10:00 abrió dentro. El caso que se debe resolver es la vela identificada
por el usuario como 10:00 en TC2000. No debe clasificarse como una apertura
exterior ni cambiarse la estrategia para admitir reingresos a partir de este
caso. La apertura dentro seguida de salida con ambas bandas abriéndose sigue
siendo el objetivo.

La app etiqueta sus barras con el comienzo del intervalo. Las capturas tienen
flechas y secuencia de precios, pero no tooltip con la hora y OHLC de la vela
señalada. La equivalencia exacta entre esa etiqueta de TC2000 y el timestamp
Alpaca está pendiente. Se pidió el precio Open de META de esa vela para
identificarla sin discutir o reinterpretar el horario usado por el usuario.

Las conclusiones anteriores que equiparaban automáticamente las flechas con
un bloque 09:45-10:00, o con el bloque 10:00-10:15, quedan sin validar como
identificación del caso. Las reconstrucciones que siguen son evidencia del
cálculo local por timestamp, no prueba de la apertura de la vela de TC2000.

## Cálculo local disponible

Alpaca/IEX, sesión regular, Bollinger con media simple de 20 cierres,
desviación 2 y ddof=0. La apertura se compara con bandas recalculadas usando
19 cierres anteriores y el precio de apertura, sin el cierre futuro. Los
veinte minutos de cierre de referencia y la primera barra de cada bloque
revisado están guardados. Las marcas received_at corresponden a las versiones
almacenadas; no forman un historial completo de primeras llegadas/revisiones.

META, intervalo Alpaca que comienza 09:45 ET: apertura 751.31; bandas de
apertura 739.5856758637218 a 752.2988241362781. El cierre anterior es 751.63,
apenas sobre su banda superior 751.5113244385666. El primer cierre de minuto,
753.765, tiene salida superior, avance desde apertura, punto medio alineado y
ambas bandas abriéndose. La regla v3 lo vetaba por el cierre anterior fuera.

AAPL, intervalo Alpaca que comienza 09:45 ET: apertura 342.09; banda superior
de apertura 341.7061765669357. La interpretación exploratoria de reingreso no
es una descripción validada del caso del usuario ni una regla activa.

Para el intervalo Alpaca que comienza 10:00 ET, las aperturas guardadas son
345.08 en AAPL y 768.91 en META. Las bandas superiores calculadas a esas
aperturas son 343.8413168523237 y 763.3656068646371, respectivamente. La
diferencia respecto de la observación del usuario requiere alinear primero
la vela y después comparar la configuración y los cierres de referencia.
No se atribuye todavía a fórmula, feed u horario con certeza.

No hay eventos detectados ni intentos de envío de AAPL o META el 13 de octubre.
Otros símbolos registran 70 envíos, sin confirmar recepción en el teléfono.
El archivo local no contiene ticks de esa mañana. El flujo rápido se activó
a las 21:09 ET, después de estos movimientos.

## Cambio implementado y alcance de la validación

La versión v4_apertura_dentro_sin_veto_previo elimina el veto de cierre
anterior fuera. Sigue exigiendo apertura propia dentro, salida del precio,
avance desde apertura, punto medio alineado y apertura de ambas bandas.
No agrega tolerancias, aperturas exteriores aceptadas ni bandas futuras.

Pasaron 790 pruebas, incluidos ambos sentidos, saltos excluidos, ambas bandas
obligatorias, deduplicación y regresión con los precios guardados de META.
El playback reconoce ahora el bloque Alpaca que comienza 09:45 en META a
partir de su primer minuto completo (disponibilidad nominal 09:46). Esto prueba
el cambio de regla, pero no verifica todavía la vela denominada 10:00 por el
usuario ni confirma una entrega histórica de Telegram.

El radar se reinició con v4. El buscador que se inició antes del cambio
requiere reinicio para cargarla. Las memorias descriptivas de v3 no se aplican
a nuevas observaciones de v4 hasta reconstruirlas con la misma regla.

## Comparación pendiente

Identificar Open/O y timestamp de la vela 10:00 en TC2000. Contrastar los
parámetros completos de Bollinger (20/2 es visible; tipo de media y fuente
no están verificados) y los valores de bandas con los mismos cierres. La
corrección del veto anterior no demuestra por sí sola equivalencia con TC2000
ni precisión futura. No se han enviado órdenes ni señales históricas.

Fuente de fórmula y parámetros consultada el 13/10/2026:
[TC2000 Bollinger Bands](https://help.tc2000.com/m/69404/l/744931-bollinger-bands).
