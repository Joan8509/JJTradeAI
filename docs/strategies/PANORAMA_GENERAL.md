# Panorama General Multi-temporal

Estado: `EN_PROCESO` — resumen técnico y compuerta manual implementados  
Categoría: `PANORAMA`  
Prioridad: `ALTA`  
Fuente: Metodología Investep enviada por Joan

## Objetivo

Evaluar si una estrategia detectada dispone de dirección y espacio suficientes
para desarrollarse, considerando temporalidades y niveles que puedan favorecer
o bloquear el movimiento.

## Temporalidades principales

- 15 minutos: anticipación y movimientos rápidos.
- Hora: confirmación intermedia y estructura operativa.
- Diario: contexto de mayor peso.
- Semanal y Mensual: contexto de largo plazo cuando sea relevante.

## Componentes mínimos

- Dirección del Punto Medio en 15m, Hora y Diario.
- Estado de volatilidad en 15m, Hora y Diario.
- Posición del precio dentro o fuera de Bollinger.
- Medias móviles de 20, 40, 100 y 200.
- Máximos, mínimos, soportes, resistencias y líneas relevantes.
- Distancia hasta el siguiente techo o piso.
- Noticias corporativas o macroeconómicas relevantes.

## Reglas de jerarquía

- Diario pesa más que Hora y Hora pesa más que 15m.
- Una temporalidad inferior puede anticipar, pero no reemplaza el contexto de
  una superior.
- Una estrategia válida puede convertirse en `NO_OPERAR` si existe un nivel
  cercano que limita el recorrido.
- La aprobación humana no anula conflictos direccionales entre temporalidades.
- Cuando el precio está encerrado entre piso y techo, se prefiere no operar.
- El mejor panorama es el que presenta camino limpio en la dirección esperada.

## Salida esperada

El panorama no genera una estrategia. Debe producir:

- Dirección dominante.
- Conflictos entre temporalidades.
- Techos y pisos cercanos.
- Espacio disponible.
- Estado: `FAVORABLE`, `MIXTO`, `DESFAVORABLE` o `NO_DISPONIBLE`.
- Motivos y fuentes de cada evaluación.

## Implementación actual

`panorama_engine.py` presenta por temporalidad el cierre, orden MA20/MA40,
posición frente a Bollinger y apertura de volatilidad. También muestra
conflictos, pero no asigna pesos artificiales. Para aprobar la compuerta exige
15m, Hora y Diario, ausencia de conflictos direccionales, camino libre,
calendario revisado y aprobación humana.

## Pendientes antes de completar la automatización

- Definir pesos cuantitativos por temporalidad.
- Definir distancia mínima aceptable hasta techos y pisos.
- Normalizar soportes, resistencias y líneas dibujadas manualmente.
- Integrar un calendario confiable de noticias.
- Validar reglas de conflicto y prioridad con Joan.
