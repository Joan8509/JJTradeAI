# Enfoque operativo: salida Bollinger 15m

Desde el 9 de octubre de 2026 la vista principal muestra exclusivamente los estados
del radar específico de Bollinger. Seguimiento de resultados muestra exclusivamente
el estudio de continuidad de esa estrategia, por defecto con detecciones en vivo.
Las validaciones de entrada de otras estrategias no se ofrecen en este modo.
Las herramientas manuales de riesgo, diario, análisis y auditoría se conservan.

El proceso de datos existente sigue recibiendo y guardando barras. Sus registros
anteriores de otros detectores no se usan para alimentar la vista de Bollinger ni
para sus notificaciones. El antiguo informe periódico de ocho estrategias se pausa.
Los códigos de esos detectores se conservan y el scanner existente no se reinicia,
porque hacerlo requiere credenciales de datos no disponibles en la sesión del agente.
Por tanto no se afirma que todo cálculo del antiguo scanner haya dejado de ejecutarse.

`bollinger_phone_worker.py` ahora registra observaciones aunque Telegram esté pausado
o desconectado. Solo el envío depende de su activación. Cada símbolo conserva el
estado más reciente en `bollinger_radar_state`; las detecciones inmutables permanecen
en `bollinger_live_events`. La pantalla exige sesión abierta y una barra completa
con antigüedad máxima de tres minutos para mostrar una salida como actual.

`bollinger_strategy_study.py --watch` sigue evaluando exclusivamente esos movimientos
y su reconstrucción histórica cada cinco minutos. No cambia las reglas, no autoriza
órdenes y no transforma una frecuencia histórica en certeza de la siguiente entrada.
