# Entrada y avisos independientes

Petición26/10: priorizar compra simulada al detectar estrategia y avisar en
paralelo. No se exige recibir Telegram para entrar; no se habilitan órdenes
reales ni se relajan señales, precios, frescura o contratos.

Se encontró espera evitable de escritura: heartbeat y motivo informativo
usaban BEGIN IMMEDIATE/timeout2s antes de revisar más filas. Ahora heartbeat
se publica máximo una vez por segundo si el estado no cambia, inmediatamente
si cambia, con timeout0. Un motivo idéntico no adquiere bloqueo de escritura;
un cambio ocupado se difiere. Esto solo afecta información de pantalla:
claims, idempotencia, pausas, conciliación y registro durable no cambian.
Se conserva prioridad de señal nueva, polling200ms en reposo y sin espera
añadida tras trabajo. No se incrementa carga de sondeo para aparentar rapidez.

Monitor despierta al trabajador independiente de avisos de ejecución al
terminar observación. Compra/seguimiento no esperan Telegram. Retry-After
sigue esperando sin que ese wakeup lo omita. El aviso de estrategia mantiene
su flujo y deduplicación; el de ejecución solo afirma compra al haber fills
reales del simulador, nunca por una detección o solicitud sin llenar.

Revisión de carga: nonblocking_entry_metadata_v1 y execution_notice_wakeup.
Cambios: automatic_entry_queue.py (heartbeat/waiting),
telegram_manual_runtime.py (wakeup de avisos),
tests/test_nonblocking_entry_metadata.py. No código de detector ni colector.

96pruebasOK63.925s con bases aisladas/proveedores ficticios: SQLite ocupado,
estado repetido, heartbeat, Telegram bloqueado mientras compra registra y
recibe fill, Retry-After, prioridad, cola y cierres. No son una medida de
latencia en mercado ni prometen fill instantáneo. Red, datos y contrato apto
siguen condicionando la entrada. Despliegue/evidencia en diario26/10 y
exports/trade_review/2026-10-26_opening_mu_nvda/ (privado).
