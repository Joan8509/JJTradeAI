# Momentum de una Empresa

Estado: `IMPLEMENTADO_EN_BETA` — detector técnico objetivo con una revisión visual  
Categoría: `MOMENTUM`  
Prioridad: `ALTA`  
Fuente principal: `Estrategias/momemntum de una empresa.txt`

## Objetivo

Detectar el inicio de un movimiento fuerte y de mayor duración después de una
tendencia prolongada. El Momentum suele aparecer primero en Hora y puede
consolidarse posteriormente en Diario.

## Momentum alcista

1. Tendencia bajista prolongada previa.
2. En Hora, estructura de largo plazo bajista entre las medias 100 y 200.
3. Precio subiendo con fuerza y rompiendo 20 y 40 en Hora.
4. Cruce de 20 sobre 40 como confirmación formal adicional.
5. Ruptura de 100 y 200 en Hora.
6. Ruptura de 20 y 40 en Diario.
7. Punto Medio Diario virándose al alza.
8. Disipador superior Diario abriendo y volatilidad diaria expandiéndose.
9. Panorama sin techos cercanos que bloqueen el recorrido.

Sesgo metodológico: movimientos alcistas en opciones o activo principal.

## Momentum bajista

1. Tendencia alcista prolongada previa.
2. En Hora, estructura de largo plazo alcista entre las medias 100 y 200.
3. Precio cayendo con fuerza y rompiendo 20 y 40 en Hora.
4. Cruce de 20 bajo 40 como confirmación formal adicional.
5. Ruptura de 100 y 200 en Hora.
6. Ruptura de 20 y 40 en Diario.
7. Punto Medio Diario virándose a la baja.
8. Disipador inferior Diario abriendo y volatilidad diaria expandiéndose.
9. Panorama sin pisos cercanos que bloqueen el recorrido.

Sesgo metodológico: `PUT` en opciones o evaluación del activo inverso. El
análisis siempre se realiza sobre el activo principal.

## Regla crítica

La ruptura de medias móviles no confirma Momentum por sí sola. Sin apertura de
volatilidad en Diario, el escenario se considera falso Momentum y no debe
aprobarse.

## Confirmaciones adicionales

- Volumen Diario aumentando al abrirse la volatilidad.
- Alineación de Hora y Diario.
- Ruptura confirmada mediante vela cerrada.
- Ausencia de edge lines, techos o pisos cercanos.

El volumen es un plus; no sustituye la volatilidad diaria.

## Uso por horizonte

- Hora: seguimiento activo en opciones o activos.
- Diario: posible inversión de mayor duración.
- Una confirmación en Hora no garantiza que Momentum llegue a consolidarse en
  Diario.

## Invalidaciones

- Volatilidad diaria cerrada después de las rupturas.
- Punto Medio Diario sin acompañar la dirección.
- Ruptura intradía sin cierre confirmado.
- Piso o techo relevante inmediatamente cercano.
- Medias entrelazadas o panorama lateral.

## Contrato técnico implementado

`strategies/momentum.py` comprueba que el precio esté al lado direccional de
20/40/100/200 en Hora, de 20/40 en Diario, que el Punto Medio Diario acompañe
y que ambos disipadores diarios se expandan. Sin esta última condición no
detecta Momentum.

La transición se confirma exclusivamente con velas cerradas. La ruptura debe
haber comenzado dentro de las últimas 20 velas de Hora y cinco velas de Diario.
Antes de ella se exigen al menos 10 y hasta 20 velas: un 70 % debe mostrar la
tendencia diaria contraria y la estructura 100/200 horaria contraria. Estos
umbrales son conservadores, explícitos, auditables y deberán recalibrarse con
resultados PAPER, sin aprendizaje automático silencioso.

Solo el camino libre al siguiente nivel continúa como revisión manual, porque
las edge lines y niveles discrecionales de TC2000 no están presentes en el feed
de Alpaca. Se registran `MOMENTUM_ALCISTA` y `MOMENTUM_BAJISTA`.

## Pendientes antes de completar la automatización

- Tolerancias de ruptura para cada media y temporalidad.
- Número de velas requerido para apertura diaria confirmada.
- Definición de finalización de Momentum.
- Universo y relación de activos principales, ETF e inversos.
- Validar esta interpretación con Joan.
