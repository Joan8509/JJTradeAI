# Salidas pendientes: prioridad y cotización posterior a la orden

27/10/2026 ET. Usuario solicita revisar la demora de venta al alcanzar el
objetivo. El caso privado está en2026-10-27_meta_trade/REPORT.md y la revisión
en exports/trade_review/2026-10-27_exit_latency/.

Se acredita intervalo orden→fill, pero no existe historial completo de quotes
no casados de ese intervalo para atribuir su causa exacta. La salida observada
es una orden límite al Bid que dispara, y solo se ejecuta con una cotización
posterior, con tamaño y Bid>=ese límite. Si Bid retrocede, puede seguir pendiente
aunque aún esté por encima del porcentaje objetivo. Esta revisión no cambia
el límite de órdenes existentes/nuevas, objetivos, stop20% ni cierre manual.

Demora evitable reproducida: el monitor podía consultar una posición que ya
tenía venta pendiente antes de atender esa venta, reutilizar un quote anterior
a la orden por la caché subsegundo y rechazarlo. Ahora posiciones con venta
pendiente omiten esas consultas redundantes; ventas se atienden antes que
compras pendientes y su consulta es forzada para pedir datos nuevos. No se
eliminan controles de sesión, timestamp posterior, antigüedad, tamaño, límite,
deduplicación de liquidez, cancelación de entrada parcial ni conciliación.
No se permite llenar una venta con la cotización que creó la orden.

Diagnóstico privado acotado en exit_observations.jsonl del directorio del
simulador observado. Trading solo encola con bloqueo no esperable; trabajador
separado escribe y rota2MB+unarchivo anterior. Eventos: alta de salida, inicio/
fin/error de lookup, falta de quote posterior, Bid bajo límite, liquidez no
disponible o match. Campos permitidos: tiempos, precios, contrato, clave local
y motivo fijo; nunca cuerpo de error, URL, cuentas o credenciales. Si se llena
la cola/se bloquea disco/falla diagnóstico, no impide vender. No nuevo stream.

Pruebas: quote nuevo durante caché<1s permite vender; una sola consulta para
venta pendiente, sin consulta redundante de posición; Bid inferior a límite
no fabrica fill; error de diagnóstico no impide venta; cola acotada/rotación/
campos no autorizados rechazados. Validaciones y carga efectiva en continuidad.
Revisión runtime esperada fresh_pending_exit_quotes_v1 y exit_diagnostics_enabled.
Se requiere nueva comprobación sin exposición antes de recargar solo radar.

Carga acreditada18:56:54ET, después del cierre, revisiónesperada y diagnóstico
habilitado. Sin exposición/pending, guard+barrera de claims; hashes contables/
claims/autorizaciones/reglas iguales, dos incertidumbres y154dedup intactos,
colector/interfaz y tarea conservados. No reinicioWindows/colector ni streams.
HTTPS200/monitorREADY/TelegramgetMe/getChatOK18:57:27; cero mensajes/órdenes del
agente, realesOFF. Tandas80/71/51OK con solapamiento, py_compile/diffcheckOK.
Falta próxima salida con mercado abierto para medir y clasificar la espera;
no declarar eliminados23.89s del caso histórico. Mantener precio límite
actual: aceptarlo al porcentaje mínimo en vez del primer Bid sería otra
decisión de ejecución, no cambiada en esta reparación. No commit/push.
