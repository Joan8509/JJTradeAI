# Guia rapida de uso

## 1. Abrir la app

```powershell
.\venv\Scripts\streamlit.exe run app.py
```

## 2. Cargar datos

En la pestana **Analisis**, carga exportaciones TC2000 de:

- 15 minutos
- Hora
- Diario

Los archivos deben corresponder al mismo simbolo y a la misma sesion. Si solo
quieres probar la interfaz, activa **Usar demostracion sintetica**. Esa demo no
representa mercado real.

La carga rechaza fechas invalidas, columnas requeridas vacias o valores
numericos negativos.

La pantalla muestra la ultima sesion y cantidad de velas por temporalidad para
ayudarte a detectar exportaciones desalineadas o incompletas antes de revisar
estrategias.

### Mercado real en PAPER

En **Alertas de mercado**, el bloque **Preparacion PAPER** indica si el scanner
puede iniciar o continuar de forma supervisada. El bloque **Validacion mercado
real** responde otra pregunta: si la sesion ya acumulo evidencia suficiente
para demostrar preflight remoto, heartbeat, barras Alpaca, reconciliacion y
ausencia de incidentes abiertos.

`LISTO_PAPER` no equivale a evidencia `APROBADO`. Abre **Checks de evidencia
PAPER real** para identificar exactamente que falta y descarga el JSON para
conservar la prueba de la sesion. Ninguno de esos estados ejecuta ordenes ni
autoriza modo REAL.

## 3. Completar revisiones

La app muestra primero el **Radar de detectores**, donde cada estrategia indica
su categoria, si fue detectada, su sesgo inicial, si requiere confirmacion,
cumplimiento, requisitos completos, pendientes, fallidos y la siguiente
revision obligatoria que impide confirmar la estrategia.

Cada estrategia muestra criterios objetivos y revisiones manuales. Usa:

- `SI` si lo verificaste en el grafico o fuente externa;
- `NO` si no se cumple;
- `PENDIENTE` si no lo revisaste.

`PENDIENTE` bloquea la confirmacion. La app prefiere `NO_OPERAR` antes que
asumir una condicion no verificada.

## 4. Evaluar riesgo

En **Riesgo de opciones**, introduce la cotizacion del contrato y activa solo
los limites que formen parte de tu plan aprobado. Si falta un limite, riesgo
queda `NO_DISPONIBLE`.

La compuerta queda vinculada al simbolo, contrato, direccion y limites. Si
cambias esos datos, la aprobacion se reinicia.

## 5. Aprobar plan operativo

En **Plan operativo**, define modo `PAPER` o `REAL`, radar, flujo, entrada y
salida. El conteo semanal se toma del diario, no se escribe manualmente.

Una aprobacion de gestion de posicion no habilita una nueva entrada.

## 6. Leer la decision

La pestana **Analisis** solo puede mostrar `CALL` o `PUT` cuando se cumplen:

1. estrategia detectada y confirmada;
2. sin invalidaciones activas;
3. panorama aprobado;
4. riesgo aprobado para la misma direccion;
5. plan operativo aprobado para el simbolo;
6. datos alineados.

Si falta algo, el resultado correcto es `NO_OPERAR`.

Cuando la app detecta una geometria todavia incompleta, puede mostrar un
**sesgo tentativo** hacia `CALL` o `PUT`. Eso solo indica direccion preliminar
para revisar; no es una recomendacion operable hasta que aparezca en
**Estrategias que sostienen la direccion** y pasen todas las compuertas.

## 7. Guardar y aprender

Guarda el analisis en el diario. Si operas, registra contrato, planes y razon
si decidiste apartarte de la decision. Tambien debes justificar una operacion
basada en un analisis `INCOMPLETO` o `BLOQUEADO`, aunque la accion coincida con
`CALL` o `PUT`; la pestana **Diario** lo advierte al seleccionar ese analisis.

Al cerrar operaciones, la app calcula metricas descriptivas separadas entre
PAPER y REAL, incluyendo si la operacion siguio la decision original o fue una
excepcion humana.

En resultados de alertas, el modo aparece bloqueado porque se deriva del
gobierno versionado de la reevaluacion. Si no se vinculo gobierno, solo se
admite `PAPER`; para registrar `REAL` debe existir una revision de gobierno
`REAL` perteneciente a esa misma alerta.

Los analisis recientes conservan tambien el sesgo tentativo y sus estrategias
cuando existian, para diferenciar casos incompletos de decisiones confirmadas.
Tambien conservan la fuente de datos usada y muestran el resumen de auditoria
inmediata cuando el reporte los incluye.

En **Diario**, los analisis recientes se pueden filtrar por simbolo, decision
y estado de auditoria. Tambien puedes descargar la vista filtrada como CSV para
revisar una sesion PAPER fuera de la app.

Las operaciones cerradas se muestran en una tabla separada con filtros por modo,
simbolo y decision del analisis. La app resume resultados por modo y si la
operacion siguio la decision original; esa comparacion es descriptiva y no
calibra confianza.

Estas estadisticas no garantizan resultados futuros y no modifican las reglas
oficiales automaticamente.

## 8. Auditar reportes

La pestana **Analisis** muestra una auditoria inmediata del reporte recien
generado antes de exportarlo o guardarlo. Esa revision resume preparacion,
faltantes, bloqueos, estrategias detectadas y si el caso esta listo para
aprendizaje PAPER.

En la pestana **Auditoria**, sube un JSON generado por la app,
`validation_runner.py` o `validation_batch.py`.

La auditoria clasifica el reporte como:

- `LISTO_REVISION`
- `INCOMPLETO`
- `BLOQUEADO`

Tambien permite subir una **cola de revision** CSV generada por el lote. La app
muestra conteos por filas, paquetes, bloqueos y faltantes, y permite filtrar por
prioridad, tipo y paquete. Esa cola convierte cada faltante o bloqueo en una
fila accionable, por ejemplo panorama, riesgo, gobierno, invalidacion pendiente
o criterio de estrategia. Puedes descargar la vista filtrada como CSV desde la
misma pestana.

Tambien puedes subir `case_intake.csv` para revisar el estado de observaciones
humanas por paquete. La app resume casos, simbolos, pendientes de intake y
riesgo aprobado, y permite descargar una vista resumida.

Si generaste `operator_board.csv`, puedes subirlo en la misma pestana para ver
una fila por paquete con decision, readiness, learning ready, primer pendiente,
primer bloqueo y conteos agregados. Esta vista sirve para priorizar paquetes; no
aprueba ninguna compuerta.

La pestana tambien muestra evidencia faltante, bloqueos, estrategias detectadas
y si el caso tiene evidencia suficiente para revision PAPER. No cambia la
decision original.

Si quieres conservar evidencia, usa **Guardar auditoria en el diario**. Las
auditorias guardadas aparecen luego en la pestana **Diario**, separadas de las
operaciones reales o PAPER. La tabla de auditorias recientes muestra tambien el
primer pendiente o bloqueo para decidir rapido que revisar.
