# Techos y Pisos por Medias Móviles

Estado: `EN_PROCESO` — mapa geométrico implementado  
Categoría: `PANORAMA`  
Prioridad: `ALTA`  
Fuente principal: `Intensivo y Basico/Medias moviles.txt`

## Medias utilizadas

- 20 y 40 como primer par.
- 100 y 200 como segundo par.
- Peso relativo ascendente: 20, 40, 100 y 200.
- Temporalidades principales: Hora y Diario.

## Tendencia

- 20 sobre 40: tendencia alcista del primer par.
- 40 sobre 20: tendencia bajista del primer par.
- 100 sobre 200: tendencia alcista del segundo par.
- 200 sobre 100: tendencia bajista del segundo par.
- Medias entrelazadas y cruces repetidos: lateralidad.

El conteo comienza desde el cruce. La clase exige como mínimo dos días para
validar tendencia y describe:

- 2 a 5 días: corto plazo.
- 5 a 15 días: mediano plazo.
- Más de 15 días: largo plazo.

Mayor separación entre las medias representa una tendencia más saludable.

## Pisos y techos

En tendencia alcista:

- Precio aproximándose desde arriba: la media puede actuar como piso.
- Precio avanzando desde abajo hacia arriba: continuidad, no techo.

En tendencia bajista:

- Precio aproximándose desde abajo: la media puede actuar como techo.
- Precio avanzando desde arriba hacia abajo: continuidad, no piso.

## Confirmación

Un toque no confirma el rebote. Debe esperarse una vela cerrada de Hora:

- Alcista para confirmar rebote desde un piso.
- Bajista para confirmar rechazo desde un techo.
- Direccional más allá del nivel para confirmar ruptura.

El primer acercamiento suele tener más peso; rebotes repetidos debilitan el
nivel. Esta relación deberá validarse y cuantificarse antes de programar.

## Uso en panorama

Las medias cercanas pueden limitar una estrategia aunque el detector sea
correcto. Deben evaluarse tanto en Hora como en Diario y marcarse como niveles
de bloqueo o espacio disponible.

## Implementación actual

`levels_engine.py` reúne las medias 20/40/100/200 de 15m, Hora y Diario,
calcula su distancia absoluta y porcentual, y marca cuáles se encuentran por
delante del sesgo evaluado. Esta es una medición geométrica: no afirma que toda
media sea automáticamente techo o piso ni que exista espacio suficiente.

## Pendientes antes de completar la automatización

- Tolerancia de toque, ruptura y cierre.
- Separación mínima para tendencia saludable.
- Definición cuantitativa de lateralidad y cruces repetidos.
- Conteo y debilitamiento por número de rebotes.
- Espacio mínimo necesario hasta la siguiente media.
