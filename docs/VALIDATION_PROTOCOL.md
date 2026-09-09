# Protocolo de validacion con datos reales

Este documento define como validar JJTrade AI con exportaciones reales de
TC2000 antes de usarlo como apoyo operativo.

La validacion no busca demostrar rentabilidad. Busca comprobar que la app:

- lee correctamente los datos;
- no inventa confirmaciones;
- conserva evidencia;
- produce `NO_OPERAR` cuando falta una compuerta;
- permite revisar cada criterio contra el grafico original.

## Paquete minimo recomendado

Para cada simbolo y sesion guarda tres archivos TC2000:

- 15 minutos;
- 1 hora;
- diario.

Ejemplo de nombres sugeridos:

```text
SPY_2026-06-24_15m.txt
SPY_2026-06-24_1H.txt
SPY_2026-06-24_1D.txt
```

Las columnas requeridas siguen siendo:

- `Date`
- `Open`
- `High`
- `Low`
- `Close`
- `Moving Average 20`
- `Moving Average 40`
- `Moving Average 100`
- `Moving Average 200`
- `Volume`
- `Worden Stochastics`

Los valores numericos requeridos deben ser validos, no vacios y no negativos.
Ademas, cada vela debe respetar coherencia OHLC: `High` no puede quedar por
debajo de `Open`, `Low` o `Close`, y `Low` no puede quedar por encima de
`Open`, `High` o `Close`.

## Validacion por linea de comandos

El validador corre el mismo motor autoritativo que usa la interfaz.

Antes de generar artefactos puedes confirmar version de app y metodologia:

```powershell
.\venv\Scripts\python.exe validation_runner.py --version
.\venv\Scripts\python.exe validation_batch.py --version
.\venv\Scripts\python.exe report_auditor.py --version
```

Para crear una hoja de control donde registrar evidencia humana, revisiones
visuales y resultado PAPER de cada caso:

```powershell
.\venv\Scripts\python.exe validation_batch.py `
  --write-intake-template exports\tc2000_cases\case_intake_template.csv
```

Esta plantilla no participa en la decision automatica; solo ayuda a no perder
contexto entre los archivos TC2000, el reporte JSON, la auditoria y la revision
manual.

Camino recomendado: si ya copiaste archivos TC2000 a la carpeta de entrada,
ejecuta un preflight unico. Este genera inventario, intake y revision de intake
en una sola pasada:

```powershell
.\venv\Scripts\python.exe validation_batch.py `
  --input-dir exports\tc2000_cases `
  --preflight-output-dir exports\tc2000_cases
```

El preflight escribe:

- `exports\tc2000_cases\package_inventory.csv`;
- `exports\tc2000_cases\case_intake.csv`;
- `exports\tc2000_cases\case_intake_check.csv`.

Si detecta paquetes incompletos, termina con error para evitar correr el lote
sin 15m, 1H y 1D.

Cuando quieras generar controles y correr el batch en una sola ejecucion:

```powershell
.\venv\Scripts\python.exe validation_batch.py `
  --input-dir exports\tc2000_cases `
  --preflight-output-dir exports\tc2000_cases `
  --run-after-preflight `
  --output-dir exports\validation_batch `
  --standard-output-dir
```

El batch solo corre si el preflight no encuentra paquetes incompletos.
Con `--standard-output-dir`, el lote escribe tambien `audit.csv`,
`review_queue.csv` y `operator_board.csv` dentro de `--output-dir`.

Si ya copiaste archivos TC2000 a la carpeta de entrada, puedes generar una hoja
de intake alineada con los paquetes encontrados:

```powershell
.\venv\Scripts\python.exe validation_batch.py `
  --input-dir exports\tc2000_cases `
  --write-intake-from-input exports\tc2000_cases\case_intake.csv
```

Tambien puedes generar primero un inventario de paquetes para ver que
temporalidades estan presentes o faltantes:

```powershell
.\venv\Scripts\python.exe validation_batch.py `
  --input-dir exports\tc2000_cases `
  --write-package-inventory exports\tc2000_cases\package_inventory.csv
```

Antes de ejecutar el lote, puedes verificar que los archivos declarados en la
plantilla existan en la carpeta de entrada:

```powershell
.\venv\Scripts\python.exe validation_batch.py `
  --input-dir exports\tc2000_cases `
  --check-intake-csv exports\tc2000_cases\case_intake.csv `
  --intake-check-output-csv exports\tc2000_cases\case_intake_check.csv
```

Si algun archivo falta o una temporalidad queda sin declarar, la revision marca
el caso como `INCOMPLETO`.

```powershell
.\venv\Scripts\python.exe validation_runner.py `
  --symbol SPY `
  --tf15 exports\SPY_2026-06-24_15m.txt `
  --tf1h exports\SPY_2026-06-24_1H.txt `
  --tf1d exports\SPY_2026-06-24_1D.txt `
  --output exports\validation_SPY_2026-06-24.json
```

