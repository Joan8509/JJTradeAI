# Validar entrada PAPER

La pestaña **Validar entrada PAPER** reúne una alerta, la revisión de camino,
noticias y panorama, selección explícita de contrato, plan de entrada/salida y
límites semanales existentes. Guardar y validar crea revisiones trazables y una
reevaluación nueva, sin cambiar la alerta original ni ejecutar órdenes.

## Evidencia que utiliza

Lee el informe que se actualiza cada cinco minutos. Solo incorpora observaciones
de estrategias confirmadas, entrada posterior a la emisión, horizonte de 60
minutos, mismo proveedor/feed y versión metodológica. No mezcla candidatas con
confirmadas ni suma horizontes. Excluye la propia alerta y resultados posteriores
al momento de validar. Quita ventanas superpuestas del mismo símbolo.

La evidencia se guarda en el resultado junto con su fecha de origen. Se conserva
la decisión metodológica por separado de la decisión de validación PAPER.

La política descriptiva utiliza el mínimo de 20 observaciones del aprendizaje
PAPER existente, retorno direccional medio positivo y límite inferior de Wilson
al 95 % mayor que 50 %. Exige evidencia favorable para todas las estrategias que
soportan la decisión. No representa una probabilidad calibrada: símbolos/sesiones
pueden estar correlacionados, las muestras se seleccionan y faltan costos.
`confidence` permanece NO_CALIBRADA y la aprobación no garantiza rentabilidad.

## Condiciones adicionales

- Todas las compuertas metodológicas originales deben pasar la reevaluación.
- Gobierno operativo debe ser PAPER, con planes y límites evaluados.
- La sesión oficial guardada debe estar abierta.
- La señal debe estar dentro de los tres minutos de frescura existentes y su
  frescura original debe estar aprobada.
- El contrato debe pertenecer a los candidatos elegibles de la alerta, coincidir
  con CALL/PUT y contener una cotización dentro de los tres minutos de frescura.
- El informe debe haberse actualizado en los últimos diez minutos.

Si falta un dato, el flujo guarda NO_OPERAR y explica el bloqueo. El formulario
no obtiene cotizaciones nuevas por sí mismo ni inventa un contrato o sus límites.
Los candidatos nuevos de opciones conservan quote_timestamp en el reporte;
los anteriores que no contienen esa fecha no sirven como cotización vigente.

La aprobación se refiere al momento guardado. La interfaz deja de presentarla
como vigente cuando vence la señal o cierra la sesión. Resultados posteriores se
siguen registrando con el flujo de feedback de alertas existente; no sirven para
aprobar retroactivamente la entrada original. La confirmación visual de Worden
continúa siendo evidencia separada y no modifica criterios del detector.
