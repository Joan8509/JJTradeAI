# Diagnóstico de entradas omitidas — 4 de noviembre de 2026

Conservar solo el último error no permite explicar el primer intento de
entrada. Una consulta posterior no prueba la disponibilidad histórica de contratos.

Se corrige un defecto reproducible en `real_live_opportunities.py`: una lista
vacía de contratos se devolvía como ausencia de oportunidad y podía mostrarse
como espera de estrategia. Ahora produce `NO_ELIGIBLE_EXPIRATION_OR_RANGE`.
También conserva el primer intento y primer fallo por señal, fase, tiempos y
contrato seleccionado cuando existe. Solo códigos expresamente permitidos;
ningún texto arbitrario de excepción o respuesta privada del broker.

El registro de entrada es exclusivamente en memoria, acotado a 128 señales.
El heartbeat cifrado existente de `real_execution_host.py` publica esa copia
fuera del camino de compra. No se implementó recuperación de ese historial
en memoria después de reiniciar el ejecutor. Se conserva la evidencia previa
al desplegar en el directorio privado de auditoría.

No cambian filtros, rango de primas, cinco strikes OTM, fondos, spread,
caducidad de 30 segundos ni primera entrada que excluye el resto. No se fuerza
una compra sobre una señal vencida. No se amplía autorización económica.

Validación offline: 57 pruebas focalizadas y 262 de regresión aprobadas,
incluida privacidad de excepciones, ausencia de contrato, primer fallo conservado
tras éxito y señal caducada. Los ensayos no enviaron órdenes ni avisos reales.
La activación y estado efectivo deben consultarse en CURRENT_CONTEXT y el diario;
un resultado offline no demuestra carga del proceso ni ejecución futura.

Evidencia detallada privada: `exports/trade_review/2026-11-04_real_readiness/`.
Incluye auditoría de señal, consulta de elegibilidad posterior, validación con
SHA-256 y procedimiento de recarga que exige journal terminal sin exposición,
verifica órdenes conocidas en Schwab y conserva cola, control y procesos de mercado.
