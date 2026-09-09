# Beta readiness report

Fecha de revision: 2026-07-23.

Version: `0.2.1-beta`.
Metodologia: `investep-draft-0.1`.

## Ensayo PAPER sintetico

`paper_rehearsal.py` recorre localmente persistencia de barras, cierre de 15
minutos, reconciliacion, clasificacion de alerta y acuse humano. Usa una base
temporal y queda incluido en `release_health_check.py`.

Este ensayo solo valida infraestructura. No valida la metodologia con mercado
real, no demuestra rentabilidad y no ejecuta ordenes.

`paper_session_evidence.py` queda preparado para consolidar el primer ensayo
Alpaca. Separa el estado actual del proceso de la evidencia historica, por lo
que el reporte puede completarse despues de detener el scanner. La aprobacion
requiere barras reales y reconciliacion aprobada para cada simbolo.

`scripts/run_first_paper_trial.ps1` une preflight, scanner en primer plano,
parada cooperativa, evidencia y limpieza de credenciales en un unico
procedimiento guiado.

La evidencia real queda aislada por sesion: el ultimo preflight remoto `LISTO`
define la frontera y no se reutilizan barras, heartbeat ni reconciliaciones
anteriores.

## Estado

Estado generado actual: `CODIGO_LISTO_ENTORNO_BLOQUEADO`.

JJTrade AI tiene salud de codigo `OK`; la cantidad de checks se obtiene del
reporte generado para evitar cifras manuales obsoletas. La
fuente TC2000 sigue disponible y el pipeline en vivo Alpaca ya cuenta con
preflight, backfill, WebSocket, reconciliacion REST, calendario, alertas,
aprendizaje, backup y control de proceso.

En esta maquina, el preflight local del 2026-07-23 aprobo simbolos, 365 dias de
backfill, feed IEX y SQLite. El unico bloqueo de entorno es que la sesion no
tiene `ALPACA_API_KEY` y `ALPACA_API_SECRET`. La red permanece `PENDIENTE`
porque el preflight seguro no abre conexiones.

La beta no esta lista para operar en automatico ni para retirar la etiqueta
beta. Las reglas ambiguas siguen bloqueadas por revision humana o por
`NO_DISPONIBLE`.

## Cobertura metodologica automatica

`methodology_coverage.py` cruza el pipeline, el registro central, el indice
maestro y el manifiesto de fuentes. El estado actual es estructuralmente `OK`:
18 IDs pertenecen a 9 detectores y no existen estrategias huerfanas.

Esto no significa metodologia completa. Solo Expuesto Bollinger figura como
`IMPLEMENTADA`; los otros 8 detectores conservan
`IMPLEMENTACION_PARCIAL` y confirmaciones obligatorias. El control forma parte
de `release_health_check.py` y bloquea el codigo si aparece una inconsistencia.

El pipeline tambien aplica el contrato durante cada ejecucion. Cada detector
declara sus IDs operativos y un ID diagnostico neutral `SIN_*`. Se descartan y
registran como error las salidas no declaradas, diagnosticos direccionales,
duplicados o temporalidades incoherentes antes de construir una decision.

Los minimos de historial por temporalidad tambien estan declarados. Si faltan
velas, el detector queda `skipped`; no se presenta como averia. Si con historial
suficiente falla por columnas, contrato o excepcion, la calidad efectiva queda
`RECHAZADO` y la decision obligatoriamente termina en `NO_OPERAR`.

Los fallos inesperados del scanner durante una vela de cierre tambien quedan
persistidos como incidentes operativos. Un incidente abierto degrada el estado
del panel y solo se resuelve con una vela posterior procesada correctamente
para el mismo simbolo. El historial conserva la recuperacion de forma auditable
y los detalles se sanean antes de escribirlos en SQLite.

La evidencia PAPER aplica la misma regla: cualquier incidente abierto para los
simbolos de la sesion produce `BLOQUEADO`. Los incidentes resueltos durante la
sesion se conservan en el reporte, que omite el texto del error y solo exporta
metadatos seguros y su huella de correlacion.

## Flujo PAPER en vivo recomendado

1. Ejecutar el lanzador seguro sin persistir credenciales:

```powershell
.\scripts\start_jjtrade_secure.ps1 -PreflightOnly
.\scripts\start_jjtrade_secure.ps1
```

2. Iniciar el scanner desde **Alertas de mercado**, confirmar estado
`LISTO_PAPER` y revisar cobertura por simbolo.

