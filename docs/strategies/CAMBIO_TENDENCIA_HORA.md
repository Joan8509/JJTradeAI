# Cambio de Tendencia en Hora

Estado: `IMPLEMENTADO_EN_BETA` — detector multitemporal objetivo  
Categoría: `CAMBIO_TENDENCIA`  
Prioridad: `ALTA`  
Fuentes principales:  
- `Estrategias/cambio de tendencia en hora.txt`  
- `Estrategias/Cambio Tendencia en hora a la baja.txt`  
Fuente: Metodología Investep enviada por Joan

## Objetivo

Detectar un cambio confirmado de tendencia en la temporalidad de Hora mediante
la ruptura de la línea de tendencia y el Punto Medio de Bollinger, con
alineación posterior en 15 minutos.

Esta estrategia solo cambia entre tendencia alcista y bajista. Una transición
desde lateralidad no corresponde a Cambio de Tendencia en Hora.

## Variante alcista

Sesgo esperado: `CALL_CAMBIO_TENDENCIA_HORA`.

1. Tendencia claramente bajista en Bollinger de Hora, con mínimo dos días.
2. Línea de tendencia trazada por la parte alta, bordeando la mayor cantidad de
   puntos posibles.
3. Ruptura alcista de la línea de tendencia.
4. Ruptura alcista del Punto Medio de Hora.
5. Si la ruptura ocurre durante el mercado, esperar una vela de Hora cerrada
   completamente alcista por encima de ambos niveles.
6. En 15 minutos, la tendencia debe mostrarse claramente alcista.

## Variante bajista

Sesgo esperado: `PUT_CAMBIO_TENDENCIA_HORA`.

1. Tendencia claramente alcista en Bollinger de Hora, con mínimo dos días.
2. Línea de tendencia trazada por la parte baja, bordeando la mayor cantidad de
   puntos posibles.
3. Ruptura bajista de la línea de tendencia.
4. Ruptura bajista del Punto Medio de Hora.
5. Si la ruptura ocurre durante el mercado, esperar una vela de Hora cerrada
   completamente bajista por debajo de ambos niveles.
6. En 15 minutos, la tendencia debe mostrarse claramente bajista.

## Confirmación mediante salto

Cuando un salto de apertura rompe simultáneamente la línea de tendencia y el
Punto Medio de Hora en la dirección esperada, el salto funciona como
confirmación y no es necesario esperar el cierre de una vela adicional de Hora.

Si el salto no rompe ambos niveles, continúa siendo obligatoria una vela de
Hora cerrada que confirme las dos rupturas.

## Confirmaciones adicionales

- Buena separación entre los disipadores de Hora.
- Apertura de volatilidad en Hora; es un plus, no un requisito obligatorio.
- Salida desde Bollinger con fuerza y volatilidad en 15 minutos.
- Punto Medio de 15 minutos claramente inclinado en la dirección nueva.
- Camino limpio hasta el siguiente techo o piso relevante.

## Invalidaciones y condiciones de descarte

- Punto Medio de Hora lateral.
- Tendencia previa menor al mínimo requerido.
- Vela de Hora todavía en formación.
- Vela que cruza temporalmente y cierra nuevamente sin confirmar la ruptura.
- Salto que no rompe simultáneamente línea y Punto Medio, sin confirmación
  posterior cerrada.
- Tendencia de 15 minutos no alineada con la nueva dirección.
- Lateralidad general o medias cercanas que dejan el movimiento sin espacio.

## Panorama y objetivos

La media móvil de 40 u otro techo/piso cercano puede limitar el recorrido. La
distancia hasta ese nivel pertenece al panorama y puede convertir una detección
correcta en `NO_OPERAR` si no existe espacio suficiente.

## Contrato técnico implementado

`strategies/cambio_tendencia_hora.py` detecta el cruce del Punto Medio entre
dos velas de Hora. Evalúa 13 velas previas —dos sesiones regulares— y exige que
al menos 70 % permanezca del lado anterior del Punto Medio, con pendiente de
cierres compatible. Ajusta una línea sobre máximos para la variante alcista o
 mínimos para la bajista y proyecta su valor hasta la vela de ruptura.

El feed entrega únicamente velas horarias cerradas. La confirmación normal
exige cerrar más allá de la línea y del Punto Medio; una apertura más allá de
ambos se identifica objetivamente como salto confirmatorio. El último 15m debe
cerrar del lado nuevo con pendiente del Punto Medio alineada.

Se registran `CAMBIO_TENDENCIA_HORA_ALCISTA` y
`CAMBIO_TENDENCIA_HORA_BAJISTA`. Los argumentos manuales permanecen únicamente
como compatibilidad interna para archivos históricos y no aparecen en el flujo
en vivo.

## Pendientes antes de completar la automatización

- Precisar qué significa una vela “totalmente” direccional.
- Establecer tolerancias de ruptura y cierre respecto de los niveles.
- Definir el espacio mínimo hasta el siguiente techo o piso.
- Validar esta interpretación con Joan.

## Notas

Los porcentajes de rentabilidad mencionados en la capacitación son ejemplos
educativos y no forman parte del detector ni constituyen una promesa.
