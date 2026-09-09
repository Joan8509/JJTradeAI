# JJTrade AI - Blueprint de construccion

## Objetivo

Encontrar en el movimiento del mercado las estrategias documentadas en las
clases de Joan, explicar la evidencia multitemporal y separar claramente una
geometria candidata de una entrada confirmada.

## Flujo autoritativo

1. **Datos**: cargar y validar 15m, 1H y 1D con procedencia y fecha.
2. **Contexto**: medir tendencia, Bollinger, medias, volatilidad, niveles y
   panorama sin emitir una operacion.
3. **Detectores**: buscar la geometria propia de cada estrategia registrada.
4. **Confirmaciones**: evaluar requisitos objetivos y revisiones humanas.
5. **Invalidaciones**: bloquear noticias, datos vencidos, conflictos y reglas
   especificas de cada estrategia.
6. **Riesgo y gobierno**: comprobar contrato, plan, modo PAPER y disciplina.
7. **Decision**: emitir `CALL`, `PUT` o `NO_OPERAR` con evidencia auditable.

## Vistas de producto

- **Por activo**: todas las estrategias evaluadas para un simbolo.
- **Por estrategia**: todos los simbolos ordenables para una estrategia.
- **Candidatas**: geometria detectada con confirmaciones pendientes.
- **Confirmadas**: estrategia detectada con todos sus requisitos satisfechos;
  aun depende de panorama, invalidaciones, riesgo y gobierno.
- **Auditoria y diario**: evidencia, decisiones, overrides y resultado PAPER.

## Estados del scanner

- `NO_DETECTADA`: la geometria base no aparecio.
- `CANDIDATA`: geometria detectada, con requisitos pendientes.
- `FALLIDA`: geometria detectada, con al menos un requisito incumplido.
- `CONFIRMADA`: todos los requisitos obligatorios estan en `CUMPLE`.

Estos estados describen estrategias. Ninguno sustituye la decision final.

## Orden de construccion

1. Scanner multi-activo por estrategia.
2. Vista Streamlit por estrategia y candidatas.
3. Componentes objetivos reutilizables: volatilidad, lateralidad, medias y
   disipadores.
4. Completar detectores parciales usando solamente reglas documentadas.
5. Validacion con casos TC2000 reales y diario PAPER.
6. Calibracion fuera de muestra antes de cualquier confianza numerica.

## Regla metodologica

Una expresion visual de las clases sin medida oficial se conserva como
revision humana o configuracion pendiente. Nunca se transforma en un umbral
inventado para hacer que una estrategia aparezca confirmada.
