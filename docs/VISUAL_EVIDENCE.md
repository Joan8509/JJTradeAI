# Evidencia visual TC2000

## Proposito

Las capturas permiten conservar el contexto visual que observa el usuario en
TC2000, especialmente lineas, niveles, compresion y configuraciones que aun no
tienen una regla automatizada.

La fuente cuantitativa principal sigue siendo la API. Una imagen no reemplaza
OHLCV, temporalidades ni indicadores calculados.

Esta evidencia pertenece exclusivamente al carril posterior a la alerta. El
scanner nunca espera una captura para emitir `CALL`, `PUT` o `NO_OPERAR` y no
se requiere abrir TC2000 durante un movimiento rápido.

## Flujo

1. Seleccionar una alerta existente.
2. Elegir temporalidad `15m`, `1H` o `1D`.
3. Adjuntar una imagen PNG o JPEG.
4. Declarar los indicadores visibles.
5. Guardar notas de contexto.
6. Revisar la captura como `PENDIENTE`, `COINCIDE`, `DIFIERE` o
   `NO_EVALUABLE`.

Las discrepancias y limitaciones requieren notas. Cada revision se agrega como
una nueva version y no sobrescribe revisiones anteriores.

## Efecto conservador en la reevaluacion

No adjuntar capturas es valido y queda como `OMITIDO`. Cuando si existen:

- todas deben conservar integridad;
- todas deben tener revision `COINCIDE`;
- `DIFIERE` rechaza el panorama de esa reevaluacion;
- `PENDIENTE` o `NO_EVALUABLE` mantienen `NO_OPERAR`;
- la revision humana general debe ser posterior a la ultima captura o revision
  visual.

Si una captura o su revision cambia, debe guardarse una nueva revision humana
antes de reevaluar. La reevaluacion congela IDs, hashes y estados visuales.
Esto no cambia las reglas Investep; solo impide ignorar evidencia contradictoria.

Los resultados PAPER pueden agruparse descriptivamente por
`visual_confirmation`. Se mantiene el minimo de muestra contextual y nunca se
modifican estrategias de forma automatica.

## Seguridad y trazabilidad

- Limite de archivo: 10 MB.
- Dimensiones minimas: 320x200.
- Dimensiones maximas: 12000 por eje.
- Nombre fisico derivado del SHA-256 del contenido.
- Archivos almacenados bajo `exports/visual_evidence`.
- Directorio excluido de Git y bloqueado por el control de publicacion.
- Asociacion obligatoria con una alerta y su simbolo.

La autoridad registrada es `EVIDENCIA_VISUAL_NO_MODIFICA_DECISION`. Ni la carga
ni la revision visual ejecutan ordenes o modifican la decision congelada.

## Auditoria

La app vuelve a leer cada archivo y comprueba:

- existencia;
- SHA-256;
- cantidad de bytes;
- tipo de imagen;
- dimensiones registradas;
- ultima revision humana.

El estado `INTEGRO` confirma que los archivos coinciden con la base.
`BLOQUEADO_ARCHIVOS` indica ausencia, corrupcion o modificacion. El manifiesto
JSON descargable incluye conteos de revisiones pendientes y discrepancias, pero
no incluye la imagen ni modifica la decision.

## Auditoria multitemporal posterior opcional

La pestaña **Alertas de mercado** y `beta_status.py` muestran un estado agregado
independiente de la decisión. Para alcanzar `APROBADO` debe existir al menos una
alerta con capturas `15m`, `1H` y `1D`, todos los archivos íntegros y la última
revisión de cada captura en `COINCIDE`.

`NO_INICIADO`, `EN_REVISION`, `DIFIERE` y `BLOQUEADO` permanecen diferenciados.
Un caso completo no autoriza trading real ni sustituye datos OHLCV; solo
demuestra que el flujo visual multitemporal fue recorrido y auditado. Un estado
`NO_INICIADO` no bloquea `BETA_PAPER_VALIDADA` ni el carril de señales en vivo.

## Respaldo

El arranque del scanner crea un paquete `.visual.zip` emparejado con el backup
SQLite. El manifiesto interno registra la huella de la base y la de cada
captura. Un archivo faltante o alterado bloquea la creacion del paquete y, por
seguridad, el scanner no continua.

La restauracion se realiza con `visual_evidence_backup.py` y nunca sobrescribe
un archivo diferente.
