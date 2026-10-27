# Memoria de referencias sin demorar entradas

Usuario26/10 mantiene entrada rápida como prioridad y pide aprovechar trades
positivos para mejorar la certeza. Primera etapa: referencias descriptivas,
incluyendo pérdidas, sin entrenamiento predictivo ni modificación automática
de estrategia. No convertir resultados positivos seleccionados en filtros.

Se aprovecha el historial persistente de fills ya existente. La memoria se
recalcula del mismo snapshot reconciliado de «Mis operaciones», sin otra
consulta a DB/proveedor y sin dependencia nueva del detector/motor/Telegram.
No worker nuevo ni recarga del mercado. Solo la interfaz necesita recarga.

trade_learning.completed_trade_references es función pura. Solo cierres
completos conocidos a la hora de consulta; excluye parcial/abierto/futuro,
deduplica entradas y rechaza números inválidos. Referencias positivas por
recencia, no por mayor ganancia; pérdidas permanecen para comparación.
Grupos por compañía, dirección, fase horaria, stop/objetivo/modo de salida,
base de entrada y modelo de ejecución guardados. Registros con distinto plan
no se agrupan como si fueran iguales. Todos siguen OBSERVACION_NO_VALIDADA.

Precios/resultados provienen de fills; neto sigue desconocido sin comisiones.
Duración y espera orden→primer fill no equivalen a latencia detección→orden. Esta
última, expansión y versión exacta de señal se dejan desconocidas si faltan;
no inferirlas del profit ni del umbral que está activo hoy. Reglas históricas
pueden diferir aun en un grupo: no declarar precisión, probabilidad ni patrón
validado. La muestra solo incluye trades ejecutados, no oportunidades omitidas.

Visualización discreta en expander «Aprendizaje · Referencias de operaciones»
en Mis operaciones. Tres referencias positivas recientes, cifras ganadas y
perdidas y medianas de retorno/duración claramente descriptivas del historial.
Los datos siguen en exports/trade_review; no guardar operaciones en Git.

operation_results añade metadatos ya guardados en orden: created_at, plan,
entry_basis, execution_model. No nuevas lecturas ni escritura en bases activas.
No cambia estrategia3%, contratos, frescura, stop20, avisos o deduplicación.
Sin aprobación/bloqueo por memoria, sin órdenes reales y sin autoajuste.

Siguiente etapa: vincular evidencia verificable de señal y medir fuera de
muestra antes de proponer cambios. Estado de pruebas/carga en contexto/diario.
