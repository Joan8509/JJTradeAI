# JJTrade AI

Herramienta local de decision asistida basada en la metodologia Investep.

Version actual: **0.2.1-beta**.

## Estado actual

El proyecto dispone de un MVP funcional para:

- Cargar TXT/CSV exportados desde TC2000 para 15m, Hora y Diario.
- Calcular y visualizar Bollinger.
- Detectar Expuesto en Bollinger sin convertirlo en entrada automatica.
- Evaluar un radar de detectores prioritarios implementados total o
  parcialmente: CT15, Primer Salto, Salto de Lateralidad en Hora, Efecto Iman,
  Rebote en Punto Medio, Retorno a Bollinger, Cambio de Tendencia en Hora y
  Momentum.
- Mostrar por detector si hubo geometria, sesgo, cumplimiento, requisitos
  completos, pendientes y fallidos.
- Separar sesgo tentativo de estrategias confirmadas para explicar `NO_OPERAR`
  sin convertir una deteccion incompleta en entrada.
- Mostrar criterios, motivos y fuentes.
- Evaluar spread, spot/strike, vencimiento y costo con limites configurables.
- Guardar analisis y resultados en un diario SQLite local.
- Registrar planes, excepciones humanas y resultados PAPER/REAL por separado.
- Calcular metricas descriptivas sin modificar automaticamente la metodologia.
- Evaluar disciplina operativa: modo PAPER, radar, limite semanal y planes.
- Producir `NO_OPERAR` cuando faltan confirmaciones, panorama o riesgo.

Las demas estrategias estan en proceso de formalizacion. Primer Salto continua
en validacion y no puede autorizar una operacion por si solo.

## Instalacion

```powershell
python -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
```

## Ejecutar la app

```powershell
.\venv\Scripts\streamlit.exe run app.py
```

Abrir `http://localhost:8501` si el navegador no se inicia automaticamente.

## Probar datos de mercado Alpaca

La primera integracion de solo lectura admite historial y barras de un minuto
por WebSocket. Configura `ALPACA_API_KEY`, `ALPACA_API_SECRET` y opcionalmente
`ALPACA_DATA_FEED` (`iex`, `sip` o `delayed_sip`) como variables de entorno.

```powershell
.\venv\Scripts\python.exe market_data_probe.py --symbol SPY --days 10
.\venv\Scripts\python.exe market_data_probe.py --symbol SPY --stream
```

El adaptador no ejecuta ordenes.

Para comparar IEX con SIP historico retrasado sin ejecutar ordenes:

```powershell
.\scripts\run_feed_comparison.ps1 -Symbols "SPY,QQQ"
```

El resultado se guarda en `exports/feed_comparison.json` y reporta diferencias
de OHLCV y detectores. La comparacion es descriptiva y no autoriza operaciones.

Para mantener el scanner activo y guardar una alerta al cierre de cada vela de
15 minutos:

```powershell
.\venv\Scripts\python.exe live_strategy_service.py --symbols SPY,QQQ --days 365
```

Antes de abrir conexiones puedes ejecutar unicamente el diagnostico local:

```powershell
.\venv\Scripts\python.exe live_strategy_service.py --symbols SPY,QQQ --days 365 --preflight-only
```

El preflight valida simbolos, credenciales presentes, feed en tiempo real,
escritura e integridad SQLite y la politica opcional de opciones. No imprime
las claves y conserva el resultado en `live_preflight_runs`. La conectividad y
el calendario oficial se verifican despues, antes del backfill y del WebSocket.

Antes de cada arranque normal, el scanner crea un backup SQLite verificado en
`exports/backups` y conserva 30 copias por defecto. Para crear o verificar una
copia manualmente:

```powershell
.\venv\Scripts\python.exe database_backup.py exports\market_data.db --retention 30
.\venv\Scripts\python.exe database_backup.py --verify exports\backups\market_data_FECHA.db
```

El mismo arranque crea `market_data_FECHA.visual.zip` con las capturas
referidas por ese snapshot. Cada paquete visual conserva la huella del backup
SQLite y bloquea archivos faltantes o modificados. La restauracion conservadora
se realiza con `visual_evidence_backup.py`; nunca sobrescribe contenido
diferente.

La coherencia entre estrategias, detectores, documentos y fuentes se verifica
con:

