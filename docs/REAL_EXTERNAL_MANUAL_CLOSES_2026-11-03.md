# Venta manual desde thinkorswim o Schwab

El usuario autoriza el 03/11/2026 detectar automáticamente una venta manual de
un contrato comprado por JJTradeAI, conciliar el cierre y mantener las demás
compañías fuera de compras automáticas. Sustituye la necesidad de confirmación
individual del usuario para cada cierre externo normal que pueda verificarse.
La conciliación explícita anterior sigue disponible y conserva su historial.

## Comportamiento

- Observador independiente cada dos segundos mientras haya exposición propia o
  una conciliación pendiente. Consulta las órdenes de la cuenta seleccionada;
  no añade HTTP a la detección o preparación de una compra. El tiempo efectivo
  incluye respuesta, límites y disponibilidad del broker.
- Solo considera ventas SELL_TO_CLOSE del contrato exacto gestionado por la app.
  Compras externas y operaciones de otras compañías/cuentas no se incorporan.
- Guarda una retención persistente antes de conciliar. Pausa toda la cola,
  desactiva repetición y conserva primera entrada, exclusiones y auditoría.
  El guard final impide nuevas compras o ventas de ese contrato durante la
  conciliación, incluso si ya estaban preparándose. El cierre no rearma la cola.
- Cancela únicamente las órdenes pendientes de la app asociadas a esa posición,
  incluido un remanente de compra. No cancela la orden manual. Espera que Schwab
  confirme estados terminales y ejecuciones antes de liberar reservas.
- Reconoce cierres SINGLE MARKET o LIMIT con cuenta, contrato, cantidad, hora
  e historial completo de ejecuciones. No deduce un cierre de una lista de
  posiciones ausente ni de un precio promedio. MARKET no inventa un límite.
- Una venta parcial aún activa mantiene la retención. Cuando finaliza o se
  cancela su remanente, registra solo lo ejecutado. Si quedan contratos propios,
  continúa su gestión con el objetivo y stop originales; las compras siguen
  pausadas. Cierre completo elimina la posición del seguimiento de ventas.
- Reinicios y lecturas repetidas conservan deduplicación por orden de Schwab,
  fills y reservas. Una respuesta incierta de envío propio no se abandona ni
  repite. Evidencia ambigua, una compra externa simultánea del mismo contrato,
  órdenes complejas o cantidades incompatibles requieren revisión.
- Estado visible en Cola REAL e historial; avisos de detección/revisión separados
  de la confirmación de ejecución. No se envía una prueba adicional de Telegram.

## Validación y límites

Pruebas aisladas cubren venta completa, MARKET, parciales, cancelación del
objetivo, remanente de compra, desconexión/reinicio, carrera entre cancelación y
fill, cola consumida y ausencia de doble venta. La regresión completa y su carga
efectiva se registran en CURRENT_CONTEXT y el diario.

La evidencia de reproducción auténtica permanece en la revisión privada,
sin publicar operaciones individuales.

Esta reproducción no es una venta nueva ni demuestra una latencia futura en
mercado. La detección necesita que Schwab publique la orden. Una venta objetivo
ya activa en Schwab puede reservar los contratos: para vender manualmente hay
que revisar/cancelar esa orden en thinkorswim antes de enviar otra venta. El
observador no convierte dos ventas concurrentes en una operación atómica.

SIM, señales, selección, fondos, bandas3%, objetivo y stop20% no cambian. El
stop sigue local en la VPS. No hay rearme automático de otras compañías.
