# Analysis Pipeline

## Nivel 0 - Calidad de datos

Validar:

- archivos no vacíos;
- fechas ordenadas y sin duplicados;
- última sesión alineada entre temporalidades;
- indicadores críticos disponibles en la última vela;
- cantidad de velas cargadas por temporalidad.

Resultado: `calidad_datos`

Si esta compuerta no está aprobada, la decisión final debe permanecer en
`NO_OPERAR` y explicar que la calidad de datos no está aprobada.

---

## Nivel 1 - Detectores

Revisar todas las estrategias registradas.

Ejemplos:

- Expuesto en Bollinger
- Disipadores
- Punto Medio
- Primer Salto
- Cambio de Tendencia
- Volatilidad

Resultado: `estrategias_detectadas`

Los detectores pueden devolver evaluaciones diagnósticas con prefijo `SIN_*`
cuando no aparece una geometría operable. Esos registros sirven para explicar
la ausencia de setup, no son estrategias registradas ni pueden sostener una
dirección.

---

## Nivel 2 - Confirmaciones

Validar si las estrategias tienen confirmación.

Resultado: `estrategias_confirmadas`

---

## Nivel 3 - Invalidaciones

Buscar condiciones que invaliden la operación.

Resultado: `estrategias_invalidadas`

---

## Nivel 4 - Panorama

Analizar:

- 15m
- 1H
- Diario

Resultado: `panorama_general`

---

## Nivel 5 - Riesgo

Evaluar:

- Riesgo
- Calidad de la entrada
- Contexto

Resultado: `riesgo_operacion`

---

## Nivel 5.5 - Gobierno operativo

Validar:

- Modo PAPER o REAL
- Límite semanal
- Radar de compañías
- Plan escrito de entrada y salida

Resultado: `gobierno_operativo`

---

## Nivel 6 - Decisión

Posibles resultados:

- `CALL`
- `PUT`
- `NO OPERAR`

Regla crítica: ninguna estrategia individual puede emitir una decisión final
por sí sola.

La decisión exige simultáneamente calidad de datos aprobada, una estrategia
confirmada, ausencia de invalidaciones, panorama aprobado, riesgo aprobado y
gobierno operativo aprobado.