```powershell
.\venv\Scripts\python.exe methodology_coverage.py `
  --output exports\methodology_coverage.json
```

Un detector sin documento, fuente, temporalidad valida o confirmacion
obligatoria queda bloqueado por el health check.

Las invariantes de seguridad PAPER se verifican de forma independiente:

```powershell
.\venv\Scripts\python.exe safety_invariants.py `
  --output exports\safety_invariants.json
```

El control bloquea importaciones de clientes de trading, llamadas o endpoints
de mutacion de ordenes y dependencias directas o indirectas desde los modulos
de decision hacia el aprendizaje descriptivo. Tambien forma parte de
`release_health_check.py`.

Durante el analisis, cada detector solo puede emitir los IDs operativos y
diagnosticos neutrales declarados. Una salida desconocida, duplicada o con
temporalidad incorrecta queda registrada como error del detector y no alcanza
el motor de decision.

Los minimos de historial son parte del registro. Una muestra corta omite el
detector de forma explicita; un error real del detector rechaza calidad de datos
y fuerza `NO_OPERAR`, aunque otra estrategia aparezca confirmada.

Cada copia tiene un manifiesto JSON con integridad, tamano y SHA-256. El
directorio completo esta excluido de Git y bloqueado por el prepublish check.

El scanner usa `exports/live_scanner.lock` para impedir dos instancias sobre la
misma base. Consulta el estado sin mostrar credenciales:

```powershell
.\venv\Scripts\python.exe scanner_instance.py --status
```

Si el PID sigue activo, un segundo arranque queda bloqueado. Si el proceso
murio, el siguiente arranque recupera automaticamente el lease obsoleto. El
archivo lock tambien esta excluido de Git.

En Windows puede iniciarse en segundo plano y detenerse cooperativamente:

```powershell
.\venv\Scripts\python.exe scanner_control.py start -- --symbols SPY,QQQ --days 365
.\venv\Scripts\python.exe scanner_control.py status
.\venv\Scripts\python.exe scanner_control.py stop
```

La salida queda en `exports/live_scanner.log`. `stop` no mata el proceso:
solicita al supervisor cerrar el WebSocket, marcar salud `DETENIDO` y liberar
el lease. Los archivos `.log`, `.lock` y `.stop` estan excluidos de Git.

Los errores inesperados al analizar cierres de 15 minutos crean incidentes
persistentes en SQLite. Mientras exista alguno abierto para los simbolos
vigilados, el panel muestra estado `DEGRADADO`. El incidente solo se resuelve
despues de procesar correctamente una vela posterior del mismo simbolo; el
detalle almacenado se sanea para no copiar secretos.

La misma compuerta protege `paper_session_evidence.py`: una sesion no puede
quedar `APROBADO` con incidentes abiertos. Los incidentes recuperados quedan
incluidos en el reporte sin exportar su texto de error.

Los errores internos que el pipeline captura y convierte en `NO_OPERAR` tambien
se registran como incidentes de etapa `DETECTORES`. Solo un analisis posterior
realmente ejecutado y sin esos errores demuestra recuperacion; una vela
duplicada no basta.

Para abrir JJTrade AI sin guardar credenciales en archivos, usa el lanzador
seguro. PowerShell solicita key y secret de forma oculta, los mantiene solo en
el entorno del proceso y los elimina al cerrar:

```powershell
.\scripts\start_jjtrade_secure.ps1 -PreflightOnly
.\scripts\start_jjtrade_secure.ps1
```

El scanner iniciado desde Streamlit hereda esas variables. El script nunca
escribe los valores en `.env`, JSON, logs o SQLite.

Como defensa adicional, los errores de preflight, heartbeat, WebSocket, REST,
noticias, reconciliacion e incidentes se sanean con una politica comun antes de
mostrarse o persistirse. Los campos JSON con nombres sensibles se redactan de
forma recursiva.

Para restaurar, detiene primero el scanner y Streamlit. Conserva juntos el
archivo `.db` y su manifiesto `.json`. Un destino existente nunca se reemplaza
sin `--overwrite`; al autorizarlo se crea antes otro backup de seguridad:

```powershell
.\venv\Scripts\python.exe database_backup.py `
  --restore exports\backups\market_data_FECHA.db `
  --target exports\market_data_restored.db
```

