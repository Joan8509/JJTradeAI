# Invalidaciones

Estado: EN_PROCESO  
Categoría: INVALIDACION  
Prioridad: ALTA  
Fuente: Metodología Investep enviada por Joan  

## Función

Una invalidación bloquea el avance hacia una decisión aunque exista una
estrategia detectada. No crea un sesgo contrario ni se interpreta como una
estrategia nueva.

## Invalidaciones transversales implementadas

- Noticia corporativa o macroeconómica relevante: “noticia mata estrategia”.
- Datos desactualizados o temporalidades pertenecientes a sesiones distintas.
- Estrategias plenamente confirmadas con sesgos opuestos.

## Invalidaciones específicas

La falta de volatilidad, exposición, cierre previo incorrecto, ruptura fallida
y otros descartes permanecen dentro de la evaluación de su estrategia. No se
generalizan porque una condición inválida para una estrategia puede ser válida
para otra.

## Contrato técnico

`invalidation_engine.py` devuelve criterios auditables. En este contrato,
`CUMPLE` significa que la invalidación está activa. Una invalidación activa
obliga al motor final a producir `NO_OPERAR`.

La revisión de noticias continúa siendo manual hasta integrar una fuente
actualizada y definir oficialmente su ventana temporal.