Por defecto, el resultado final debe ser conservador porque panorama, riesgo y
gobierno operativo no se aprueban automaticamente.

## Validacion por lote

Para validar muchos casos, coloca los archivos en una carpeta usando el patron:

```text
SIMBOLO_FECHA_TEMPORALIDAD.txt
```

Ejemplos:

```text
SPY_2026-06-24_15m.txt
SPY_2026-06-24_1H.txt
SPY_2026-06-24_1D.txt
AAPL_2026-06-24_15m.txt
AAPL_2026-06-24_1H.txt
AAPL_2026-06-24_1D.txt
```

Luego ejecuta:

```powershell
.\venv\Scripts\python.exe validation_batch.py `
  --input-dir exports\tc2000_cases `
  --output-dir exports\validation_batch `
  --require-complete-packages `
  --standard-output-dir
```

Si todos los casos del lote comparten una misma revision externa de riesgo o
gobierno, puedes conservarla con:

```powershell
.\venv\Scripts\python.exe validation_batch.py `
  --input-dir exports\tc2000_cases `
  --output-dir exports\validation_batch `
  --risk-status RECHAZADO `
  --governance-status APROBADO
```

Estos estados se aplican a todos los paquetes del lote. Para revisiones
distintas por simbolo o contrato, genera reportes individuales con
`validation_runner.py`.

El proceso genera:

- `exports/validation_batch/reports/*.json`: reporte completo por simbolo/sesion,
  con `validation_package` para conservar `package_id`, sesion, temporalidades y
  rutas fuente;
- `exports/validation_batch/summary.csv`: resumen comparativo con decision,
  calidad de datos, conteo de velas por temporalidad, panorama, conteos del
  radar, detectores omitidos y estrategias detectadas. Tambien incluye
  `decision_data_quality` y `decision_panorama`, los estados usados por la
  compuerta final, ademas de `tentative_bias` y `tentative_strategies` cuando
  el caso apunta a una direccion preliminar todavia no confirmada. Tambien
  incluye `readiness`, `learning_ready` y conteos de evidencia faltante o
  bloqueos por compuertas, estrategias, invalidaciones y detectores.
- `exports/validation_batch/audit.csv`, si usaste `--audit-output-csv`:
  auditoria de completitud generada desde los reportes JSON del lote.
- `exports/validation_batch/review_queue.csv`, si usaste `--review-output-csv`:
  cola accionable con una fila por faltante o bloqueo.
- `exports/validation_batch/operator_board.csv`, si usaste
  `--operator-board-output-csv`: tablero por paquete con decision, readiness,
  primer pendiente, primer bloqueo y conteos agregados.
  Tambien se genera con `--standard-output-dir`.
- `exports/validation_batch/inspection.csv`, si usaste `--inspection-output-csv`:
  resultado de inspeccionar que los artefactos esperados existen y que los
  `package_id` principales coinciden.

Para inspeccionar una salida batch ya generada:

```powershell
.\venv\Scripts\python.exe validation_batch.py `
  --inspect-output-dir exports\validation_batch `
  --inspection-output-csv exports\validation_batch\inspection.csv
```

Si un paquete falla por archivo ilegible, columnas faltantes u otro error de
carga, el lote conserva un JSON de error para ese simbolo/sesion. Ese reporte
queda marcado como `ERROR` y la auditoria lo clasifica como `BLOQUEADO`, para
que el caso no desaparezca del control de calidad. Al igual que los reportes
exitosos, conserva `validation_package` con `package_id`, sesion,
temporalidades y rutas de los archivos usados.

El resumen sirve para detectar patrones, errores de exportacion y casos que
merecen revision manual profunda. No reemplaza el analisis en la interfaz ni la
aprobacion de riesgo.

Cada reporte JSON incluye `strategy_summary`, un resumen de radar con
detectores evaluados, detectados, confirmados, omitidos y con error. La
evidencia completa permanece en `strategies.evaluations`; `strategies.skipped`
y `strategies.errors` siempre existen para que el auditor tenga un contrato
estable. Tambien conserva
`app_version` y `methodology_version` para reproducibilidad.
Cuando `app_version` se incluye, no puede estar vacio; el JSON exportado debe
ser un objeto de reporte, no una lista u otro tipo.
Los reportes generados desde el CLI y desde validacion por lote pueden incluir
`data_source` con el proveedor y los archivos usados por temporalidad.

El resumen de lote tolera reportes heredados donde `risk.status` y
`governance.status` todavia no estaban duplicados dentro de `decision`; en esos
casos usa esas secciones como respaldo para las columnas `risk` y `governance`.