```powershell
.\venv\Scripts\python.exe database_backup.py `
  --restore exports\backups\market_data_FECHA.db `
  --target exports\market_data.db `
  --overwrite
```

Las alertas se conservan en `exports/market_data.db`. El proceso evalua
estrategias, pero no contiene ningun endpoint de ejecucion de ordenes.

La pestana **Riesgo de opciones** puede consultar la cadena Alpaca despues de
configurar todos los limites de riesgo. Filtra vencimientos y strikes, muestra
griegas y liquidez, y solo marca elegibles las cotizaciones OPRA que aprueban
todas las compuertas. El feed `indicative` se conserva para desarrollo, pero no
se trata como precio ejecutable.

Para enriquecer alertas automaticas con candidatos, copia
`config/option_policy.example.json` como `config/option_policy.json`, sustituye
todos los valores `null` por limites aprobados y ejecuta:

```powershell
.\venv\Scripts\python.exe live_strategy_service.py `
  --symbols SPY,QQQ `
  --days 365 `
  --option-policy config\option_policy.json
```

Sin `--option-policy`, el scanner no consulta opciones. El archivo operativo se
excluye de Git para evitar publicar parametros privados por accidente.

El proceso en vivo se reconecta automaticamente con espera progresiva y hace
backfill REST antes de cada intento. La pestana **Alertas en vivo** muestra su
estado, ultima vela, reconexiones y ultimo error sin exponer credenciales.

Cada alerta incluye una compuerta de frescura. Los feeds retrasados, barras con
mas de tres minutos, timestamps futuros o eventos no confirmados en SQLite no
se consideran datos actuales y mantienen bloqueada la decision.

Las velas parciales de Hora y Diario se excluyen del motor. La trazabilidad de
la fuente muestra `closed_through` para 15m, 1H y 1D, indicando el ultimo cierre
confirmado utilizado en cada temporalidad.

El bundle Alpaca conserva ademas las barras cerradas de 1 minuto como datos
auxiliares internos. No constituyen una cuarta temporalidad de entrada: se usan
solo para comprobar la reaccion de los primeros cinco minutos en Retorno a
Bollinger y no alteran los reportes multitemporales.

Los cierres se obtienen del calendario oficial Alpaca, que contempla feriados
y sesiones abreviadas. Si el calendario no puede verificarse, la fuente Alpaca
no inicia el analisis con un cierre horario inventado.

El scanner recibe por defecto SPY, QQQ, IWM y DIA como benchmarks de contexto.
Puedes cambiarlos con `--benchmarks`. Su direccion y sincronizacion se adjuntan
a la alerta, sin aprobar automaticamente la compuerta de panorama.

Cada alerta consulta tambien titulares recientes del simbolo. La evidencia es
descriptiva y siempre requiere revision humana; el programa no infiere tono ni
declara automaticamente que una noticia invalida la operacion.

Para recorrer toda la interfaz sin archivos, activa **Usar demostracion
sintetica**. Sus resultados son educativos y no representan ningun activo.

## Ejecutar pruebas

```powershell
.\venv\Scripts\python.exe -m unittest discover -s tests -v
```

Antes de publicar o hacer el primer commit privado, revisa que no entren datos
operativos, secretos ni artefactos locales:

```powershell
.\venv\Scripts\python.exe prepublish_check.py
```

Para una verificacion local completa de release:

```powershell
.\venv\Scripts\python.exe release_health_check.py
```

Para guardar esa verificacion como dato estructurado:

```powershell
.\venv\Scripts\python.exe release_health_check.py --json
.\venv\Scripts\python.exe release_health_check.py --output exports\release_health.json
```

Para separar salud de codigo, entorno, incidentes y validacion de mercado real:

```powershell
.\venv\Scripts\python.exe beta_status.py `
  --output exports\beta_status.json
```

`code_health=OK` no significa que el mercado real ya fue validado. Ese hito
solo queda demostrado cuando `real_market_validation_status=APROBADO`; el mismo
reporte expone seguridad PAPER, aislamiento del aprendizaje e incidentes
abiertos.

Para revisar que falta antes de crear el primer repo privado en GitHub:

```powershell
.\venv\Scripts\python.exe github_readiness.py
```

Si quieres guardar esa revision como dato estructurado:

```powershell
.\venv\Scripts\python.exe github_readiness.py --json
.\venv\Scripts\python.exe github_readiness.py --output exports\github_readiness.json
```

## Validar exportaciones reales

Para generar un reporte JSON reproducible con archivos TC2000 reales:

```powershell
.\venv\Scripts\python.exe validation_runner.py `
  --symbol SPY `
  --tf15 exports\SPY_15m.txt `
  --tf1h exports\SPY_1H.txt `
  --tf1d exports\SPY_1D.txt `
  --output exports\validation_SPY.json
```

