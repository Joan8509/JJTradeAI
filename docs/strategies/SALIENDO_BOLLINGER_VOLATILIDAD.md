# Tendencia Lateral: Precio Fuera de Bollinger en 15 Minutos

Estado: `IMPLEMENTADO_EN_BETA` — historial y reversión de cinco minutos objetivos  
Nombre de inventario: Saliendo de Bollinger con Volatilidad  
Categoría: `BOLLINGER` / `VOLATILIDAD`  
Prioridad: `ALTA`  
Fuente principal: `Estrategias/Salida de Bollinguer con Volatilidad.txt`  
Fuente: Metodología Investep enviada por Joan

## Objetivo

Detectar la reversión rápida hacia Bollinger después de que un salto de apertura
deje el precio excepcionalmente alejado de un oscilador que había cerrado
lateral y sin volatilidad el día anterior.

La capacitación denomina esta estrategia “Tendencia Lateral Precio Fuera de
Bollinger, marco de tiempo 15 minutos”. El nombre definitivo dentro de JJTrade
AI debe validarse antes de registrarla.

## Variante alcista

Sesgo esperado: `CALL_RETORNO_BOLLINGER`.

1. Al cierre anterior, Punto Medio de 15 minutos totalmente lateral.
2. Al cierre anterior, Bollinger de 15 minutos sin volatilidad.
3. Apertura con salto fuerte a la baja.
4. Precio excepcionalmente alejado del disipador inferior, comparado con los
   saltos habituales del activo.
5. Durante los primeros minutos, el precio comienza a subir con fuerza hacia el
   disipador inferior.
6. La volatilidad que pueda abrirse por el salto debe comenzar a cerrarse a
   medida que el precio revierte.

## Variante bajista

Sesgo esperado: `PUT_RETORNO_BOLLINGER`.

1. Al cierre anterior, Punto Medio de 15 minutos totalmente lateral.
2. Al cierre anterior, Bollinger de 15 minutos sin volatilidad.
3. Apertura con salto fuerte al alza.
4. Precio excepcionalmente alejado del disipador superior, comparado con los
   saltos habituales del activo.
5. Durante los primeros minutos, el precio comienza a bajar con fuerza hacia el
   disipador superior.
6. La volatilidad que pueda abrirse por el salto debe comenzar a cerrarse a
   medida que el precio revierte.

## Momento de evaluación

- Temporalidad metodológica: 15 minutos.
- Preparación: revisar el premarket pocos minutos antes de la apertura.
- Confirmación: observar la dirección de la reversión después de abrir.
- Ventana mencionada para la oportunidad: primeros cinco minutos del mercado.

## Invalidaciones y falsos escenarios

- Punto Medio inclinado al alza o a la baja al cierre anterior.
- Volatilidad abierta al cierre anterior.
- Salto de tamaño normal o pequeño para el activo.
- Ausencia de reversión inmediata hacia Bollinger.
- Volatilidad permaneciendo abierta mientras el precio se aproxima al
  disipador; esto puede representar continuidad y no la estrategia descrita.
- Interpretar cualquier exposición con retroceso como esta estrategia sin
  verificar lateralidad y ausencia de volatilidad previas.

## Riesgo de ejecución

La capacitación advierte que inmediatamente después de abrir puede existir una
diferencia bid/ask anormal. Debe esperarse la actualización de precios y nunca
entrar con un spread excesivo. Esta regla pertenece a la capa de riesgo y puede
convertir una detección válida en `NO_OPERAR`.

## Objetivo metodológico

El primer objetivo descrito es el disipador más cercano. El precio puede
continuar hacia Punto Medio o el disipador opuesto, pero la clase afirma que no
existe forma de conocerlo anticipadamente. La app no debe proyectar esos
objetivos adicionales como certezas.

## Decisión de taxonomía técnica

Para evitar confundir reversión con continuidad, esta variante se registra
como `RETORNO_BOLLINGER_LATERAL_ALCISTA` o
`RETORNO_BOLLINGER_LATERAL_BAJISTA`. El nombre histórico del inventario se
conserva como referencia, pero no determina el comportamiento del detector.

`strategies/retorno_bollinger_lateral.py` comprueba el salto fuera del
disipador, la dirección de la primera vela y el cierre de ambos disipadores.
La lateralidad usa ocho Puntos Medios y una pendiente normalizada máxima de
0.03 % por vela. La compresión exige un ancho situado en o por debajo del
percentil 25 de entre 20 y 60 observaciones anteriores. La excepcionalidad del
salto exige alcanzar el percentil 90 de entre 20 y 60 aperturas históricas del
propio símbolo. Si falta historial, el criterio queda `NO_DISPONIBLE`.

La reacción usa cinco barras auxiliares cerradas de 1 minuto suministradas por
Alpaca. Exige al menos tres movimientos direccionales entre cierres y recuperar
como mínimo 10 % de la distancia del salto. Estas barras no se mezclan con las
temporalidades canónicas ni aparecen como archivos requeridos. Si no existen,
la revisión manual continúa disponible para paquetes antiguos.

Limitación operativa vigente: el scanner procesa esta confirmación en el ciclo
de cierre de 15m. La medición corresponde exactamente a los primeros cinco
minutos, pero la notificación puede emitirse después; adelantar exclusivamente
este detector requiere una cadencia adicional segura.

## Pendientes antes de completar la automatización

- Confirmar el nombre oficial de la estrategia en el registro.
- Definir cómo medir que las bandas “comienzan a cerrarse”.
- Precisar la ventana temporal exacta de vigencia.
- Validar esta interpretación con Joan.

## Notas

Los porcentajes de rentabilidad mencionados en la capacitación son ejemplos
educativos y no forman parte del detector ni constituyen una promesa.
