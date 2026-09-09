# JJTrade AI - Handoff operativo

Fecha de recuperacion: 2026-07-08.
Actualizado: 2026-07-14.

## Estado recuperado

El proyecto esta en `0.2.1-beta` con metodologia `investep-draft-0.1`.
El cierre operativo de beta esta resumido en
`docs/BETA_READINESS_REPORT.md`.
La preparacion para publicar en GitHub privado esta en
`docs/GITHUB_PRIVATE_PUBLISH_CHECKLIST.md`.

La base actual es un MVP funcional para:

- cargar archivos TXT/CSV exportados desde TC2000;
- evaluar 15m, 1H y 1D;
- correr detectores auditables para CT15, Primer Salto, Salto de Lateralidad en Hora, Efecto Iman, Rebote Punto Medio, Retorno Bollinger, Cambio de Tendencia en Hora, Momentum y Expuesto Bollinger;
- separar geometria preliminar, confirmaciones, invalidaciones, panorama, riesgo y gobierno operativo;
- exportar reportes JSON reproducibles;
- auditar reportes individuales y lotes;
- guardar analisis, auditorias y operaciones en diario local;
- mantener aprendizaje descriptivo separado entre PAPER y REAL.

## Verificacion tecnica

La suite completa pasa:

```powershell
.\venv\Scripts\python.exe -m unittest discover -s tests -v
```

El conteo cambia con cada incremento y se obtiene de la salida actual; no se
mantiene manualmente en este documento.

Versiones CLI verificadas:

```text
JJTrade AI 0.2.1-beta / investep-draft-0.1
```

Health check local verificado:

```powershell
.\venv\Scripts\python.exe release_health_check.py
```

El resultado y la cantidad vigente de checks se obtienen con `--json`; no se
mantienen manualmente en este documento.
Incluye `Prepublish check: OK (116 candidatos revisados)`.

Readiness GitHub actual:

```powershell
.\venv\Scripts\python.exe github_readiness.py
```

Resultado actual: `PENDIENTE`.
Faltan rama `main`, `git user.name`, `git user.email`, commit inicial y remoto
privado.

## Ultimo hito real

El ultimo bloque construido fue la beta validable, la usabilidad PAPER/REAL del
diario y el guardia pre-publicacion:

- `validation_runner.py` genera JSON reproducible por simbolo/sesion;
- `validation_batch.py` agrupa paquetes TC2000 por `SIMBOLO_FECHA_15m|1H|1D.txt`;
- `report_auditor.py` clasifica reportes como `LISTO`, `INCOMPLETO` o `BLOQUEADO`;
- la pestana **Auditoria** muestra cola de revision filtrable desde un JSON y
  permite descargarla como CSV;
- `strategy_summary`, `data_source`, `validation_package`, versiones y conteos de radar quedan preservados;
- la app muestra auditoria inmediata y conserva resumen de auditoria en analisis guardados.
- el diario filtra analisis, auditorias y operaciones cerradas, y compara
  resultados por modo sin mezclar PAPER y REAL;
- `prepublish_check.py` revisa candidatos de Git antes del primer commit para
  bloquear exports reales, DBs locales, secretos y artefactos operativos sin
  depender de mayusculas/minusculas, incluyendo `.env` y credenciales en
  subcarpetas.
  Tambien puede generar un manifiesto CSV local con `--manifest`.
- `release_health_check.py` ejecuta pruebas, guardia pre-publicacion y versiones
  CLI en una sola pasada; tambien puede emitir o guardar JSON con `--json` y
  `--output`.
- `github_readiness.py` audita identidad Git, commit inicial, remoto privado y
  candidatos bloqueados antes de publicar; tambien revisa que la rama sea
  `main`, imprime acciones sugeridas para cada item pendiente o bloqueado y
  puede emitir o guardar JSON con `--json` y `--output`.

Los artefactos existentes en `exports/` confirman ese estado:

- `exports/beta_e2e_report.json`
- `exports/validation_SPY_common_news_review.json`
- `exports/validation_SPY_salto_lateralidad.json`
- `exports/beta_batch_output/summary.csv`
- `exports/beta_batch_output/audit.csv`

## Resultado esperado de los casos beta

Los casos existentes terminan correctamente en `NO_OPERAR` porque faltan
compuertas reales:

- panorama: `REQUIERE_REVISION`;
- riesgo: `NO_DISPONIBLE`;
- gobierno operativo: `NO_DISPONIBLE`;
- noticias/datos pueden permanecer como invalidaciones pendientes si no fueron revisadas.

Esto no es un fallo: es la regla conservadora de la beta.

## Donde seguir

El siguiente avance recomendado es ampliar el primer set real de validacion:

1. Exportar desde TC2000 tres archivos por caso:
   - `SIMBOLO_FECHA_15m.txt`
   - `SIMBOLO_FECHA_1H.txt`
   - `SIMBOLO_FECHA_1D.txt`
2. Guardarlos en `exports/tc2000_cases/`.
3. Ejecutar el preflight:

```powershell
.\venv\Scripts\python.exe validation_batch.py `
  --input-dir exports\tc2000_cases `
  --preflight-output-dir exports\tc2000_cases
```

4. Si todos los paquetes quedan `LISTO`, ejecutar preflight + batch:

