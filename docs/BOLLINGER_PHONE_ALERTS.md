# Avisos tempranos de Bollinger

El servicio `bollinger_phone_worker.py` vigila exclusivamente salidas de Bollinger
en 15 minutos a partir de barras de un minuto persistidas por el buscador. Trabaja
separado del scanner, por lo que no necesita reiniciarlo ni acceder a sus claves.

Regla inicial de observación: el cierre de la vela anterior estaba dentro de sus
bandas; el precio observado de la vela actual queda fuera de la superior o inferior;
la banda superior aumenta y la inferior disminuye respecto de la vela anterior;
el punto medio cambia en la dirección de la salida. No se considera un simple toque.
No existe un umbral de fuerza calibrado: el aviso es provisional y puede revertirse.
Hora, Diario, contratos y aprobación PAPER no retrasan este aviso al usuario.

El proceso consulta cada cinco segundos, pero la fuente entrega barras por minuto.
Solo observa símbolos actualizados por el radar en los últimos tres minutos y
fuentes cuyo último minuto completo está dentro de esa ventana. Usa el calendario
persistido para limitarse a la sesión regular. No reconstruye señales antiguas para
enviarlas después del cierre.

Hay una sola notificación por chat, fuente, compañía, vela y disipador. El registro
SQLite sobrevive al reinicio. Se registra el intento antes de enviar. Si falla la
conexión, el envío queda no confirmado y no se repite automáticamente porque un
timeout puede ocurrir después de que Telegram aceptara el mensaje; no se garantiza
entrega exactamente una vez. La pantalla informa errores y falta de datos recientes.

El token se cifra con Windows DPAPI para la cuenta actual. Configuración y registros
locales están bajo `exports/telegram/`, excluido de Git. El servicio guarda heartbeat
y utiliza un bloqueo para impedir instancias duplicadas. El equipo, Internet y el
buscador deben permanecer activos. Tras reiniciar Windows hay que volver a iniciar
el servicio; no se instaló una tarea de inicio automático.

La pestaña «Avisos a mi teléfono» permite pausar o habilitar avisos. Desconectar
Telegram también detiene los envíos. No se envían SMS de operador telefónico.
