# Release Checklist - 0.2.1-beta

## Capacidades verificadas

- Carga y normalizacion de TXT/CSV TC2000.
- Calculo explicito de Bollinger y metricas de salto.
- Validacion de integridad y sincronizacion multitemporal.
- Detectores parciales auditables para las estrategias prioritarias.
- Detector parcial para Salto de Lateralidad en Hora incorporado desde la clase nueva de repaso.
- Confirmaciones ternarias y criterios con fuente.
- Invalidaciones, panorama y mapa de medias moviles.
- Riesgo configurable sin limites inventados.
- Gobierno PAPER/REAL y planes obligatorios.
- Decision final conservadora `CALL`, `PUT` o `NO_OPERAR`.
- Diario SQLite, operaciones abiertas/cerradas y excepciones humanas.
- Estadisticas PAPER/REAL y aprendizaje descriptivo controlado.
- Exportacion JSON completa.
- Auditoria inmediata del reporte en la pestana de analisis.
- Resumen de auditoria inmediata preservado en analisis guardados.
- Resumen de radar en JSON, auditoria, diario y validacion por lote.
- Conteo de velas por temporalidad en calidad de datos.
- Validador CLI reproducible para paquetes TC2000 reales.
- Auditoria CSV opcional generada desde la validacion por lote.
- Cola CSV opcional de revision humana generada desde auditoria, con una fila
  por faltante o bloqueo.
- Trazabilidad de paquete batch preservada en JSON, summary y auditoria CSV.
- Preflight de paquetes TC2000 con inventario, intake y verificacion de
  temporalidades antes del batch.
- Ejecucion `preflight + batch` en un solo comando con bloqueo si faltan 15m,
  1H o 1D.
- El batch puede emitir `summary.csv`, `audit.csv` y `review_queue.csv` en la
  misma corrida.
- Trazabilidad de fuente de datos normalizada en app, runner y batch sin
  credenciales ni metadatos arbitrarios.
- Demostracion sintetica inequivocamente marcada.
- Datos Alpaca por REST y WebSocket con backfill, calendario, frescura y
  reconciliacion por simbolo.
- Evidencia visual TC2000 versionada, auditada y respaldada.
- Auditor automatico de cobertura entre 18 IDs de estrategia, 9 detectores,
  documentos y fuentes Investep.
- Contrato de salida en runtime para impedir IDs no declarados, diagnosticos
  direccionales, duplicados y temporalidades incorrectas.
- Separacion entre historial insuficiente (`skipped`) y fallo interno
  (`errors`); cualquier error interno rechaza la compuerta de calidad.
- Incidentes de procesamiento persistentes: degradan el panel, exigen una vela
  posterior para demostrar recuperacion y bloquean la aprobacion de evidencia
  PAPER mientras permanezcan abiertos.
- Panel y JSON de evidencia PAPER real con checks descargables; un fallo de
  lectura o corrupcion SQLite produce `BLOQUEADO` en vez de romper la interfaz.
- Errores controlados del contrato de detectores abren incidentes metodologicos;
  una vela duplicada no puede cerrar un incidente sin producir un reporte nuevo.
- Saneamiento comun de diagnosticos para consola, heartbeat, preflight,
  noticias, reconciliacion e incidentes, incluida redaccion recursiva de claves
  sensibles antes de persistir JSON.
- Verificador estatico de invariantes PAPER: bloquea clientes, endpoints y
  llamadas de ejecucion de ordenes, y dependencias directas o transitivas desde
  el motor de decision hacia los modulos de aprendizaje descriptivo.
- Asesoria descriptiva V2 aislada por version metodologica y protegida contra
  fuga temporal mediante `evento <= registro <= alerta`.
- Resultados PAPER/REAL ligados al modo de gobierno de la misma alerta; IDs
  cruzados y resultados REAL sin gobierno REAL se rechazan.
- Auditor visual agregado: exige un caso con 15m, 1H y 1D integros y revisados
  como `COINCIDE`, sin convertir esa evidencia en decision operativa.

## Comando de verificacion

Antes de cerrar una beta o publicar en GitHub privado:

```powershell
.\venv\Scripts\python.exe release_health_check.py
```

Este comando ejecuta pruebas unitarias, guardia pre-publicacion y versiones CLI.
Usa `--json` o `--output exports\release_health.json` si necesitas conservar la
verificacion en formato estructurado.

La cobertura metodologica tambien puede inspeccionarse directamente:

```powershell
.\venv\Scripts\python.exe methodology_coverage.py `
  --output exports\methodology_coverage.json
```

Las invariantes PAPER y de aislamiento del aprendizaje pueden auditarse con:

```powershell
.\venv\Scripts\python.exe safety_invariants.py `
  --output exports\safety_invariants.json
```

Para revisar si el proyecto ya esta listo para el primer push privado:

```powershell
.\venv\Scripts\python.exe github_readiness.py
```

Ese chequeo puede quedar `PENDIENTE` aunque la beta este sana, por ejemplo si
todavia falta configurar identidad Git, renombrar la rama a `main`, crear el
commit inicial o conectar el remoto privado. Tambien puede quedar `BLOQUEADO`
si encuentra candidatos inseguros para publicar.

Usa `--output exports\github_readiness.json` si quieres guardar esa revision.

## Limitaciones deliberadas

- Las consultas Alpaca de acciones, noticias y opciones requieren credenciales
  locales y validacion durante sesiones reales.
- No ejecuta ordenes.
- Lineas de tendencia y varios terminos visuales requieren revision humana.
- No existe todavia una tabla oficial por simbolo para spot/strike.
- La linea roja de volumen Worden no esta incluida en la exportacion actual.
- La confianza permanece `NO_CALIBRADA`.
- Los ejemplos y porcentajes del curso no se tratan como garantias.

## Condiciones antes de una version estable

- Validar con Joan los umbrales abiertos de la matriz metodologica.
- Probar archivos TC2000 reales de varios simbolos y dias de mercado.
- Guardar reportes del validador en `exports/` para cada caso revisado.
- Definir y congelar un conjunto historico fuera de muestra.
- Validar tablas oficiales de opciones y limites del plan de riesgo.
- Revisar usabilidad durante sesiones PAPER supervisadas.
- Validar Alpaca REST/WebSocket contra sesiones PAPER reales sin retirar el
  flujo TXT/CSV conservado.

## Regla de lanzamiento

La etiqueta beta no debe retirarse mientras una regla obligatoria dependa de un
umbral no validado que la aplicacion pretenda decidir automaticamente. Las
revisiones humanas explicitas son aceptables y deben permanecer auditadas.
