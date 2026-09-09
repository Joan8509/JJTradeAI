# Revisión de las ocho estrategias mediante imágenes

Estado: `EN_CURSO`  
Inicio: 2026-08-16  
Autoridad: evidencia metodológica aportada por Joan; no autoriza cambios de
reglas hasta completar y reconciliar las ocho estrategias.

## Estrategia 1 — Cambio de tendencia al alza, Hora

Fuente visual: `Cambio de tendencia a la alza.jpeg`, páginas 190–191.

### Requisitos explícitos observados

1. Trazar una línea de tendencia sobre el precio, bordeando levemente y
   alcanzando la mayor cantidad posible de puntos de la tendencia bajista.
2. El precio debe romper esa línea. La ruptura puede ocurrir durante el día o
   mediante un salto.
3. En Hora, el precio debe romper la media móvil de 20 periodos y terminar con
   una vela de confirmación alcista.
4. En 15 minutos, la tendencia debe mostrarse totalmente alcista.
5. Solo cuando se cumplan todos los requisitos se contempla una posición CALL.

### Coincidencias con la implementación actual

- Variante alcista asociada a `CALL`.
- Tendencia previa bajista en Hora.
- Línea trazada por la parte superior y ruptura alcista.
- Ruptura del Punto Medio de Bollinger, equivalente a la media móvil de 20.
- Confirmación alcista en Hora.
- Alineación alcista posterior en 15 minutos.

### Diferencias o precisiones pendientes

- La imagen no establece por sí sola un mínimo de dos días para la tendencia
  previa; ese mínimo procede de las fuentes textuales anteriores.
- La imagen dice que un salto puede producir la ruptura de la línea, pero no
  afirma inequívocamente que el salto elimine el requisito posterior de una
  vela alcista de confirmación. Debe revisarse el atajo de confirmación por
  salto del detector actual.
- “Bordear la mayor cantidad de puntos” describe una línea de contacto. La
  regresión sobre todos los máximos usada actualmente es una aproximación y
  puede divergir de una línea visual válida.
- “Totalmente alcista” en 15 minutos sigue sin una definición matemática
  suficiente. No debe inventarse un umbral.

### Decisión provisional

No cambiar el detector todavía. Reconciliar estas observaciones con las otras
siete imágenes y con las fuentes textuales antes de modificar confirmaciones,
líneas o umbrales.

## Estrategia 2 — Cambio de tendencia a la baja, Hora

Fuente visual: `Cambio de tendencia a la baja.jpeg`, páginas 192–193.

### Requisitos explícitos observados

1. Es la variante bajista de la estrategia anterior.
2. Trazar una línea de tendencia por debajo del precio, bordeando levemente y
   alcanzando la mayor cantidad posible de puntos de la tendencia alcista.
3. El precio debe romper esa línea. La ruptura puede ocurrir durante el día o
   mediante un salto.
4. En Hora, el precio debe romper la media móvil de 20 periodos y terminar con
   una vela de confirmación bajista.
5. En 15 minutos, la tendencia debe mostrarse totalmente bajista.
6. Solo cuando se cumplan todos los requisitos se contempla una posición PUT.

### Coincidencias con la implementación actual

- Variante bajista asociada a `PUT`.
- Tendencia previa alcista en Hora.
- Línea trazada por la parte inferior usando los mínimos.
- Ruptura bajista de la línea y del Punto Medio/MA20 de Hora.
- Confirmación horaria bajista y alineación bajista en 15 minutos.

### Diferencias o precisiones pendientes

- Igual que en la variante alcista, la imagen no define un mínimo de dos días.
- El salto se presenta como mecanismo posible de ruptura, no como sustitución
  explícita de la vela bajista de confirmación.
- La línea debe privilegiar contactos visuales con la trayectoria. Una
  regresión de todos los mínimos es solo una aproximación.
- “Totalmente bajista” en 15 minutos no tiene aquí un umbral matemático.
- Los ejemplos muestran ruptura decidida y continuidad, pero la imagen no
  define una distancia mínima, número de velas ni porcentaje de penetración.

### Decisión provisional

Mantener la simetría CALL/PUT del detector, pero no validar todavía el atajo
por salto ni las tolerancias de línea. La pareja de imágenes 1–2 refuerza que
la vela horaria direccional y la alineación de 15 minutos son requisitos, no
simples elementos informativos.

## Estrategia 3 recibida — Efecto Imán, tendencia alcista

Numeración del libro: estrategia 8.  
Fuente visual: `Efecto iman-tendencia alcista.jpeg`, páginas 204–205.

### Requisitos explícitos observados

1. Tendencia claramente alcista en las medias móviles de Hora, sostenida
   durante varios días.