3. Mantener una sesion supervisada, acusar alertas y registrar resultados.

## Flujo beta TC2000 conservado

1. Copiar paquetes TC2000 en `exports\tc2000_cases` con nombres:

```text
SIMBOLO_FECHA_15m.txt
SIMBOLO_FECHA_1H.txt
SIMBOLO_FECHA_1D.txt
```

2. Ejecutar preflight + batch + auditoria + cola:

```powershell
.\venv\Scripts\python.exe validation_batch.py `
  --input-dir exports\tc2000_cases `
  --preflight-output-dir exports\tc2000_cases `
  --run-after-preflight `
  --output-dir exports\validation_batch `
  --standard-output-dir
```

3. Revisar:

- `exports\validation_batch\summary.csv`
- `exports\validation_batch\audit.csv`
- `exports\validation_batch\review_queue.csv`
- `exports\validation_batch\operator_board.csv`
- `exports\validation_batch\inspection.csv`
- `exports\validation_batch\reports\*.json`

4. Abrir la app:

```powershell
.\venv\Scripts\streamlit.exe run app.py
```

5. Usar la pestana **Auditoria** para subir reportes JSON, `operator_board.csv`,
`review_queue.csv` de lote o `case_intake.csv`, filtrar la cola de revision y
descargar vistas CSV cuando haga falta.

## Verificacion tecnica actual

Comando:

```powershell
.\venv\Scripts\python.exe -m unittest discover -s tests
```

El conteo de pruebas no se mantiene manualmente en este documento. El estado
actual se genera con:

```powershell
.\venv\Scripts\python.exe beta_status.py --output exports\beta_status.json
```

El artefacto incluye salud, cantidad de checks, preflight, proceso, bloqueos,
invariantes PAPER, aislamiento del aprendizaje, incidentes abiertos y estado de
validacion con mercado real, ademas del hito visual TC2000 multitemporal.
`code_health=OK` no equivale a evidencia real aprobada: esa afirmacion exige
`real_market_validation_status=APROBADO`. Cuando esa evidencia esta aprobada y
el scanner esta detenido, el estado es `BETA_PAPER_VALIDADA`. La auditoria
visual es posterior y opcional: `visual_evidence_status` se informa por
separado, pero nunca retrasa una señal en vivo.
`release_health_check.py --json` conserva el detalle de cada comando y el
resultado actual de la suite.

Comando de flujo beta ejecutado contra el paquete SPY disponible:

```text
Preflight generado: paquetes=1 inventario_incompleto=0 intake_incompleto=0
Paquetes validados: 1
```

## Artefactos del paquete beta actual

- Entrada: `exports\tc2000_cases\SPY_2026-06-21_15m.txt`,
  `SPY_2026-06-21_1H.txt`, `SPY_2026-06-21_1D.txt`
- Inventario: `exports\tc2000_cases\package_inventory.csv`
- Intake: `exports\tc2000_cases\case_intake.csv`
- Revision de intake: `exports\tc2000_cases\case_intake_check.csv`
- Resumen: `exports\validation_batch\summary.csv`
- Auditoria: `exports\validation_batch\audit.csv`
- Cola: `exports\validation_batch\review_queue.csv`
- Tablero operador: `exports\validation_batch\operator_board.csv`
- Inspeccion: `exports\validation_batch\inspection.csv`
- Reporte JSON: `exports\validation_batch\reports\SPY_2026-06-21.json`

Resultado esperado del caso beta: decision `NO_OPERAR`, preparacion
`INCOMPLETO`, aprendizaje `NO`, sesgo tentativo `CALL`.

## Bloqueos para version estable

Estos puntos no deben resolverse inventando valores:

- pesos cuantitativos entre Bollinger y medias;
- tabla o formula oficial para rango optimo de opciones;
- umbrales de tendencia, volatilidad, lateralidad y distancia a medias;
- automatizacion segura de lineas de tendencia;
- duracion valida de Momentum;
- universo y ventana de noticias;
- criterios para pasar de PAPER a REAL;
- validacion con varios simbolos y dias reales fuera de muestra.

## Regla final de beta

La beta debe preferir `NO_OPERAR`, `REQUIERE_REVISION` o `NO_DISPONIBLE` cuando
falta evidencia. Una deteccion parcial puede explicar sesgo tentativo, pero no
autoriza entrada hasta que estrategia, invalidaciones, panorama, riesgo y
gobierno operativo esten aprobados.
