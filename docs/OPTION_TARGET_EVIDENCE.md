# Evidencia y comparacion del objetivo de opciones

Investigacion16Nov: option_target_quality calcula el esfuerzo teorico necesario
para un10% bruto a partir de Ask/Bid/delta. Requiere contrato prevalidado por el
llamador, no evalua elegibilidad completa ni autoriza compra. Delta supone
constantes IV/tiempo/spread y cambia con el mercado; no es una probabilidad de
acierto. La frontera Pareto informa alternativas y conserva desconocidos.
No se importa este modelo en el ejecutor ni se cambia seleccion automatica.

scripts/study_target_certainty.py compara rasgos causales y retrasos sobre un
corte congelado. Horas anteriores y volumen recibido antes de decision son los
unicos insumos de seleccion; endpoints futuros son etiquetas separadas. Muestras
historicas ya vistas son contraste retrospectivo. Sin orden ni filtro activo.

option_evidence_recorder conserva solo quotes ya recibidas por REAL. Publicacion
en memoria con limite128paquetes y descarte visible; hilo separado escribe una
SQLite propia en exports/trade_review/option_evidence/quotes.sqlite3. Nunca
solicita HTTP, no llama gateways, no forma parte de las guardas de operacion.
Si falla, publica UNAVAILABLE y la operacion conserva sus controles normales.
No diagnosticar conexion broker mediante heartbeat del writer.

Guarda timestamp real del proveedor y hora de observacion, Bid/Ask/tamanos,
Greeks, spot y signal_key de candidatos que ya cumplen criterios de mercado.
No incluye cuentas, credenciales ni IDs de orden. Deduplica repeticion de cache;
los counters corresponden al proceso actual. Greeks no finitos quedan null.
Gaps indican paquetes descartados; no equivale a historial completo del mercado.
Hooks en real_live_opportunities y arranque explicito en real_execution_host.
Cargado/verificado solo segun CURRENT_CONTEXT, nunca por presencia de codigo.

La futura evaluacion de10%antesde20% debe asociar mismo contrato y fills,
respetar huecos y costes. No inferir primer toque exacto de un fill final ni
reconstruir precios de opciones desde el movimiento del subyacente. No crea
segunda instancia ni activa colas/compra, ni cambiaSEV25,10/20,3% o reloj30s.