2. Apertura con un salto fuerte al alza que deje el precio muy alejado de la
   MA20 de Hora.
3. La primera vela de 15 minutos debe quedar completamente fuera del disipador
   superior de Bollinger.
4. La confirmación para comprar PUT ocurre cuando la vela de volumen comienza
   a formarse y cruza la línea roja de Worden Stochastics en Hora.
5. El objetivo conceptual es la corrección del precio hacia la MA20 de Hora,
   que actúa como imán cuando la tendencia alcista comienza a fatigarse.

### Coincidencias con la implementación actual

- Tendencia alcista de Hora mediante MA20 y MA40.
- Salto alcista anormalmente alejado de MA20 Hora.
- Primera vela 15m totalmente sobre Bollinger, sin tocar el disipador.
- Sesgo contrario `PUT`, pendiente de confirmación.
- El cruce Worden permanece obligatorio y `NO_DISPONIBLE` cuando no existe la
  serie de la línea roja.

### Diferencias o precisiones pendientes

- La imagen dice “varios días”, no fija exactamente dos. Las dos sesiones del
  detector son un mínimo operativo derivado de las fuentes textuales previas.
- La imagen no menciona percentil 90 ni ventana de 60 sesiones. Esa regla es
  una cuantificación adaptativa previa y debe conservar trazabilidad separada.
- La frase sobre cuándo comienza a formarse “la vela en indicador volumen” no
  identifica inequívocamente la segunda vela de 15 minutos. La implementación
  actual sí exige que haya comenzado la segunda vela; debe reconciliarse con la
  fuente textual original.
- La captura no incluye el requisito de camino limpio hasta MA20 ni medias
  100/200; ese criterio procede de evidencia textual anterior.
- El API actual no entrega la línea roja de Worden Stochastics. No se puede
  inferir el cruce únicamente con volumen estándar.

### Decisión provisional

Mantener el detector conservador y el cruce Worden como bloqueo obligatorio.
No convertir una exposición 15m o un salto aislado en PUT confirmado. Revisar
la secuencia temporal exacta cuando se reciba la imagen de la variante bajista
y al reconciliar las ocho estrategias.

## Estrategia 4 recibida — Efecto Imán, tendencia bajista

Numeración del libro: estrategia 7.  
Fuente visual: `Efecto iman-tendencia bajista.jpeg`, páginas 202–203.

### Requisitos explícitos observados

1. Tendencia claramente bajista en las medias móviles de Hora durante varios
   días.
2. Apertura con salto fuerte a la baja, muy alejada de MA20 Hora.
3. Primera vela de 15 minutos completamente fuera del disipador inferior.
4. Confirmación mediante cruce de la línea roja de Worden Stochastics en Hora
   cuando comienza a formarse la vela del indicador de volumen.
5. La confirmación conduce a una posible compra CALL para el regreso hacia
   MA20 Hora.

### Coincidencias con la implementación actual

- Es la variante simétrica de Efecto Imán alcista: tendencia bajista, salto a
  la baja, exposición inferior y sesgo contrario `CALL`.
- El requisito de que toda la primera vela quede fuera de Bollinger coincide
  con la comparación de su máximo contra el disipador inferior.
- La imagen 12 etiqueta una “vela expuesta” y señala “Entrada” en la vela de
  reacción siguiente. Esto respalda la separación entre exposición inicial y
  confirmación posterior usada por el detector.
- Worden continúa siendo una compuerta obligatoria no inferible desde Alpaca.

### Diferencias o precisiones pendientes

- “Varios días” sigue sin definir un número exacto.
- “Fuerte salto” y “muy alejado” no incluyen porcentajes en la imagen.
- La imagen apoya esperar una reacción posterior, pero no define si basta el
  inicio de la segunda vela, si debe ser verde, cuánto debe recuperar ni si
  necesita cerrar. La flecha visual no debe transformarse en un umbral
  inventado.
- La afirmación narrativa de que el precio “regresa siempre” no constituye una
  garantía ni una regla técnica y no se incorporará al sistema.
- El camino limpio y las medias adicionales siguen procediendo de las fuentes
  textuales, no de esta captura.

### Decisión provisional

La pareja de imágenes 7–8 valida la simetría `PUT`/`CALL` y refuerza que la
primera vela expuesta no es por sí sola una entrada. Mantener `NO CONFIRMADA`
hasta el cruce Worden/reacción posterior y no atribuir rentabilidad garantizada.

## Estrategia 5 recibida — Rebote en Punto Medio al alza

Numeración del libro: estrategia 3.  
Fuente visual: `Rebote en punto medio a la alza.jpeg`, páginas 194–195.

