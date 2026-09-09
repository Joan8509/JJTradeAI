# Salto de Lateralidad en Hora

Estado: `IMPLEMENTADO_EN_BETA` — geometría objetiva; noticias y camino externos  
Categoría: `PRIMER_SALTO`  
Prioridad: `ALTA`  
Fuentes principales:
- `clases de soporte(repaso).txt`
- `Estrategias/saltos.txt`
- `docs/strategies/PRIMER_SALTO.md`

## Objetivo

Identificar una estructura de continuidad donde el precio viene de una
tendencia previa, descansa en una lateralidad de Hora y rompe esa lateralidad
por una vela de confirmación o por un salto.

La estrategia solo estima dirección probable de continuidad. No estima tamaño
del salto ni garantiza que el movimiento intradía posterior sea amplio.

## Temporalidad

La clase nueva recalca que esta estrategia se revisa en `Hora`. El panorama
completo sigue siendo obligatorio:

- medias móviles en Hora y Diario;
- volatilidad en 15m, Hora y Diario;
- techos, pisos y espacio libre;
- noticias corporativas o macroeconómicas.

## Variante alcista

1. Tendencia previa alcista de al menos cinco registros de Hora.
2. Lateralidad previa de al menos diez registros de Hora.
3. Precio por encima de MA20 y MA40, con MA20 sobre MA40, actuando como piso.
4. Ruptura de la lateralidad al alza mediante salto o vela cerrada de Hora.
5. Precio idealmente cercano a MA20 de Hora antes de la ruptura.
6. Volatilidad acompañando la dirección alcista.
7. Sin noticia invalidante al día siguiente.
8. Camino libre hasta el siguiente techo relevante.

## Variante bajista

1. Tendencia previa bajista de al menos cinco registros de Hora.
2. Lateralidad previa de al menos diez registros de Hora.
3. Precio por debajo de MA20 y MA40, con MA20 bajo MA40, actuando como techo.
4. Ruptura de la lateralidad a la baja mediante salto o vela cerrada de Hora.
5. Precio idealmente cercano a MA20 de Hora antes de la ruptura.
6. Volatilidad acompañando la dirección bajista.
7. Sin noticia invalidante al día siguiente.
8. Camino libre hasta el siguiente piso relevante.

## Reglas interpretadas

- Un salto tiene más peso que una sola vela de Hora porque cubre más tiempo
  entre cierre y apertura.
- Una vela cerrada de Hora también puede confirmar la ruptura si rompe el canal.
- La lateralidad no exige que MA100 y MA200 estén dentro del canal; eso pertenece
  a otra estructura como `Canal del Millón`.
- Si el precio queda demasiado lejos de MA20 de Hora, aumenta el riesgo de
  retroceso por Efecto Imán.
- Earnings, splits y noticias macro fuertes pueden invalidar la continuidad.
- Un `even price` después de un salto reinicia el conteo: el siguiente salto ya
  no debe tratarse como segundo, tercero o cuarto salto de la misma secuencia.

## Contrato técnico implementado

`strategies/salto_lateralidad_hora.py` implementa evidencia objetiva:

- exige al menos 16 registros de Hora: 5 de tendencia previa, 10 de lateralidad
  y 1 registro evaluado;
- mide la dirección de la tendencia previa por cierre inicial/final;
- valida relación precio/MA20/MA40 como piso o techo;
- define el canal con diez velas, ancho máximo de 2 % y pendiente normalizada
  máxima de 0.05 % por vela;
- confirma ruptura cuando la apertura o el cierre supera el máximo/mínimo del
  canal;
- exige que la distancia previa a MA20 no supere el ancho del canal;
- exige disipador superior subiendo e inferior bajando en la vela cerrada;
- conserva noticias y camino libre como compuertas externas.

Identificadores registrados:

- `SALTO_LATERALIDAD_HORA_ALCISTA`
- `SALTO_LATERALIDAD_HORA_BAJISTA`

## Revisiones manuales

- `lateral_jump.path_clear`
- `common.news_clear`

Mientras falte cualquier revisión obligatoria, la estrategia puede aparecer en
el radar como detectada, pero no puede confirmar una entrada ni superar la
decisión final.

## Pendientes antes de automatizar más

- Catálogo de noticias invalidantes por símbolo, fecha y severidad.
- Separación formal entre primer, segundo y saltos posteriores cuando aparece
  `even price`.
