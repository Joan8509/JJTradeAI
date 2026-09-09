# Auditoría de reportes

JJTrade AI puede generar reportes JSON desde la app, desde
`validation_runner.py` o desde `validation_batch.py`. El auditor revisa esos
reportes y resume qué evidencia falta antes de considerar un caso como útil
para revisión o aprendizaje PAPER.

El auditor no cambia la decisión final y no crea señales nuevas.
Si el JSON contiene una decisión final distinta de `CALL`, `PUT` o
`NO_OPERAR`, el auditor rechaza el reporte como mal formado.

## Auditar un reporte individual

```powershell
.\venv\Scripts\python.exe report_auditor.py `
  --report exports\validation_SPY.json
```

Para guardar el resultado:

```powershell
.\venv\Scripts\python.exe report_auditor.py `
  --report exports\validation_SPY.json `
  --output-csv exports\audit_SPY.csv
```

## Auditar una carpeta de reportes

```powershell
.\venv\Scripts\python.exe report_auditor.py `
  --reports-dir exports\validation_batch\reports `
  --output-csv exports\validation_batch\audit.csv
```

Para generar tambien una cola de revision accionable:

```powershell
.\venv\Scripts\python.exe report_auditor.py `
  --reports-dir exports\validation_batch\reports `
  --output-csv exports\validation_batch\audit.csv `
  --output-review-csv exports\validation_batch\review_queue.csv
```

Por defecto, un JSON inválido detiene la auditoría de carpeta. Para revisar los
reportes válidos y omitir los mal formados, usa `--skip-invalid`; el auditor
avisará cuáles omitió.

## Estados de auditoría

La app muestra estos estados como auditoría inmediata en la pestaña
**Análisis** para el reporte recién generado. La pestaña **Auditoría** permite
revisar reportes JSON guardados o producidos por CLI/lote, ver la misma cola
accionable y descargarla como CSV.

- `LISTO_REVISION`: no hay compuertas abiertas ni bloqueos detectados.
- `INCOMPLETO`: faltan confirmaciones, panorama, riesgo, gobierno operativo o
  invalidaciones por revisar.
- `BLOQUEADO`: existe una invalidación activa, error de detector o compuerta
  rechazada.

## Campo `learning_ready`

`learning_ready = SI` significa que el caso tiene evidencia suficiente para
entrar en una revisión PAPER controlada. No significa que la operación fue buena
ni que una estrategia esté calibrada.

Un caso puede tener decisión `NO_OPERAR` y aun así ser útil para aprendizaje si
explica con claridad por qué no se debía operar.

## Resumen de detectores

Cuando el reporte incluye `strategy_summary`, el auditor conserva los conteos
de detectores evaluados, detectados, confirmados, omitidos y con error. Esto
permite revisar el alcance del caso sin reemplazar la evidencia completa de
`strategies.evaluations`. Si `strategy_summary` existe, debe ser un objeto; un
tipo distinto se rechaza como reporte mal formado.

El auditor también conserva `app_version` y `methodology_version` cuando el
reporte las incluye, y las propaga al CSV o a la auditoría guardada en el
diario.

El CSV también expone `data_quality_status`, `panorama_status`, `risk_status` y
`governance_status` como columnas propias para filtrar casos por compuerta.
Cuando el reporte proviene de `validation_batch.py`, conserva la trazabilidad
del paquete en `package_id`, `package_session` y `package_timeframes`.
Si el reporte incluye `data_source`, el auditor propaga `data_provider`,
`data_source_timeframes` y `data_source_files` al CSV y al diario.

Si el reporte incluye `decision.tentative_bias` y
`decision.tentative_strategies`, el auditor los propaga al CSV. Esto permite
filtrar casos donde había dirección preliminar, pero la decisión final seguía
siendo conservadora.

Las evaluaciones repetidas de una misma estrategia deben declarar
`timeframe`. El auditor las presenta como `STRATEGY_ID@15m`,
`STRATEGY_ID@1H` o `STRATEGY_ID@1D` tanto en estrategias detectadas como en
evidencia pendiente. Las listas `supporting_strategies` y
`tentative_strategies` usan la misma etiqueta cuando corresponde. El sufijo
solo identifica la evaluación; no cambia el ID metodológico registrado.

Además clasifica pendientes y bloqueos por origen: compuertas, estrategias,
invalidaciones, errores de detector y problemas concretos de calidad de datos.
Esto ayuda a decidir si el siguiente paso es completar una revisión visual,
corregir datos o revisar una invalidación.
El CSV incluye además `first_missing_evidence` y `first_blocker` para filtrar
rápidamente el siguiente punto accionable sin leer las listas completas.

Cuando se usa `--output-review-csv`, el auditor crea una fila por cada faltante
o bloqueo. Esa cola incluye `priority`, `review_type`, `source`, `evidence`,
`package_id`, `tentative_bias`, estrategias detectadas y ruta del reporte. Sirve
para ordenar primero bloqueos (`1_BLOQUEO`) y luego faltantes (`2_FALTANTE`) sin
abrir cada JSON completo.

Cuando un análisis se guarda desde la app, el resumen de auditoría inmediata se
conserva dentro del payload del análisis y aparece en la tabla de análisis
recientes del diario.

## Regla crítica

El auditor mide completitud de evidencia. No reemplaza la lectura del gráfico,
la revisión del riesgo ni la disciplina del plan operativo.