```powershell
.\venv\Scripts\python.exe validation_batch.py `
  --input-dir exports\tc2000_cases `
  --preflight-output-dir exports\tc2000_cases `
  --run-after-preflight `
  --output-dir exports\validation_batch `
  --standard-output-dir
```

5. Revisar `exports/validation_batch/summary.csv` y `audit.csv`.
6. Abrir en la app los casos que muestren geometria interesante para completar revisiones manuales.

## Batch estandar inicial

Se dejo creada la ruta estandar `exports/tc2000_cases/` y se ejecuto el flujo
contra el paquete beta de SPY para comprobar la salida final:

- entrada: `exports/tc2000_cases/SPY_2026-06-21_15m.txt`,
  `SPY_2026-06-21_1H.txt`, `SPY_2026-06-21_1D.txt`;
- salida: `exports/validation_batch/summary.csv`;
- auditoria: `exports/validation_batch/audit.csv`;
- cola de revision: `exports/validation_batch/review_queue.csv`;
- tablero operador: `exports/validation_batch/operator_board.csv`;
- reporte: `exports/validation_batch/reports/SPY_2026-06-21.json`.

Resultado esperado: `NO_OPERAR`, `readiness=INCOMPLETO`,
`learning_ready=NO`, `tentative_bias=CALL`, con primer pendiente
`panorama: REQUIERE_REVISION`.

Los `.txt` dentro de `exports/tc2000_cases/` son datos operativos exportados
desde TC2000 y quedan ignorados por `.gitignore`.

Tambien existe una plantilla de intake para registrar evidencia humana por caso:

```powershell
.\venv\Scripts\python.exe validation_batch.py `
  --write-intake-template exports\tc2000_cases\case_intake_template.csv
```

La plantilla conserva columnas para archivos por temporalidad, revision visual,
estado de riesgo/gobierno, resultado PAPER y notas del operador. No cambia la
decision automatica.

Para generar una hoja de intake desde los archivos que ya existen en la carpeta:

```powershell
.\venv\Scripts\python.exe validation_batch.py `
  --input-dir exports\tc2000_cases `
  --write-intake-from-input exports\tc2000_cases\case_intake.csv
```

Para inventariar paquetes antes de preparar intake:

```powershell
.\venv\Scripts\python.exe validation_batch.py `
  --input-dir exports\tc2000_cases `
  --write-package-inventory exports\tc2000_cases\package_inventory.csv
```

Camino recomendado actual: generar todos los controles previos en una sola
pasada:

```powershell
.\venv\Scripts\python.exe validation_batch.py `
  --input-dir exports\tc2000_cases `
  --preflight-output-dir exports\tc2000_cases
```

Ese comando crea `package_inventory.csv`, `case_intake.csv` y
`case_intake_check.csv`; si falta alguna temporalidad, devuelve error antes del
batch.

Para preflight + batch en una sola ejecucion:

```powershell
.\venv\Scripts\python.exe validation_batch.py `
  --input-dir exports\tc2000_cases `
  --preflight-output-dir exports\tc2000_cases `
  --run-after-preflight `
  --output-dir exports\validation_batch `
  --audit-output-csv exports\validation_batch\audit.csv `
  --review-output-csv exports\validation_batch\review_queue.csv `
  --operator-board-output-csv exports\validation_batch\operator_board.csv
```

Cuando el preflight quede `LISTO`, corre el batch con proteccion estricta:

```powershell
.\venv\Scripts\python.exe validation_batch.py `
  --input-dir exports\tc2000_cases `
  --output-dir exports\validation_batch `
  --require-complete-packages `
  --standard-output-dir
```

Tambien puede validarse contra los archivos presentes:

```powershell
.\venv\Scripts\python.exe validation_batch.py `
  --input-dir exports\tc2000_cases `
  --check-intake-csv exports\tc2000_cases\case_intake.csv `
  --intake-check-output-csv exports\tc2000_cases\case_intake_check.csv
```

La salida `case_intake_check.csv` muestra `LISTO` o `INCOMPLETO` por caso y
lista archivos faltantes o temporalidades no declaradas antes de correr el
batch.

Para regenerar auditoria y cola accionable desde reportes ya existentes:

```powershell
.\venv\Scripts\python.exe report_auditor.py `
  --reports-dir exports\validation_batch\reports `
  --output-csv exports\validation_batch\audit.csv `
  --output-review-csv exports\validation_batch\review_queue.csv
```

## Pendientes metodologicos principales

No se deben programar valores nuevos sin validacion de Joan. Los pendientes
actuales estan en `docs/METHODOLOGY_VALIDATION_MATRIX.md`:

- pesos cuantitativos Bollinger vs medias;
- rango optimo de opciones;
- umbrales de tendencia, volatilidad, lateralidad y distancia a medias;
- automatizacion de lineas de tendencia;
- duracion valida de Momentum;
- universo y ventana de noticias;
- criterios humanos para pasar de PAPER a REAL.

## Nota de repositorio

El repositorio Git fue reinicializado en `C:\JJTradeAI` despues de encontrar una
carpeta `.git` invalida. No se hizo commit inicial. Como el historial se perdio,
`git status --short` muestra la base como archivos sin trackear hasta que Joan
decida crear el primer commit.