Cuando hay estrategias detectadas pero todavia no confirmadas, la seccion
`decision` puede incluir `tentative_bias` y `tentative_strategies`. Estos campos
sirven para explicar hacia donde apunta la geometria preliminar, pero no
autorizan una entrada. La decision debe permanecer `NO_OPERAR` hasta que las
confirmaciones, invalidaciones, panorama, riesgo y gobierno operativo esten
aprobados.

Cuando un detector se ejecuta sobre varias temporalidades, cada elemento de
`strategies.evaluations` conserva `timeframe`. Los resumenes usan etiquetas
como `EXPUESTO_BOLLINGER_INFERIOR@15m` para distinguir evidencia del mismo
detector sin modificar su `strategy_id` metodologico.

## Revisiones manuales

Cuando una estrategia requiera evidencia visual, registra cada revision con
`--review clave=si`, `--review clave=no` o `--review clave=pendiente`.

Ejemplo:

```powershell
.\venv\Scripts\python.exe validation_runner.py `
  --symbol SPY `
  --tf15 exports\SPY_2026-06-24_15m.txt `
  --tf1h exports\SPY_2026-06-24_1H.txt `
  --tf1d exports\SPY_2026-06-24_1D.txt `
  --review ct15.prior_trend=si `
  --review ct15.trendline_drawn=si `
  --review ct15.trendline_broken=si `
  --news-clear=si `
  --path-clear=si `
  --panorama-approved=si `
  --data-current=si `
  --output exports\validation_SPY_ct15.json
```

Aunque esas revisiones aprueben panorama y datos, el CLI no aprueba riesgo ni
gobierno operativo por defecto. Esa capa se revisa en la app, con la cotizacion
real del contrato y el plan de entrada/salida.

Para conservar una revision de Salto de Lateralidad en Hora, usa las claves
`lateral_jump.*`:

```powershell
.\venv\Scripts\python.exe validation_runner.py `
  --symbol SPY `
  --tf15 exports\SPY_2026-06-24_15m.txt `
  --tf1h exports\SPY_2026-06-24_1H.txt `
  --tf1d exports\SPY_2026-06-24_1D.txt `
  --review lateral_jump.lateral_channel=si `
  --review lateral_jump.breakout_or_gap=si `
  --review lateral_jump.near_hourly_ma20=si `
  --review lateral_jump.directional_volatility=si `
  --review lateral_jump.path_clear=si `
  --news-clear=si `
  --output exports\validation_SPY_salto_lateralidad.json
```

Si esa revision ya existe y quieres conservarla en el reporte reproducible,
puedes pasar los estados explicitos:

```powershell
.\venv\Scripts\python.exe validation_runner.py `
  --symbol SPY `
  --tf15 exports\SPY_2026-06-24_15m.txt `
  --tf1h exports\SPY_2026-06-24_1H.txt `
  --tf1d exports\SPY_2026-06-24_1D.txt `
  --risk-status APROBADO `
  --risk-option-type CALL `
  --governance-status APROBADO `
  --output exports\validation_SPY_ct15_complete.json
```

Los estados aceptados son `APROBADO`, `RECHAZADO`, `NO_DISPONIBLE` y
`REQUIERE_REVISION`. Si riesgo se marca como `APROBADO`, el tipo de opcion debe
coincidir con la direccion detectada; si no coincide, el motor conserva la
decision conservadora.
El tipo de opcion se normaliza a mayusculas y espacios recortados, pero solo se
aceptan `CALL` y `PUT`.
`--risk-option-type` solo debe enviarse cuando `--risk-status` es `APROBADO`;
para estados rechazados o pendientes, el contrato no se considera aprobado.

Para listar las claves aceptadas:

```powershell
.\venv\Scripts\python.exe validation_runner.py --list-reviews
```

El catalogo completo tambien esta documentado en
[`docs/MANUAL_REVIEW_CATALOG.md`](MANUAL_REVIEW_CATALOG.md). El validador
rechaza claves desconocidas para evitar errores silenciosos.

## Criterios de aceptacion por caso

Cada caso validado debe conservar:

1. archivos originales de TC2000;
2. captura o nota de la revision visual si hubo linea de tendencia;
3. JSON generado por `validation_runner.py`;
4. decision final de la app;
5. resultado posterior si se registro una operacion PAPER.

Un caso se considera util para aprendizaje solo si puede explicar:

- que estrategia detecto;
- que confirmaciones faltaron o se cumplieron;
- que invalidaciones estaban activas;
- si el panorama era claro o mixto;
- que riesgo se aprobo o rechazo;
- si la operacion respeto el plan.

## Regla critica

Si el JSON muestra detectores pero no hay riesgo y gobierno aprobados, el
resultado correcto es `NO_OPERAR`. Una validacion real no debe convertir una
deteccion aislada en entrada automatica.


