# Fuerza observada del movimiento

Implementacion 11/11/2026: clasificacion descriptiva paralela a la estrategia.
No autoriza ni bloquea compras, no espera confirmaciones, no cambia Bollinger,
la caducidad V7, el objetivo elegido ni el stop del 20%.

`movement_strength.py` calcula con informacion conocida en la deteccion:

- Expansion de ambas bandas frente al ancho anterior; referencia experimental
  de fuerza: dos veces el minimo vigente. Tambien muestra la velocidad de la
  banda contraria cuando hay geometria comparable de la misma vela anterior.
- Velocidad media de los ultimos cinco segundos frente a los cinco anteriores.
  Referencias experimentales: 0.2% del ancho previo por segundo y aceleracion1.5x.
- Continuidad del tramo previo: eficiencia y avance conservado al menos0.7.
  Solo se clasifica con precios suficientemente continuos, sin huecos mayores2s.
  La velocidad media puede conocerse con anclas aun faltando continuidad.
- Volumen del ULTIMO minuto cerrado frente a la mediana de la misma hora ET en
  hasta20 sesiones anteriores; al menos10 disponibles y referencia1.5x. No es
  volumen del minuto en formacion ni volumen consolidado de todo el mercado.

Alta: al menos3 componentes favorables de4 conocidos. Media:2; baja:0-1.
Si falta algun componente, PARCIAL, nunca asignar baja por datos ausentes.
Umbrales exploratorios, no probabilidades calibradas. No usar como filtro.
Las medias y posibles niveles siguen en el panel de recorrido existente;
ninguna media por delante se convierte automaticamente en resistencia.

`movement_strength_store.py` lee la base de mercado con mode=ro/query_only y
presupuesto200ms por conexion. Auditoria acotada por received_at (indice),
12s previos, hasta10000 filas; truncamiento se trata como falta de evidencia.
Solo TRADE con geometria aceptada y precio/instante finales iguales a la senal.
Excluye precios futuros, recibidos/procesados despues de detectar, horas ambiguas
y eventos sin zona. Las revisiones de barras posteriores no entran al volumen.
La auditoria antigua no etiqueta feed por fila: se comprueba feed de runtime y
se limita captura al dia actual. No usar para inferir historicos de otros feeds.

`scripts/observe_movement_strength.py` funciona separado del detector/ejecutor,
sin red, credenciales, broker o Telegram. Guarda evento original, entradas,
politica, mediciones y heartbeat en `exports/movement_strength.sqlite3`.
Tarea Windows propia `JJTrade-ObservacionFuerza`, singleton y prioridad baja;
registro mediante `scripts/register_movement_strength.ps1`. Ninguna tarea de
operacion se modifica. Espera2s solo el OBSERVADOR para leer auditoria publicada;
no es una espera de la compra. Reintentos30s hasta2min y despues conserva lectura.

REAL: Estado de la estrategia > Actualizar diagnostico, junto a las medias de
cada senal guardada. SIM: tarjetas de senales. Ambas leen solo el archivo de
observaciones, sin recalcular historicos ni llamar al broker. Fecha, precio y
fuente originales visibles. No hay nuevos botones ni avisos Telegram adicionales.

Validacion: 65 pruebas pasadas (incluye13 nuevas) y repeticion del modulo tras
ajuste de presentacion. Prueba SQLite aislada verifica hash de fuente intacto,
reproduccion exacta desde entradas guardadas y ausencia de creacion por lectura.
Estado de carga y prueba visual efectiva se registran en CURRENT_CONTEXT y en
exports/trade_review/2026-11-11_movement_strength/; no deducir conexion REAL de
que el observador o la interfaz respondan.
