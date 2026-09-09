# Glosario técnico Investep para JJTrade AI

Estado: `EN_PROCESO`  
Fuentes principales: `Bollinguer 1.txt`, `Bollinguer2.txt`, `indicadores.txt`,
`worden.txt` y `Bollinguer y sus temporalidades.txt`.

## Bollinger

Componentes utilizados por la metodología:

- Disipador superior: banda superior.
- Punto Medio: línea central y media móvil de 20 períodos.
- Disipador inferior: banda inferior.
- Volatilidad: separación o “mancha” comprendida entre los disipadores.

Bollinger aporta contexto de tendencia, volatilidad y posición del precio, pero
no debe utilizarse de manera aislada para decidir una operación.

## Punto Medio

El Punto Medio indica el estado de tendencia en la temporalidad evaluada:

- Inclinado al alza: tendencia alcista.
- Inclinado a la baja: tendencia bajista.
- Lateral: tendencia lateral.

En una tendencia alcista puede actuar como piso cuando el precio se aproxima
desde arriba. En una tendencia bajista puede actuar como techo cuando el precio
se aproxima desde abajo. El respeto del nivel necesita confirmación.

## Disipadores y volatilidad

- Mayor separación entre disipadores representa mayor volatilidad.
- Apertura simultánea de ambos disipadores respalda un movimiento fuerte.
- Disipadores cerrados representan baja o nula volatilidad.
- Aperturas y cierres repetidos sin expansión sostenida constituyen volatilidad
  engañosa.
- Movimiento del precio sin apertura de disipadores constituye movimiento
  engañoso.
- El movimiento puede continuar mientras la volatilidad permanezca abierta y
  pierde fuerza cuando comienza a cerrarse.

La capacitación no establece un ángulo o distancia universal. Cada definición
cuantitativa deberá validarse mediante ejemplos y datos.

## Precio expuesto

Un precio está expuesto cuando queda fuera del disipador correspondiente. Tiene
probabilidad de acercarse nuevamente al disipador, pero puede continuar en la
misma dirección si la volatilidad sigue abierta.

Por ello, exposición nunca equivale por sí sola a `CALL` o `PUT`.

## Saliendo desde Bollinger

Cuando el precio parte dentro de Bollinger, sale con fuerza, ambos disipadores
se abren y Punto Medio se inclina en la misma dirección, existe un movimiento
respaldado por volatilidad.

Debe descartarse o frenarse cuando:

- El precio ya está excesivamente expuesto.
- La volatilidad no abre o se fractura.
- Punto Medio no acompaña la dirección.
- Existen medias móviles o niveles que bloquean el recorrido.

## Jerarquía temporal

- Diario tiene más peso que Hora.
- Hora tiene más peso que 15 minutos.
- 15 minutos suele anticipar cambios que después pueden aparecer en Hora.
- Hora suele anticipar cambios que después pueden aparecer en Diario.

La estrategia puede originarse en una temporalidad específica, pero el panorama
debe comprobar conflictos con temporalidades superiores.

## Worden Stochastics

Es un oscilador utilizado principalmente como confirmación de Efecto Imán. La
capacitación lo considera complementario y no suficiente para decidir por sí
solo.

## Pendientes de normalización

- Pendiente mínima para considerar Punto Medio direccional.
- Separación mínima y tasa de expansión de los disipadores.
- Definición de volatilidad abierta, cerrada, fracturada y engañosa.
- Distancia mínima para considerar un precio expuesto.
- Tolerancias diferentes por símbolo y temporalidad.

