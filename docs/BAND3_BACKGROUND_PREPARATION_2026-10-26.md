# Apertura mínima y preparación de contratos

Usuario autoriza26/10 aplicar la mejora tras revisar dos entradas recientes.
El mínimo pasa de1% a3% para CADA banda, sobre el ancho previo; inclusive.
No se modifica la apertura oficial dentro de bandas actuales, dirección,
referenciaREGULAR, IEX3s, correcciones, calendario ni identidad de eventos.
La comparación retrospectiva de cuatro ejemplos no garantiza rentabilidad.

Preparación de calendarios completos CALL/PUT de compañías ARMED en un
trabajador separado, desde4min antes de la apertura hasta cierre oficial.
Una consulta por5s como máximo, pausa por Retry-After/fallo y monitor no listo;
órdenes pendientes tienen prioridad. Renovación a4min, TTL original5min.
Sin bloqueo del caché de negociación durante la red. Publicación breve no
sobrescribe una respuesta más reciente de compras/monitor. Cotizaciones
conservan timestamps reales y controles de frescura originales; preparación
no reclama ni ejecuta compras. Cola de producción no hace warmup síncrono.

SchwabTransport también separa su reserva compartida de inicio de solicitudes
de la espera HTTP: conserva separación mínima1s y actualiza Retry-After bajo
bloqueo. Respuestas de red pueden solaparse; una cadena lenta no mantiene
retenida la consulta de cotizaciones durante toda su respuesta. No se crea
otro WebSocket ni se evitan límites. OAuth conserva su bloqueo de rotación.

No elimina la consulta actual del vencimiento/contrato ni garantiza ejecución
instantánea. Se verificará demora real en próxima sesión; no usar resultados
sintéticos como medición de red o evidencia de profit. Reales OFF.

Cambios: bollinger_expansion.py, manual_trade_service.py,
opening_preparation.py, automatic_entry_queue.py, telegram_manual_runtime.py,
schwab_connection.py.
Pruebas de frontera3%, ambas direcciones, no bloqueo de caché por red,
publicación no regresiva, espaciado, Retry-After, horario y ausencia de órdenes.
Estado de carga, validaciones y preservación en CURRENT_CONTEXT y diario26/10.