Los CLIs principales aceptan `--version` para confirmar version de app y
metodologia antes de generar artefactos.

El validador usa el mismo motor que la interfaz. Por seguridad, no aprueba
riesgo ni gobierno operativo automaticamente; si faltan esas compuertas, la
decision final esperada es `NO_OPERAR`.

Cuando ya exista una revision externa de riesgo y gobierno, puedes registrarla
en el JSON con `--risk-status`, `--risk-option-type` y `--governance-status`.
Los estados aceptados son `APROBADO`, `RECHAZADO`, `NO_DISPONIBLE` y
`REQUIERE_REVISION`.

Para validar una carpeta completa de casos con nombres
`SIMBOLO_FECHA_15m|1H|1D.txt`, primero corre el preflight. Este genera
`package_inventory.csv`, `case_intake.csv` y `case_intake_check.csv`, y se
detiene si falta alguna temporalidad requerida:

```powershell
.\venv\Scripts\python.exe validation_batch.py `
  --input-dir exports\tc2000_cases `
  --preflight-output-dir exports\tc2000_cases
```

El flujo recomendado para generar controles y ejecutar el lote en una sola
pasada es:

```powershell
.\venv\Scripts\python.exe validation_batch.py `
  --input-dir exports\tc2000_cases `
  --preflight-output-dir exports\tc2000_cases `
  --run-after-preflight `
  --output-dir exports\validation_batch `
  --standard-output-dir
```

Tambien puedes ejecutar solo el batch estricto, siempre rechazando paquetes sin
15m, 1H y 1D:

```powershell
.\venv\Scripts\python.exe validation_batch.py `
  --input-dir exports\tc2000_cases `
  --output-dir exports\validation_batch `
  --require-complete-packages `
  --standard-output-dir
```

Cada reporte de lote conserva `validation_package`, y el `summary.csv` y
`audit.csv` comparten `package_id` para cruzar resultados, auditoria y archivos
fuente.
Con `--standard-output-dir`, el lote genera tambien `review_queue.csv` y
`operator_board.csv` dentro de `exports\validation_batch`.

Para inspeccionar que la salida estandar quedo completa:

```powershell
.\venv\Scripts\python.exe validation_batch.py `
  --inspect-output-dir exports\validation_batch `
  --inspection-output-csv exports\validation_batch\inspection.csv
```

Para auditar reportes ya generados y ver que evidencia falta:

```powershell
.\venv\Scripts\python.exe report_auditor.py `
  --reports-dir exports\validation_batch\reports `
  --output-csv exports\validation_batch\audit.csv `
  --output-review-csv exports\validation_batch\review_queue.csv
```

`review_queue.csv` expande cada faltante o bloqueo en una fila filtrable por
prioridad, simbolo, compuerta, invalidacion o estrategia. `operator_board.csv`
resume una fila por paquete con decision, readiness, primer pendiente y
bloqueos.

## Datos TC2000

La exportacion inicial requiere:

- Date
- Open
- High
- Low
- Close
- Moving Average 20
- Moving Average 40
- Moving Average 100
- Moving Average 200
- Volume
- Worden Stochastics

Para obtener panorama completo, exporta el mismo simbolo por separado en 15
minutos, Hora y Diario y carga cada archivo en su campo correspondiente.
Las columnas numericas requeridas no pueden venir vacias, no numericas ni con
valores negativos.

## Seguridad metodologica

JJTrade AI no ejecuta ordenes y no garantiza rentabilidad. Una deteccion solo
puede llegar a `CALL` o `PUT` despues de aprobar requisitos, confirmaciones,
invalidaciones, panorama y riesgo. Los limites no documentados permanecen como
`NO_DISPONIBLE`.

Si una configuracion apunta preliminarmente a una direccion pero todavia tiene
requisitos pendientes, la app puede mostrar `tentative_bias` en el reporte. Ese
campo es explicativo y conserva la decision final en `NO_OPERAR`.