### Requisitos explícitos observados

1. Tendencia claramente alcista en Bollinger Diario.
2. Tendencia claramente bajista en Bollinger Hora durante el retroceso.
3. Precio cayendo y acercándose durante varios días al Punto Medio/MA20
   Diario, previamente marcado como referencia.
4. Al tocar el nivel, el precio no debe cruzarlo: debe respetarlo.
5. En 15 minutos debe observarse el comienzo del rebote.
6. La entrada CALL solo se contempla después de una vela horaria alcista de
   confirmación.

### Coincidencias con la implementación actual

- Punto Medio Diario ascendente y Punto Medio Hora descendente.
- Acercamiento de varios días.
- Contacto con el Punto Medio Diario y observación del rechazo en 15m.
- Vela cerrada de Hora alcista como confirmación obligatoria.
- Sesgo final `CALL`; el rebote de 15m aislado no confirma la estrategia.

### Diferencias o precisiones pendientes

- “Claramente” alcista/bajista no aporta un umbral de pendiente.
- “Varios días” no fija tres cierres. El detector usa tres como aproximación.
- La implementación compara los tres cierres anteriores contra el Punto Medio
  Diario más reciente. Una representación más fiel podría medir cada cierre
  contra el Punto Medio correspondiente a su propio día.
- La frase “que no cruce el punto” puede exigir que ni el mínimo atraviese el
  nivel. El detector actual permite una mecha por debajo si el cierre vuelve
  arriba. Esta diferencia es material y necesita validación explícita.
- No existe tolerancia aprobada para distinguir tocar, cruzar o quedar apenas
  separado de MA20.
- La imagen exige una vela horaria alcista, pero no define cuerpo mínimo ni
  tratamiento de doji. El cierre sobre el Punto Medio usado actualmente es una
  condición conservadora adicional.

### Decisión provisional

Mantener la secuencia Diario → Hora contraria → toque/rechazo 15m → vela Hora
confirmatoria. Antes de ajustar el código, resolver si una mecha que atraviesa
MA20 invalida el rebote y si el acercamiento debe usar el Punto Medio histórico
de cada día.

## Estrategia 6 recibida — Rebote en Punto Medio a la baja

Numeración del libro: estrategia 4.  
Fuente visual: `Rebote en punto medio a la baja.jpeg`, páginas 196–197.

### Requisitos explícitos observados

1. Tendencia claramente bajista en Bollinger Diario.
2. Tendencia claramente alcista en Bollinger Hora durante el acercamiento.
3. Precio subiendo hacia el Punto Medio/MA20 Diario, marcado como referencia.
4. Al tocar el nivel, el precio no debe cruzarlo y debe respetarlo.
5. En 15 minutos debe comenzar el rebote bajista desde la referencia.
6. Esperar una vela horaria bajista de confirmación antes de contemplar PUT.

### Coincidencias con la implementación actual

- Punto Medio Diario descendente y Punto Medio Hora ascendente.
- Acercamiento desde abajo durante varios días.
- Contacto y rechazo observado en 15m.
- Confirmación obligatoria mediante vela cerrada de Hora bajista.
- Sesgo final `PUT`.

### Diferencias o precisiones pendientes

- La simetría confirma que “no cruzar” también aplica por arriba: una mecha
  sobre MA20 Diario podría invalidar el caso. El detector actual permite esa
  mecha si el cierre 15m termina nuevamente debajo.
- La imagen 8 muestra la secuencia de rechazo, pero no cuantifica distancia,
  tolerancia, cuerpo de vela ni número exacto de velas para declarar el giro.
- Igual que en la variante alcista, “varios días” no equivale necesariamente a
  tres cierres y conviene comparar cada cierre con su MA20 histórica.
- La confirmación de Hora debe ser bajista; la imagen no define cuerpo mínimo,
  cierre relativo al mínimo ni tratamiento de velas de indecisión.

### Decisión provisional

La pareja de imágenes 3–4 valida completamente la simetría del detector y la
obligatoriedad de la confirmación horaria. La interpretación más literal de
“no cruzar” sería exigir que el rango completo respete MA20, pero no se debe
cambiar todavía sin la validación final de Joan y una tolerancia para ruido.

## Estrategia 7 recibida — Tendencia lateral, fuera de Bollinger a la baja

Numeración del libro: estrategia 6.  
Fuente visual: `Tendencia lateral fuera de Bollinger.jpeg`, páginas 200–201.

### Requisitos explícitos observados

1. Bollinger 15m totalmente lateral y sin volatilidad antes de la apertura.
2. Apertura con salto fuerte a la baja, extremadamente alejada del disipador
   inferior y en zona de sobreventa.
