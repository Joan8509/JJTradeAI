# Post-beta roadmap

Fecha: 2026-07-10.

Este roadmap empieza despues de `0.2.1-beta`. El objetivo no es agregar
senales, sino convertir la beta validable en una version estable sin inventar
criterios metodologicos.

## Prioridad 1 - Validacion con datos reales

Meta: probar que el flujo soporta varios simbolos y sesiones reales sin perder
trazabilidad.

Trabajo:

- Exportar al menos varios paquetes TC2000 con 15m, 1H y 1D.
- Ejecutar el flujo:

```powershell
.\venv\Scripts\python.exe validation_batch.py `
  --input-dir exports\tc2000_cases `
  --preflight-output-dir exports\tc2000_cases `
  --run-after-preflight `
  --output-dir exports\validation_batch `
  --standard-output-dir
```

- Revisar `review_queue.csv` por prioridad.
- Revisar `operator_board.csv` para priorizar paquetes completos, incompletos o
  bloqueados.
- Ejecutar `--inspect-output-dir` para confirmar que la salida batch quedo
  completa antes de revisar manualmente.
- Guardar observaciones humanas por caso en `case_intake.csv`.
- Cargar `case_intake.csv` en la pestana **Auditoria** para revisar pendientes
  humanos por paquete.

Criterio de avance:

- Cada paquete queda `LISTO` en preflight.
- Los reportes conservan `validation_package`, `data_source`, version de app y
  version metodologica.
- Los casos incompletos explican claramente por que terminan en `NO_OPERAR`.

## Prioridad 2 - Cola de revision dentro de la app

Meta: reducir el trabajo manual al revisar lotes.

Ya implementado:

- La pestana **Auditoria** muestra cola filtrable para un reporte JSON.
- La cola se puede descargar como CSV.

Siguiente mejora segura:

- Permitir cargar un `review_queue.csv` completo para revisar lotes dentro de la
  app. Estado: implementado.
- Mostrar conteos por `priority`, `review_type`, simbolo y paquete. Estado:
  implementado.
- Mantener la cola como evidencia, no como aprobacion automatica.

## Prioridad 3 - Primer set de decision metodologica con Joan

Meta: transformar ambiguedades en reglas aprobadas, revisiones manuales o
bloqueos explicitos.

Temas que requieren decision:

- peso cuantitativo entre Bollinger y medias;
- formula o tabla oficial de rango optimo de opciones;
- umbrales de tendencia, volatilidad, lateralidad y distancia a medias;
- diseno de lineas de tendencia manuales o asistidas;
- duracion valida de Momentum;
- universo y ventana de noticias;
- criterios para pasar de PAPER a REAL.

Criterio de avance:

- Cada tema se registra en `docs/METHODOLOGY_VALIDATION_MATRIX.md` como
  resuelto, manual obligatorio o no automatizable.
- Ningun umbral entra al codigo sin fuente y aprobacion.

## Prioridad 4 - Usabilidad de sesion PAPER

Meta: que una sesion PAPER supervisada sea fluida y auditable.

Trabajo seguro:

- Mejorar filtros del diario por simbolo, decision, readiness y modo. Estado:
  filtros por simbolo, decision y readiness implementados para analisis; modo,
  simbolo y decision implementados para operaciones cerradas.
- Mostrar pendientes principales desde auditorias guardadas. Estado:
  implementado con primer pendiente, primer bloqueo y descarga CSV filtrada.
- Facilitar comparar analisis recientes contra operaciones PAPER cerradas.
  Estado: implementado con tabla de operaciones cerradas, resumen por modo y
  seguimiento de decision, y descarga CSV filtrada.
- Mantener separacion estricta entre PAPER y REAL. Estado: reforzado con
  filtros y pruebas de aprendizaje/estadisticas por modo.

## Prioridad 5 - Fuente de datos API

Meta: reducir exportaciones manuales sin reemplazar todavia TC2000 validado.

Trabajo:

- Elegir proveedor candidato.
- Implementar adaptador que produzca las mismas columnas canonicas.
- Comparar API contra TC2000 para el mismo simbolo y sesion.
- No guardar credenciales ni metadatos sensibles en reportes o diario.

Bloqueo:

- Si el proveedor no entrega un campo metodologico, el campo queda
  `NO_DISPONIBLE`.

## No hacer todavia

- No retirar la etiqueta beta.
- No activar operaciones reales automaticamente.
- No aprobar riesgo sin limites configurados.
- No convertir `tentative_bias` en senal.
- No entrenar un modelo que modifique reglas oficiales.
- No reemplazar revisiones visuales sin criterios aprobados.

## Siguiente entrega recomendada

El siguiente avance recomendado es usar varios paquetes TC2000 reales y
completar `case_intake.csv` con observaciones humanas. La vista de lote en la
app ya permite cargar `operator_board.csv`, `review_queue.csv` y
`case_intake.csv`, revisar conteos y filtrar por paquete, prioridad y tipo sin
cambiar la decision de trading.
