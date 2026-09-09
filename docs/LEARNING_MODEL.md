# Aprendizaje controlado

## Objetivo

JJTrade AI aprende describiendo qué ocurrió en operaciones documentadas. No
reescribe detectores, no elimina invalidaciones y no aumenta riesgo de forma
automática.

Esta separación también se protege en liberación con
`safety_invariants.py`. El verificador bloquea importaciones directas o
dependencias transitivas desde los módulos críticos de decisión hacia
`learning_engine` o `learning_context`, y confirma que no existan rutas de
ejecución de órdenes.

## Datos conservados

- análisis y versión metodológica;
- estrategias detectadas;
- sesgo tentativo cuando el análisis quedó incompleto;
- modo `PAPER` o `REAL`;
- plan de entrada y salida;
- contrato, costo y resultado;
- si la operación siguió la decisión del motor;
- justificación cuando el usuario decidió apartarse de la decisión.

## Métricas implementadas

- tamaño de muestra;
- tasa de acierto observada;
- intervalo Wilson del 95% para esa tasa observada;
- P&L medio y total;
- profit factor;
- drawdown máximo de la secuencia registrada;
- porcentaje de operaciones que siguieron la decisión;
- conteo descriptivo por decisión original (`CALL`, `PUT`, `NO_OPERAR`);
- conteo de excepciones humanas frente a la decisión del motor.

PAPER y REAL se calculan por separado. Una operación asociada con varias
estrategias aporta evidencia descriptiva a cada una, por lo que estas métricas
no prueban causalidad individual.

Las alertas en vivo también conservan feedback versionado por reevaluación. Una
corrección no borra el dato anterior, aunque las estadísticas utilizan solo la
versión más reciente. `NO_OPERADA` queda disponible para auditoría y no se
incluye en la tasa de resultados positivos.

El modo del resultado no es una etiqueta libre. Se deriva de la revisión de
gobierno vinculada a la reevaluación; sin gobierno explícito solo se permite
`PAPER`, y `REAL` exige una revisión `REAL` de la misma alerta. Revisiones
humanas, contratos y gobierno con IDs de otra alerta se rechazan antes de
guardar la reevaluación.

## Contexto de mercado de alertas

Las alertas nuevas congelan etiquetas calculadas en el momento del cierre:

- tendencia de 15 minutos frente a media de 20 barras;
- volatilidad reciente relativa a las 20 barras anteriores;
- apertura, media sesión, cierre o fuera de sesión;
- dirección agregada y sincronización de SPY/QQQ/IWM/DIA configurados;
- alineación de esos benchmarks con la decisión reevaluada.

Si no existen al menos 25 barras o el contexto no estaba disponible, el campo
queda `NO_DISPONIBLE`. No se reconstruye con información futura. Cada segmento
requiere por defecto 10 operaciones tomadas antes de quedar elegible para una
calibración posterior; incluso entonces se muestra como
`DESCRIPTIVA_NO_PREDICTIVA`.

## Confianza

La confianza permanece `NO_CALIBRADA`. Alcanzar un número mínimo de operaciones
solo indica tamaño de muestra; no corrige selección discrecional, cambios de
régimen, datos faltantes ni diferencias entre simulación y ejecución real.

Una calibración futura deberá usar casos fuera de muestra, versiones de reglas
congeladas y validación temporal. Ningún porcentaje mencionado en las clases se
usa como probabilidad del sistema.

La validación temporal de alertas conserva separadas estrategia, modo y versión
metodológica. Ordena por la fecha de mercado de la alerta —no por la fecha en
que se informó o corrigió el resultado—, usa el 70% inicial como referencia y
el 30% final como tramo fuera de muestra. Exige al menos 10 casos iniciales y 5
posteriores. Solo informa degradación o mejora cuando los intervalos Wilson del
95% no se solapan; en los demás casos declara que no existe diferencia
concluyente.

Cada alerta nueva congela además una asesoría histórica con los resultados que
ya estaban registrados antes de su vela disparadora. Presenta PAPER y REAL por
separado, tanto en general como para las etiquetas contextuales coincidentes.
Solo utiliza registros de la misma versión metodológica y exige la secuencia
`evento de mercado <= registro del resultado <= vela de la alerta`. Un evento
futuro, una fecha sin zona horaria, una versión distinta o un resultado anotado
después de esa vela quedan excluidos para impedir fuga temporal y mezcla de
reglas. Esta asesoría tiene autoridad
`DESCRIPTIVA_NO_INFLUYE_DECISION`: no cambia CALL/PUT, confianza, compuertas ni
reglas metodológicas.

La política actual es `LEARNING_ADVISORY_V2`. La asesoría incluye
`methodology_version`, los identificadores de resultados usados y una huella
SHA-256 de un manifiesto canónico. El auditor puede recalcularla con el
historial actual. Devuelve `REPRODUCIBLE`, `HISTORIAL_CAMBIO` o `NO_AUDITABLE`
para alertas antiguas. Una discrepancia informa que hubo una corrección
histórica; nunca reescribe la asesoría congelada ni la decisión.

## Regla crítica

El aprendizaje puede recomendar revisar una regla, pero solo una nueva versión
metodológica aprobada puede modificarla.