La decision final se calcula mediante un unico servicio end-to-end que aplica:

`calidad de datos -> detectores -> confirmaciones -> invalidaciones -> panorama -> riesgo -> gobierno operativo -> decision`

## Ensayo PAPER local

Antes de conectar credenciales se puede recorrer localmente la infraestructura
de ingestion, cierre de 15 minutos, reconciliacion, alerta y acuse:

```powershell
.\venv\Scripts\python.exe paper_rehearsal.py
```

El ensayo usa datos sinteticos y una base temporal. Su resultado comprueba la
infraestructura, pero no valida estrategias, mercado real, rentabilidad ni
ejecucion de ordenes.

Despues de una sesion con Alpaca, la evidencia persistida se consolida con:

```powershell
.\venv\Scripts\python.exe paper_session_evidence.py `
  --output exports\paper_session_evidence.json
```

La aprobacion requiere un preflight remoto `LISTO`, heartbeat observado, al
menos 15 barras del proveedor `ALPACA` y reconciliacion `APROBADO`, sin
diferencias y temporalmente coherente, para cada simbolo. El reporte no incluye
credenciales y sigue sin autorizar trading real.

La captura se delimita por el ultimo preflight remoto aprobado: datos recibidos
antes de ese momento quedan fuera para impedir reutilizar evidencia antigua.

## Evidencia visual TC2000

En el detalle de una alerta se puede adjuntar una captura PNG o JPEG de TC2000
para 15m, 1H o 1D. La app valida formato, tamano y dimensiones, guarda el
archivo localmente por SHA-256 y permite versionar revisiones `COINCIDE`,
`DIFIERE` o `NO_EVALUABLE`.

La captura es evidencia complementaria. No reemplaza los datos API, no cambia
la alerta original y no autoriza una operacion.

La app audita nuevamente existencia, SHA-256, bytes, formato y dimensiones, y
permite descargar un manifiesto JSON por alerta. Un archivo faltante o alterado
queda `BLOQUEADO_ARCHIVOS`.

Si se adjuntan capturas, la reevaluacion congela sus hashes y revisiones. Una
discrepancia o revision pendiente conserva `NO_OPERAR`; una revision humana
anterior a la captura debe renovarse. Sin capturas, esta capa queda `OMITIDO`.

Para ejecutar por primera vez el ciclo completo en primer plano:

```powershell
.\scripts\run_first_paper_trial.ps1
```

El lanzador solicita las credenciales de forma enmascarada, valida la
configuracion, mantiene el scanner visible durante 30 minutos por defecto,
lo detiene cooperativamente, genera la evidencia y elimina las variables
sensibles al terminar. La duracion puede cambiarse con `-DurationMinutes`.

## Documentacion

- [Requisitos del producto](docs/PRODUCT_REQUIREMENTS.md)
- [Guia rapida de uso](docs/USER_GUIDE.md)
- [Reporte de preparacion beta](docs/BETA_READINESS_REPORT.md)
- [Roadmap post-beta](docs/POST_BETA_ROADMAP.md)
- [Checklist para publicar en GitHub privado](docs/GITHUB_PRIVATE_PUBLISH_CHECKLIST.md)
- [Protocolo de validacion con datos reales](docs/VALIDATION_PROTOCOL.md)
- [Auditoria de reportes](docs/REPORT_AUDIT.md)
- [Catalogo de revisiones manuales](docs/MANUAL_REVIEW_CATALOG.md)
- [Pipeline de analisis](docs/analysis_pipeline.md)
- [Gobierno de riesgo y disciplina](docs/RISK_GOVERNANCE.md)
- [Aprendizaje controlado](docs/LEARNING_MODEL.md)
- [Roadmap de fuentes de datos](docs/DATA_PROVIDER_ROADMAP.md)
- [Indice maestro](docs/MASTER_STRATEGIES_INDEX.md)
- [Fuentes metodologicas](docs/SOURCE_MANIFEST.md)
- [Cobertura metodologica](docs/MASTER_STRATEGIES_INDEX.md)
- [Lecciones aprendidas](docs/LESSONS_LEARNED.md)
- [Checklist y limitaciones de la version beta](docs/RELEASE_CHECKLIST.md)


