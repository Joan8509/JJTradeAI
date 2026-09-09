# Operación del scanner en Windows

## Antes de iniciar

1. Ejecutar `live_strategy_service.py --preflight-only`.
2. Confirmar que el feed sea `iex` o `sip`.
3. Consultar `scanner_instance.py --status`.
4. Mantener Streamlit abierto solo como interfaz; no inicia otro scanner.

## Credenciales sin archivo

```powershell
.\scripts\start_jjtrade_secure.ps1 -PreflightOnly
.\scripts\start_jjtrade_secure.ps1
```

El lanzador solicita `ALPACA_API_KEY` y `ALPACA_API_SECRET` con
`Read-Host -AsSecureString`, convierte cada valor únicamente para el entorno
del proceso y libera la memoria BSTR inmediatamente. Al cerrar Streamlit elimina
las tres variables Alpaca. No crea `.env` ni persiste las credenciales.

Los diagnosticos que llegan desde preflight, WebSocket, REST, noticias,
reconciliacion o detectores pasan por un saneamiento comun antes de mostrarse o
persistirse. Las claves sensibles de estructuras JSON se reemplazan por
`[REDACTED]`; el heartbeat y los reportes no conservan el texto original.

## Instancia única

El proceso adquiere `exports/live_scanner.lock` antes del backup y de cualquier
consulta remota. El archivo contiene únicamente PID, fecha y un token aleatorio;
no contiene credenciales. Otro proceso con el mismo lock queda bloqueado con
código de salida 4.

Una salida normal, Ctrl+C o un error de calendario liberan el lease. Si el
proceso termina abruptamente, el siguiente arranque comprueba el PID y recupera
el archivo obsoleto. Un PID que todavía está activo se trata de forma
conservadora y nunca se reemplaza.

## Estado

```powershell
.\venv\Scripts\python.exe scanner_instance.py --status
```

Estados posibles: `ACTIVO`, `DETENIDO`, `LEASE_OBSOLETO` y `LEASE_INVALIDO`.
Antes de borrar manualmente un lock, se debe confirmar en el Administrador de
tareas que el PID indicado ya no corresponde al scanner.

## Inicio en segundo plano

```powershell
.\venv\Scripts\python.exe scanner_control.py start -- --symbols SPY,QQQ --days 365
```

Los argumentos posteriores a `--` se envían a `live_strategy_service.py`. El
proceso hereda las variables de entorno Alpaca de la consola actual, se inicia
sin ventana adicional y escribe stdout/stderr en
`exports/live_scanner.log`. Después del inicio se debe consultar `status` y el
panel operativo; que el proceso haya sido creado no garantiza que el preflight
remoto haya aprobado.

La pestaña **Alertas de mercado** ofrece los mismos controles dentro del
expander **Control del scanner**. El usuario define símbolos, días y si desea
activar la política de opciones. La interfaz construye una lista de argumentos
validada; no acepta comandos libres ni usa un shell. Los botones solo ejecutan
la acción después de un clic explícito y se actualizan cada 15 segundos.

## Parada cooperativa

```powershell
.\venv\Scripts\python.exe scanner_control.py stop
```

El controlador lee el token del lease activo y escribe una solicitud atómica.
El monitor interno valida ese token, llama `supervisor.stop()`, cierra el
WebSocket, registra `DETENIDO` y libera el lease. Una solicitud con token
incorrecto se ignora. No se usa `taskkill` ni se termina el proceso a la fuerza.

Para observar el registro:

```powershell
Get-Content exports\live_scanner.log -Wait
```

## Incidentes de procesamiento

Si el analisis de una vela de cierre de 15 minutos produce una excepcion
inesperada, el scanner conserva un incidente en SQLite y el panel cambia el
estado operativo a `DEGRADADO`. El registro incluye simbolo, vela, etapa, tipo
de error, detalle saneado y una huella para correlacion; no conserva
credenciales ni ejecuta ordenes.

Los errores controlados del contrato metodologico —por ejemplo, un detector que
devuelve un ID no declarado— tambien abren un incidente en la etapa
`DETECTORES`, aunque el reporte conservador termine en `NO_OPERAR`. Asi, un
fallo interno no se confunde con una ausencia legitima de estrategia.

Un incidente no desaparece por reiniciar el proceso. Solo queda resuelto cuando
el mismo simbolo procesa correctamente una vela de 15 minutos estrictamente
posterior. El panel **Incidentes de procesamiento** muestra tanto los abiertos
como el historial reciente, incluida la vela que demostro la recuperacion.
Antes de confiar en nuevas alertas se deben revisar la causa y la continuidad
de datos, aunque el estado haya vuelto a ser saludable.

Una vela repetida ignorada por deduplicacion no demuestra recuperacion: debe
existir un reporte nuevo, sin errores de detectores, para cerrar incidentes.

## Evidencia del primer ensayo con mercado real

El ciclo guiado recomendado es:

```powershell
.\scripts\run_first_paper_trial.ps1 `
  -Symbols "SPY,QQQ" `
  -Feed iex `
  -DurationMinutes 30
```

El proceso permanece en primer plano. Primero ejecuta el preflight local; si
este falla, no abre el scanner. Si aprueba, el scanner realiza su propia
comprobacion remota y se detiene automaticamente al completar la duracion.
Tambien puede solicitarse una parada desde otra terminal con
`.\venv\Scripts\python.exe scanner_control.py stop`. En todos los casos, el
bloque `finally` intenta consolidar la evidencia y elimina las variables
Alpaca del entorno del proceso.

La evidencia acumulada puede generarse con el scanner activo o despues de
detenerlo:

```powershell
.\venv\Scripts\python.exe paper_session_evidence.py `
  --database exports\market_data.db `
  --output exports\paper_session_evidence.json
```

La pestaña **Alertas de mercado** genera el mismo contrato y muestra sus checks
en **Validacion mercado real**. Desde allí puede descargarse
`paper_session_evidence.json`; la interfaz no modifica ni aprueba manualmente
los checks.

El estado `APROBADO` exige preflight remoto `LISTO`, heartbeat, al menos 15
barras `ALPACA` del feed activo y reconciliacion `APROBADO` con cero
diferencias y coherencia temporal por cada simbolo esperado. Tambien exige
cero incidentes de procesamiento abiertos para esos simbolos. Un
resultado `EN_CURSO` indica que la conexion fue aprobada pero aun falta alguna
evidencia. `BLOQUEADO` indica corrupcion SQLite o una reconciliacion rechazada.

Si SQLite no puede abrirse, leerse o decodificar un registro, el generador no
rompe la interfaz ni produce una aprobacion parcial: devuelve `BLOQUEADO`, omite
el detalle sensible y dirige a verificar o restaurar la base.

Los incidentes resueltos durante la sesion se incluyen como evidencia de
recuperacion. Los abiertos convierten el reporte en `BLOQUEADO`, incluso si las
barras y reconciliaciones ya cumplen. El JSON portable conserva tipo y huella,
pero omite el detalle del error.

Cada reporte queda acotado al ultimo preflight remoto `LISTO`. Solo cuentan el
heartbeat iniciado, las barras recibidas y las reconciliaciones creadas despues
de esa frontera. Evidencia de una sesion anterior no puede aprobar otra nueva.

El reporte omite el texto de errores del proveedor para evitar copiar datos
sensibles. No ejecuta ordenes ni autoriza el modo REAL.
