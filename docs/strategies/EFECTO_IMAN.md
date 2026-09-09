# Efecto Imán

Estado: `EN_PROCESO` — detector técnico parcial implementado; pendiente de validación por Joan  
Categoría: `PUNTO_MEDIO`  
Prioridad: `ALTA`  
Fuente principal: `Estrategias/efecto iman.txt`  
Fuente: Metodología Investep enviada por Joan

## Objetivo

Detectar una sobreextensión producida por un salto anormalmente alejado de la
media móvil de 20 períodos en hora y buscar el retroceso del precio hacia esa
media, que funciona como imán.

La estrategia combina medias móviles de 20 y 40 en hora, Bollinger en 15
minutos y volumen Worden Stochastics en hora.

## Efecto Imán en tendencia alcista

Sesgo esperado: retroceso bajista hacia la media móvil de 20 en hora.

Requisitos extraídos:

1. Tendencia claramente alcista en hora, determinada principalmente por las
   medias móviles de 20 y 40.
2. La tendencia debe llevar al menos dos días; mientras más días, mayor fuerza
   metodológica.
3. Salto fuerte al alza que deje el precio anormalmente alejado de la media
   móvil de 20 en hora: distancia actual igual o superior al percentil 90 de
   los máximos diarios de las últimas 60 sesiones del mismo activo.
4. La primera vela de 15 minutos debe terminar completamente por fuera de
   Bollinger, sin tocar el disipador superior.
5. Al comenzar la segunda vela de 15 minutos, el volumen de hora debe haber
   cruzado la línea roja de Worden Stochastics.
6. El trayecto desde el precio hasta la media móvil de 20 en hora debe estar
   limpio, sin otras medias móviles que puedan frenar el retroceso.

El sesgo indicado en la clase es `PUT` hacia la media móvil de 20 en hora, pero
JJTrade AI deberá conservarlo como sesgo hasta completar panorama y riesgo.

## Efecto Imán en tendencia bajista

Sesgo esperado: retroceso alcista hacia la media móvil de 20 en hora.

Requisitos extraídos:

1. Tendencia claramente bajista en hora, determinada principalmente por las
   medias móviles de 20 y 40.
2. La tendencia debe llevar al menos dos días; mientras más días, mayor fuerza
   metodológica.
3. Salto fuerte a la baja que deje el precio anormalmente alejado de la media
   móvil de 20 en hora: distancia actual igual o superior al percentil 90 de
   los máximos diarios de las últimas 60 sesiones del mismo activo.
4. La primera vela de 15 minutos debe terminar completamente por fuera de
   Bollinger, sin tocar el disipador inferior.
5. Al comenzar la segunda vela de 15 minutos, el volumen de hora debe haber
   cruzado la línea roja de Worden Stochastics.
6. El trayecto desde el precio hasta la media móvil de 20 en hora debe estar
   limpio, sin otras medias móviles que puedan frenar el retroceso.

El sesgo indicado en la clase es `CALL` hacia la media móvil de 20 en hora, pero
JJTrade AI deberá conservarlo como sesgo hasta completar panorama y riesgo.

## Confirmaciones adicionales

- Exposición simultánea en Bollinger de hora.
- Exposición simultánea en Bollinger de Diario.
- Más temporalidades expuestas aportan mayor respaldo al retroceso.
- Mayor número de días sin tocar la media móvil de 20 puede fortalecer el
  efecto imán.

## Invalidaciones y condiciones de descarte

- Tendencia lateral.
- Medias móviles de 20 y 40 entrelazadas o apenas cruzándose.
- Otras medias móviles atravesadas entre el precio y la media móvil de 20.
- Primera vela de 15 minutos tocando o entrando nuevamente en Bollinger.
- Volumen de hora sin cruzar la línea roja de Worden Stochastics al comenzar la
  segunda vela de 15 minutos.
- Salto cuya distancia sea normal para el comportamiento histórico del activo.

## Temporalidad y momento de evaluación

- Tendencia y objetivo: hora.
- Exposición inicial: primera vela cerrada de 15 minutos.
- Confirmación final del detector: inicio de la segunda vela de 15 minutos.
- Objetivo metodológico mínimo mencionado: acercamiento a la media móvil de 20
  en hora.

## Pendientes antes de completar la automatización

- Precisar el cálculo y umbral del cruce de volumen Worden.
- Validar si el camino limpio debe revisar otras temporalidades además de las
  medias móviles exportadas en Hora.
- Formalizar el tiempo máximo permitido para alcanzar el objetivo.
- Validar esta interpretación con Joan.

## Contrato técnico implementado

El módulo `strategies/efecto_iman.py` combina las tres temporalidades y puede:

- medir el salto de la sesión diaria;
- verificar el orden de las medias 20 y 40 en la primera vela de Hora;
- inferir tendencia clara de Hora cuando existen al menos dos sesiones horarias,
  exigiendo orden 20/40, precio alineado con MA20 y pendiente de MA20 en la
  dirección del salto;
- medir la distancia porcentual entre el precio y MA20 de Hora;
- comparar esa distancia con el percentil 90 de los máximos diarios de hasta
  60 sesiones anteriores del mismo activo, exigiendo un mínimo de 20 sesiones;
- revisar camino limpio hacia MA20 de Hora usando MA40, MA100 y MA200 cuando
  esas columnas existen en la exportación;
- comprobar que la primera vela de 15m quedó completamente fuera de Bollinger,
  sin tocar el disipador;
- comprobar que comenzó la segunda vela de 15m.

Identificadores registrados:

- `EFECTO_IMAN_TENDENCIA_ALCISTA`, con sesgo inicial `PUT` hacia MA20 de Hora;
- `EFECTO_IMAN_TENDENCIA_BAJISTA`, con sesgo inicial `CALL` hacia MA20 de Hora.

La anormalidad del salto queda automatizada con la regla adaptativa autorizada
por Joan; con menos de 20 sesiones válidas permanece `NO_DISPONIBLE`. El cruce
de volumen Worden sigue como revisión obligatoria. Si no hay al menos dos sesiones horarias disponibles,
la claridad y duración de la tendencia también queda como revisión obligatoria.
Si faltan medias móviles adicionales en Hora, el camino limpio también queda
pendiente de revisión. La exportación actual solo contiene el valor de Worden
Stochastics, no la serie de su línea roja; por tanto, la aplicación no inventa
ese cruce.

Detectar la geometría objetiva de Efecto Imán no constituye una entrada final.

## Notas

La clase menciona rentabilidades históricas como ejemplos educativos. Esos
porcentajes no forman parte de los requisitos del detector ni constituyen una
promesa para JJTrade AI.
