# Seguimiento automático de estrategias PAPER

El scanner existente recibe barras de mercado y guarda evaluaciones posteriores
a 15, 30 y 60 minutos. `strategy_research.py` lee esas evaluaciones, sin escribir
en la base de mercado ni modificar decisiones. Actualiza un informe cada cinco
minutos mientras el proceso siga activo en este equipo.

La app muestra el informe en **Seguimiento de resultados de estrategias**.
Los archivos completos están en `exports/strategy_research/latest.md` y
`exports/strategy_research/latest.json`. El JSON incluye segmentos por símbolo,
horario, tendencia y alineación con el mercado cuando existen etiquetas guardadas.

La cobertura incluye las ocho familias y el detector complementario Expuesto
Bollinger, aunque no tengan resultados confirmados. Cuenta escaneos ejecutados,
detecciones, confirmaciones, omisiones y errores, y muestra requisitos pendientes
frecuentes y el último estado por símbolo. Una detección no equivale a una señal
operable.

La opción **Candidatas pendientes** analiza los movimientos de configuraciones
detectadas con requisitos incumplidos o sin datos. Sus resultados se calculan en
el informe, sin insertarlos en `paper_signal_evaluations` ni usarlos para aprobar
señales. Se exige la barra de entrada y la de cierre del horizonte exacto; una
barra tardía no suple el cierre faltante. Si falta el cierre, la observación queda
sin resultado; no se inventa un acierto ni un fallo. Los horizontes de 60 minutos
que cruzan el cierre de sesión pueden quedar sin resultado permanentemente.

El proceso no recibe datos externos por sí mismo. Si el scanner se detiene o
pierde conexión, no aparecerá nueva evidencia. El reporte incluye la última
salud y fecha de barra del scanner. No se ha configurado inicio al encender Windows.

## Método

### Auditoría y recuperación de minutos

El informe compara las últimas 20 sesiones del calendario guardado con las barras
locales de los símbolos del scanner. Respeta apertura y cierre de cada sesión,
incluidos cierres anticipados, y excluye minutos que todavía no han terminado.
Cuenta cobertura por símbolo, proveedor y feed y conserva rangos de minutos
ausentes. Si no hay calendario, informa SIN_CALENDARIO sin inventar sesiones.

MINUTOS_SIN_BARRA y SIN_COBERTURA_LOCAL describen la base local, no una pérdida
confirmada. Según la documentación oficial de Alpaca, una barra puede no generarse
si no hubo operaciones elegibles en el intervalo:
https://docs.alpaca.markets/us/docs/market-data-faq

La app permite seleccionar una sesión, introducir las claves de Alpaca en campos
enmascarados y consultar el mismo feed. Las claves no se escriben en archivos.
La recuperación inserta solo barras devueltas por el proveedor dentro del período
auditado y no sobrescribe barras existentes. No rellena con precios anteriores ni
cambia de feed. Si siguen faltando minutos después de consultar REST, la causa
queda NO_DETERMINADA; la respuesta sin barras no prueba ausencia de operaciones.

El trabajador del informe no tiene las claves que quedaron en la memoria del
scanner existente. Por ello la auditoría es automática, pero la recuperación
remota requiere las credenciales introducidas en el formulario. No se ha ejecutado
una recuperación real durante esta implementación. El informe y los estudios de
entrada reflejan las barras recuperadas en su siguiente actualización. Las
evaluaciones originales y las hipótesis registradas no se reescriben.

### Estudio de entrada posterior a la emisión

La opción **Posterior a la emisión** usa `strategy_alerts.created_at` como hora
de disponibilidad. Es una aproximación al registro de la señal, no constancia
de entrega de una notificación. La entrada de referencia es la apertura del
minuto estrictamente posterior al máximo entre esa hora y el cierre de la barra
que disparó la señal. La salida es el cierre del minuto que termina exactamente
15, 30 o 60 minutos después de esa entrada. Las barras se interpretan con timestamp
de inicio de minuto. Solo se evalúan barras terminadas al corte del informe.

Se exige continuidad de todas las barras y precios OHLC coherentes, positivos y
finitos. Los recorridos con datos incompletos, registros de sesiones anteriores y
horizontes fuera de 09:30–16:00 ET se identifican por separado. Este modelo aún no
utiliza el cierre especial de medias sesiones: no debe interpretarse como una
simulación completa de sesión ni de ejecución. La apertura siguiente tampoco
garantiza un precio ejecutable. No se incluyen órdenes, contratos, bid/ask ni costos.

Los resultados originales permanecen en **Cierre de la vela de señal**. La muestra
de entrada posterior puede ser distinta por disponibilidad de datos y exclusión
de huecos; comparar porcentajes sin revisar las muestras puede ser engañoso.
El JSON incluye las observaciones y sus precios y timestamps para auditoría.
Los experimentos anteriores de filtros siguen vinculados a su modelo original.

