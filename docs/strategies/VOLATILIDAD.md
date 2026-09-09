# Volatilidad

Estado: `EN_PROCESO` — pendiente de validación por Joan  
Categoría: `VOLATILIDAD`  
Prioridad: `ALTA`  
Fuentes principales: `Bollinguer 1.txt`, `Bollinguer2.txt` y `Volumen.txt`

## Objetivo

Medir la fuerza disponible para un movimiento mediante la separación y
expansión de los disipadores de Bollinger.

## Estados metodológicos

- `ABIERTA`: ambos disipadores se expanden simultáneamente.
- `CERRADA`: disipadores estrechos o cerrándose.
- `FRACTURADA`: una expansión previa deja de sostenerse.
- `ENGAÑOSA`: los disipadores abren y cierran repetidamente sin expansión
  sostenida.
- `NO_DISPONIBLE`: datos insuficientes para clasificar.

## Reglas documentales

- Mayor apertura implica mayor fuerza potencial.
- Punto Medio debe acompañar la dirección del movimiento.
- Movimiento del precio sin apertura de volatilidad puede ser engañoso.
- La volatilidad es cíclica: períodos bajos suelen preceder períodos altos.
- El cierre de volatilidad indica pérdida de fuerza.
- Volumen alto sin volatilidad no confirma una entrada.
- Volumen y volatilidad alineados constituyen confirmación adicional.

## Temporalidades

La volatilidad se evalúa en 15m, Hora y Diario. Diario tiene más peso, pero 15m
reacciona antes y es la referencia principal para movimientos rápidos.

## Pendientes antes de programar

- Umbral de ancho relativo por símbolo y temporalidad.
- Número de velas requerido para confirmar expansión sostenida.
- Definición matemática de fractura y volatilidad engañosa.
- Normalización por precio y comportamiento histórico del activo.

