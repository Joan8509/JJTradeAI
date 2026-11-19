# Navegacion REAL: lecturas de pantalla sin esperas del ejecutor

18/11/2026. El usuario reporta lentitud entre pestanas de Operacion Real.

Se mide cada vista con AppTest, cProfile y lecturas DPAPI reales locales,
prohibiendo conexiones de red y sin pulsar botones operativos. Es tiempo del
servidor, no latencia completa del navegador/Tailscale. Dos muestras por vista;
no representan percentiles ni una garantia de tiempo.

Cola real: cuerpo de render0.7462/1.0505s antes;0.2536/0.1497s despues.
Cuenta:0.2520/0.1979s antes;0.0739/0.0489s despues. La primera importacion
continua teniendo costo de arranque y no se mezcla con las vistas calientes.

Cambios:

- Detalles de activacion se calculan solo al abrir ese desplegable.
- Cola y resultados dejan de consultar si un refresco periodico corresponde a
  una pestana que ya no esta seleccionada.
- display_requests/display_status leen una publicacion atomica nueva para la
  pantalla, sin tomar el mutex de escritura del ejecutor. Conservan propietario,
  DPAPI, formato/proposito, cuenta y antiguedad del estado; sin cache ni fallback
  a una respuesta previa. Posiciones e historial usan una sola lectura coherente.
- La publicacion cifrada existente escribe el temporal, fsync y reemplaza el
  archivo completo. El lector observa documento anterior o nuevo, no una mezcla.
  En Windows puede haber denegacion de apertura durante el reemplazo: reintento
  acotado a150ms total para winerror5/32/33 o PermissionError/EACCES13. Otros
  errores y fallos de identidad/cifrado se propagan; nunca se reutiliza exito.
- La disposicion de botones usa ese estado de pantalla. arm/resume/can_arm y
  requests() del ejecutor mantienen sus lecturas bloqueadas y validaciones
  actuales, sin usar el camino de display como autorizacion de compra.

82testsOK28.223s: paneles, navegacion, proxy, resultados, journal, validacion de
cuenta/antiguedad, lectura simultanea con publicacion atomica, fallos de acceso
acotados y ausencia de fallback. gitdiffcheckOK. No reinicios de servicios,
armados de cola, consultas broker, ordenes ni avisos Telegram para este cambio.

Evidencia privada: exports/trade_review/2026-11-18_tab_latency/ con mediciones
antes/despues, perfiles y logs. Primer harness fallo por Path no importado en
funcion aislada; corregido. Lote inicial fallo por clase de excepcion del test y
por la carrera de acceso Windows; detectada, corregida y revalidada. Archivos
anteriores conservados. Estado de salud actual y carga: CURRENT_CONTEXT.