### Observación visual de Worden

En el detalle de una alerta de Efecto Imán se puede guardar una observación de
Worden: cruce observado, sin cruce o no evaluable, con fecha/hora observada y notas.
La captura es opcional y, si se vincula, debe pertenecer a esa alerta, ser de Hora
y declarar Worden visible. Las observaciones se versionan en `alert_worden_reviews`
y conservan la hora de registro; no modifican el reporte original, los criterios
del detector ni las decisiones históricas. Por tanto, el requisito del detector
permanece pendiente hasta una revisión metodológica específica. Es un registro
de evidencia visual, no automatización de Worden.

- Solo usa resultados cuyo horizonte y fecha de evaluación ya han transcurrido.
- Separa estrategia, dirección, horizonte y versión de metodología.
- Conserva los conteos completos y una muestra que excluye ventanas superpuestas
  del mismo símbolo, proveedor y feed dentro de cada grupo.
- Compara el 70 % inicial de sesiones con las sesiones restantes, sin partir una
  sesión entre períodos. No ajusta parámetros con ninguno de esos períodos.
- Define positivo como retorno direccional mayor que cero y negativo como menor
  que cero. Esto es distinto del umbral neutral que puede usar el evaluador PAPER.
- Muestra tamaño de muestra y número de sesiones. No interpreta la tasa positiva
  como probabilidad de la próxima señal ni prueba de rentabilidad.

Los símbolos todavía pueden estar correlacionados. Los resultados corresponden
al subyacente, no a opciones; no incluyen spread, comisiones ni deslizamiento.
Los segmentos pequeños sirven para investigar, no para aprobar filtros.

## Primer hallazgo, 6 de octubre de 2026

En CT15 bajista a 60 minutos, la muestra sin solapamiento contiene 169
evaluaciones de 20 sesiones. En el período reciente quedan 31 evaluaciones de
6 sesiones, con 10 movimientos positivos y 21 negativos y retorno direccional
medio de -0.051415 %. Es una observación que merece investigar por símbolo y
contexto; no demuestra todavía una degradación estadística ni autoriza invertir
la dirección de la estrategia.

La siguiente validación debe fijar una hipótesis a partir de las sesiones
anteriores y contrastarla con sesiones nuevas, conservando las reglas y los
resultados originales. Aumentar la tasa de aciertos tampoco basta si empeoran
las pérdidas, los costos o la cantidad de oportunidades.

## Operación

### Pruebas de filtros con sesiones futuras

Se registran tres hipótesis fijas: evitar tendencia lateral, limitar a apertura
y exigir tendencia de 15 minutos alineada con CALL/PUT. Se comparan por estrategia,
dirección, horizonte, versión y grupo (confirmadas o candidatas).

La evaluación inicial compara el 70 % inicial de sesiones con el resto. Se guarda
junto con la fecha de registro en `filter_experiments` de `latest.json`. Cada
actualización conserva esa evaluación y añade resultados de sesiones posteriores
al día de registro. Los datos futuros no reajustan filtros ni señales.

La comparación usa como referencia las observaciones del mismo período con
contexto conocido. Informa aciertos, retorno medio, excursión adversa media y
porcentaje de oportunidades retenidas. Diez resultados de al menos tres sesiones
son un mínimo descriptivo para estas pruebas; no son umbrales de trading.
Una mejora exige aumentar tasa positiva y retorno sin empeorar la excursión
adversa media. Si el retorno filtrado sigue negativo, se etiqueta
`MEJORA_RELATIVA_RETORNO_NEGATIVO`.

Las pruebas son exploratorias: múltiples comparaciones, correlación entre
símbolos y costos omitidos impiden interpretar una mejora descriptiva como
precisión demostrada. No se selecciona ni despliega automáticamente un ganador.
También se muestran las pruebas que fallan y las que carecen de muestra.
Para conservar las fechas y evaluaciones iniciales no se debe borrar `latest.json`.

Generar una vez:

```powershell
.\venv\Scripts\python.exe strategy_research.py
```

Seguimiento continuo:

```powershell
.\venv\Scripts\python.exe strategy_research.py --watch --interval 300
```

Solo se permite un trabajador por carpeta de salida. Para detener el trabajador
en segundo plano sin detener el scanner:

```powershell
.\venv\Scripts\python.exe scanner_control.py --lock-file exports/strategy_research/worker.lock --stop-file exports/strategy_research/worker.stop stop
```

El scanner ya abierto no recarga cambios de Python. Las correcciones en sus
módulos se aplicarán en su siguiente reinicio; el informe de investigación
usa un proceso nuevo y sus propias restricciones temporales desde ahora.