3. Observar que el precio comience a subir.
4. La compra CALL debe ejecutarse dentro de los primeros cinco minutos; pasado
   ese tiempo la estrategia puede perder efecto.
5. El análisis debe comenzar minutos antes de la apertura, comparando el precio
   esperado de apertura con el cierre del día anterior.

### Coincidencias con la implementación actual

- Temporalidad 15m, contexto previo lateral y comprimido.
- Salto bajista fuera del disipador inferior.
- Sesgo `CALL` solo si aparece reversión inmediata hacia Bollinger.
- Uso de barras auxiliares de un minuto para medir exactamente los primeros
  cinco minutos.
- El radar intravela agregado al proyecto permite notificar esta geometría sin
  esperar el cierre completo de 15m.

### Diferencias o precisiones pendientes

- La imagen fija con claridad una ventana máxima de cinco minutos. El detector
  mide esos minutos, pero sus umbrales internos —tres movimientos de cuatro y
  recuperación mínima del 10 % del salto— no aparecen en esta página.
- La imagen dice “fuera de Bollinger” en la apertura. El detector compara la
  apertura con el disipador del cierre anterior; debe validarse si también se
  exige permanecer fuera del disipador recalculado intravela.
- Los percentiles 25 de compresión y 90 de salto son cuantificaciones
  adaptativas previas, no valores publicados en esta imagen.
- El requisito actual de que ambos disipadores comiencen a cerrarse tampoco
  aparece aquí y procede de la fuente textual anterior.
- “Comience a subir” no define número de ticks, velas de un minuto, porcentaje
  recuperado ni spread aceptable.
- La preparación premarket requiere una fuente de precio indicativo previa a
  9:30; el scanner actual comienza su evaluación formal con barras regulares.

### Decisión provisional

La regla temporal de cinco minutos queda fuertemente validada y debe conservar
prioridad alta en la notificación intravela. No mostrar esta oportunidad como
vigente después de 9:35 ET. Revisar tras la octava imagen si conviene crear un
estado `PREPARANDO_APERTURA` con datos premarket, sin inventar confirmación.

## Estrategia 8 recibida — Tendencia lateral, fuera de Bollinger al alza

Numeración del libro: estrategia 5.  
Fuente visual: `Tendencia lateral-Fuera de Bollinger.jpeg`, páginas 198–199.

### Requisitos explícitos observados

1. Bollinger 15m totalmente lateral y sin volatilidad antes de la apertura.
2. Apertura con salto fuerte al alza, extremadamente alejada del disipador
   superior y en zona de sobrecompra.
3. Observar que el precio comience a bajar.
4. Comprar PUT dentro de los primeros cinco minutos; después la estrategia
   puede quedar sin efecto.
5. Preparar el análisis antes de la apertura comparando el salto esperado con
   el cierre anterior.

### Coincidencias con la implementación actual

- Es la variante simétrica de la estrategia 6: lateralidad previa, salto fuera
  del disipador, reversión inmediata y sesgo contrario `PUT`.
- El detector utiliza cinco barras de un minuto y el radar intravela puede
  mostrar el resultado sin esperar el cierre de 15m.

### Diferencias o precisiones pendientes

- Se repiten las diferencias sobre percentiles, recuperación mínima, número de
  minutos direccionales y cierre de bandas: son cuantificaciones previas, no
  valores visibles en el libro.
- La imagen muestra una reversión fuerte desde la apertura, pero no fija el
  mínimo necesario para declarar que “comienza a bajar”.
- Debe definirse una fuente premarket y qué precio representa la apertura
  esperada antes de 9:30.

### Decisión provisional

Las estrategias 5–6 quedan explícitamente limitadas a 09:30–09:34 ET. Se
implementa de inmediato el vencimiento visual después de esa ventana, porque
es una regla textual exacta y simétrica. Los umbrales de fuerza permanecen sin
cambios hasta validación.

## Síntesis de las ocho imágenes

- Cambio de tendencia: ruptura de línea y MA20 Hora, vela horaria direccional
  y alineación total en 15m.
- Rebote en Punto Medio: tendencia Diario, aproximación contraria en Hora,
  respeto del nivel en 15m y confirmación final de Hora.
- Laterales fuera de Bollinger: preparación premarket, reversión inmediata y
  ventana estricta de cinco minutos.
- Efecto Imán: tendencia de varios días en Hora, salto extremo, primera vela
  15m completamente expuesta y confirmación Worden posterior.
- Ninguna imagen autoriza usar una geometría incompleta como operación final.
- Permanecen pendientes las tolerancias visuales, la definición de tendencia
  “clara/total”, la línea de contacto y los datos de Worden/premarket.
