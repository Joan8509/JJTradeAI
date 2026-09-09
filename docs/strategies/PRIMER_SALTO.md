# Saltos: Primer Salto Confirmado y Posible Segundo Salto

Estado: `IMPLEMENTADO_EN_BETA` — geometría objetiva; noticias y camino externos  
Categoría: `PRIMER_SALTO`  
Prioridad: `ALTA`  
Fuentes principales:  
- `Estrategias/saltos.txt`  
- `Estrategias/Resumen.txt`  
Fuente: Metodología Investep enviada por Joan

## Objetivo

Identificar un primer salto confirmado al inicio o final de una tendencia y
evaluar la probabilidad de un segundo salto en la misma dirección.

La clase indica que el primer salto no se predice con esta metodología básica.
La oportunidad evaluada es principalmente el segundo salto después de que el
primero haya sido respetado y haya roto niveles relevantes.

## Definición

Un salto o gap es la diferencia entre el precio de cierre de un día y el precio
de apertura del siguiente.

La app podrá estimar una dirección probable para el siguiente salto, pero no
podrá afirmar su magnitud. Una diferencia mínima sigue siendo un salto.

## Posible segundo salto alcista

1. Tendencia bajista previa, idealmente de cinco días o más.
2. El conteo principal comienza desde el cruce bajista de las medias móviles de
   20 y 40 en Hora.
3. Se presenta un primer salto al alza al final o inicio de una tendencia.
4. El precio rompe la tendencia y, preferiblemente, las medias móviles de 20 y
   40 u otros techos relevantes.
5. Al cierre, el precio mantiene el salto: termina por encima del cierre del día
   anterior.
6. No existe una noticia prevista que pueda afectar el activo entre el cierre y
   la siguiente apertura.
7. El posible segundo salto debe esperarse en la misma dirección alcista.

## Posible segundo salto bajista

1. Tendencia alcista previa, idealmente de cinco días o más.
2. El conteo principal comienza desde el cruce alcista de las medias móviles de
   20 y 40 en Hora.
3. Se presenta un primer salto a la baja al final o inicio de una tendencia.
4. El precio rompe la tendencia y, preferiblemente, las medias móviles de 20 y
   40 u otros pisos relevantes.
5. Al cierre, el precio mantiene el salto: termina por debajo del cierre del día
   anterior.
6. No existe una noticia prevista que pueda afectar el activo entre el cierre y
   la siguiente apertura.
7. El posible segundo salto debe esperarse en la misma dirección bajista.

## Confirmaciones adicionales

- Fatiga de tendencia: en tendencia bajista, mínimo igual o más alto; en
  tendencia alcista, máximo igual o más bajo.
- Mayor duración de la tendencia previa.
- Camino limpio hasta el siguiente techo o piso.
- Volatilidad al cierre puede ser un plus, pero no es requisito obligatorio.

## Invalidaciones y condiciones de descarte

- El primer salto queda borrado al cierre.
- El siguiente salto esperado tendría dirección contraria al primero.
- Noticia corporativa o macroeconómica relevante antes de la apertura.
- Primer salto sin ruptura suficiente de tendencia o niveles relevantes.
- Ausencia de espacio hasta el siguiente techo o piso.
- Intentar operar basándose en el movimiento intradía sin esperar el cierre.

## Momento de decisión

La capacitación plantea evaluar la compra muy cerca del cierre —entre uno y
cinco minutos antes— para confirmar que el primer salto continúa respetado.
Esta es una metodología de mayor riesgo y debe pasar por una capa específica de
gestión de capital.

Si se opera con opciones un jueves o viernes, la clase recomienda evaluar la
expiración de la semana siguiente. Esta regla pertenece a riesgo y selección de
contrato, no al detector.

## Noticias

“Noticia mata estrategia” es una invalidación explícita. La aplicación no puede
aprobar Saltos sin integrar o solicitar la revisión de un calendario
corporativo y macroeconómico actualizado.

## Pendientes antes de completar la automatización

- Confirmar si el nombre oficial del inventario debe ser `Primer Salto`,
  `Segundo Salto` o `Saltos`.
- Definir matemáticamente el cruce y duración de tendencia 20/40.
- Definir los niveles cuya ruptura es obligatoria y cuáles son preferibles.
- Definir el universo y ventana de noticias invalidantes.
- Formalizar fatiga de tendencia y espacio mínimo al siguiente nivel.
- Definir límites de riesgo específicos.
- Validar esta interpretación con Joan.

## Contrato técnico implementado

El módulo `strategies/primer_salto.py` implementa la evidencia objetiva:

- compara la apertura diaria con el cierre diario anterior;
- clasifica el salto como alcista o bajista;
- comprueba si el salto continúa respetado al cierre;
- en Alpaca infiere el cierre diario únicamente cuando `closed_through` Diario
  coincide con la sesión del último bloque 15m;
- exige cinco sesiones previas, al menos 75 % de cambios en la dirección
  anterior y una pendiente de cierres compatible;
- proyecta máximos para un salto alcista o mínimos para uno bajista y exige que
  el cierre diario rompa esa línea;
- confirma con la última vela cerrada de Hora en la dirección del salto;
- conserva noticias y espacio al siguiente nivel como compuertas externas.

Identificadores registrados:

- `PRIMER_SALTO_RESPETADO_ALCISTA`
- `PRIMER_SALTO_RESPETADO_BAJISTA`

Detectar un primer salto respetado no equivale a ordenar una entrada ni asegura
un segundo salto. El detector no estima la magnitud del salto. Mientras falte
cualquier revisión obligatoria, la estrategia no puede superar el pipeline de
decisión.

## Notas

Los porcentajes de probabilidad y rentabilidad mencionados en la capacitación
no se incorporarán como probabilidades calibradas hasta validarlos con datos
históricos propios.
