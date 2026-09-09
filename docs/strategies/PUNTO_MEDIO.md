# Punto Medio

Estado: `EN_PROCESO` — componente documentado; reglas cuantitativas pendientes  
Categoría: `PUNTO_MEDIO`  
Prioridad: `ALTA`  
Fuentes principales: `Bollinguer 1.txt`, `Bollinguer2.txt` y clases de estrategias

## Definición

Punto Medio es la línea central de Bollinger y corresponde a la media móvil de
20 períodos en la temporalidad observada.

## Funciones dentro del motor

- Indicar tendencia alcista, bajista o lateral según su inclinación.
- Actuar como posible piso cuando está alcista y el precio llega desde arriba.
- Actuar como posible techo cuando está bajista y el precio llega desde abajo.
- Confirmar dirección cuando acompaña una apertura de volatilidad.
- Servir como nivel de ruptura en cambios de tendencia.

## Regla crítica

Punto Medio no confirma rebote o ruptura por sí solo. Debe combinarse con vela
cerrada, volatilidad, contexto y niveles del panorama.

## Pendientes antes de programar

- Pendiente mínima para clasificar dirección.
- Tolerancia de toque y ruptura.
- Número de velas usado para confirmar lateralidad.
- Reglas de conflicto entre temporalidades.

