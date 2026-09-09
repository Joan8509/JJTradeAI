# Índices y ETF

Estado: `EN_PROCESO` — contexto documentado; datos dinámicos pendientes  
Categoría: `PANORAMA`  
Prioridad: `ALTA`  
Fuentes principales: `Estrategias/Indices.txt` y `Estrategias/Resumen.txt`

## Objetivo

Incorporar el comportamiento del índice, ETF y empresas componentes al panorama
del activo analizado.

## Relaciones principales documentadas

- SPX y su ETF SPY.
- Nasdaq-100 y su ETF QQQ.
- Russell 2000 y su ETF IWM.
- Dow Jones y su ETF DIA.

El índice es la referencia principal y el ETF replica su movimiento a un precio
distinto. La app debe analizar el instrumento principal adecuado y registrar
cuál contrato o ETF se pretende operar.

## Empresa frente a índice

La dirección de influencia depende del contexto:

- Una noticia macroeconómica afecta primero al índice y después a sus empresas.
- Una noticia corporativa puede mover el índice cuando la compañía tiene peso
  suficiente dentro de él.
- El movimiento mayoritario y las empresas de mayor ponderación determinan gran
  parte del comportamiento agregado.

## Uso dentro del panorama

- Comparar la dirección del activo con su índice y ETF relacionados.
- Revisar si las empresas de mayor peso acompañan el movimiento.
- Detectar movimientos coordinados o divergencias.
- Consultar calendario macroeconómico y eventos corporativos.
- Considerar CT15 y Saliendo desde Bollinger con Volatilidad como estrategias
  destacadas por la capacitación para movimientos rápidos en índices.

## Datos dinámicos obligatorios

- Composición y ponderación actual de cada índice.
- Calendario de noticias macroeconómicas.
- Earnings y noticias corporativas.
- Calendario vigente de expiraciones.
- Liquidez y cotizaciones actuales del contrato.

Estos datos no deben fijarse desde la transcripción porque cambian con el
tiempo. Si no están disponibles, la evaluación del contexto será
`NO_DISPONIBLE`.

## Regla crítica

La coincidencia con un índice aporta contexto, pero no crea una entrada. Una
estrategia individual sigue necesitando confirmaciones, invalidaciones y riesgo.

## Pendientes antes de programar

- Fuente autorizada y actualizada de componentes y pesos.
- Mapeo oficial símbolo–índice–ETF–inverso.
- Definición cuantitativa de acompañamiento y divergencia.
- Reglas de noticias que obligan a `NO_OPERAR`.

