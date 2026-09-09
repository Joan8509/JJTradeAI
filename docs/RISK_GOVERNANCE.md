# Gobierno de riesgo y disciplina operativa

Estado: EN PROCESO DE VALIDACIÓN

Fuente principal: `Clase Yoel.txt`

## Propósito

Estas reglas gobiernan **cómo** se usa JJTrade AI. No son estrategias ni
confirmaciones direccionales. Evitan que una detección técnica se convierta en
una operación sin preparación, práctica y control humano.

## Reglas documentadas en la capacitación

- Comenzar en modalidad simulada (`PAPER`).
- Mantener un radar reducido: máximo tres compañías para una persona que inicia.
- Limitar la actividad inicial a tres posiciones u operaciones por semana.
- Especializarse en una o pocas compañías durante al menos un trimestre.
- Escribir el plan de entrada y el plan de salida antes de abrir la posición.
- Revisar posteriormente cada operación y conservar sus resultados.
- La clase propone duplicar primero una cuenta simulada antes de considerar
  capital real.

## Interpretación segura para JJTrade AI

La aplicación iniciará siempre en `PAPER`. Duplicar una cuenta simulada es una
referencia educativa del curso, pero **no demuestra por sí solo** preparación
para operar capital real. JJTrade AI no desbloqueará automáticamente el modo
real ni ejecutará órdenes.

Antes de considerar una transición a capital real deben existir, como mínimo:

- autorización expresa del usuario;
- una muestra suficiente de operaciones documentadas;
- plan de riesgo escrito;
- revisión de pérdidas máximas y consistencia;
- aceptación explícita de que el rendimiento histórico no garantiza resultados.

Los tamaños de muestra y límites definitivos permanecen pendientes de
validación; la aplicación no debe inventarlos.

## Flujos que no deben mezclarse

### NUEVA_ENTRADA

Evaluar desde cero detectores, confirmaciones, invalidaciones, panorama, riesgo
y plan escrito. Una estrategia detectada nunca basta.

### GESTION_POSICION

Administrar una operación ya abierta según su plan previo. Una regla válida
para conservar o cerrar una posición no autoriza automáticamente una entrada
nueva.

### REFUERZO

Aumentar una posición existente implica riesgo adicional. No se automatizará
en la primera versión y requerirá reglas específicas aprobadas.

## Controles iniciales de producto

- Modo predeterminado: `PAPER`.
- Radar inicial: máximo 3 símbolos únicos; espacios y mayúsculas/minúsculas se
  normalizan antes de contar.
- Límite educativo inicial: máximo 3 operaciones nuevas por semana.
- Plan de entrada y salida obligatorio antes de registrar una operación.
- Advertencias visibles al alcanzar límites; nunca órdenes automáticas.
- Estadísticas separadas entre simulación y capital real.
- Registrar una operación `REAL` exige aceptación humana explícita también en
  la capa de diario, no solo en la interfaz.
- Registrar una operación desde un análisis `INCOMPLETO` o `BLOQUEADO` exige
  razón de excepción aunque la acción coincida con la decisión `CALL` o `PUT`.

La compuerta de riesgo exige que el contrato revisado sea `CALL` o `PUT` y que
coincida con el sesgo direccional confirmado. El texto se normaliza a
mayúsculas y sin espacios externos, pero cualquier otro valor se rechaza.
Cuando falta un límite aprobado de riesgo, el criterio queda
`NO_DISPONIBLE` y el detalle se muestra como `no configurado`; eso bloquea la
aprobación sin tratarse como error técnico.

La trazabilidad posterior conserva el mismo alcance: una reevaluacion solo
puede vincular revisiones, contratos y gobierno pertenecientes a su alerta. El
modo del resultado se deriva de esa evidencia; sin gobierno vinculado se
considera `PAPER`, mientras que un resultado `REAL` exige gobierno `REAL`.

## Regla crítica

Los porcentajes, resultados y ejemplos históricos citados en las clases no son
probabilidades calibradas ni garantías. JJTrade AI aprenderá del diario de forma
controlada, pero no modificará reglas oficiales ni recomendará aumentar riesgo
automáticamente.
