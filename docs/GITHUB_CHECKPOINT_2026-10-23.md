# Estado del código conservado — 23/10/2026

Este checkpoint conserva el desarrollo conciliado de la VPS: detector intravela,
avisos persistentes, conexión de lectura Schwab, simulación manual/automática,
MiniApp Telegram, dashboard móvil, historial y protecciones de ejecución.

Reglas vigentes: Bollinger15min20/2ddof0, apertura propia dentro, ambas bandas
expandiéndose al menos1% del ancho previo, dirección de precio y media.
IEX3s y Schwab30s; sesión regular. ITM o primeros5strikesOTM inclusive, Ask
en rango por compañía y spread máximo0.08. CALL superior, PUT inferior.
SMA/niveles/contexto descriptivos no añaden filtros. Referencia extendida
preparada, sin activar hasta acreditar cobertura.

Nuevas operaciones simuladas usan stop20%, objetivos10/20/35/100/manual,
cierre manual disponible; planes de operaciones anteriores son inmutables.
Cada fila automática necesita compañía/cantidad/objetivo/sesión y autorización.
Límite automático al techo del rango autorizado; fill al Ask real posterior a
crear la orden, con tamaño visible. Caducidad10s cancela solo remanente local,
conciliado, sin rearme/replay. Manual mantiene confirmación exacta.

Revisión `fresh_signal_priority_v1`: señales nuevas preceden reintentos, primer
nuevo corta escaneo; claves nuevas no heredan pausa de otra señal, pero cliente
respeta429/Retry-After. Pasadas con trabajo no añaden200ms; reposo200ms.
Registrar compra despierta monitor independiente de Telegram. No segundo stream.

Aviso de estrategia conserva cuatro líneas sin botones. Compras y cierres
confirmados tienen avisos independientes; no se reenvían históricos ni inciertos.
Se preservan154registros originales, incluidos16inciertos; datos privados no
se adjuntan a este checkpoint. Todas las órdenes reales siguen deshabilitadas.

Validación realizada antes de publicar:75regresiones de cola/latencia/apertura/
runtime/entrada acotada y6casos focales posteriores. Tandas anteriores116y113
con solapamiento cubrieron stop20, planes antiguos, manual/Telegram/UI. No se
afirma suite completa ni rentabilidad. Ver documentos específicos y Git para
archivos y cambios. Última verificación operativa local23/10 20:26ET, HTTPS200;
no demuestra recepción futura por símbolo ni ejecución en la siguiente sesión.

Pendientes: medir detección→registro→fill en siguiente regular, disponibilidad
de contratos/datos, cobertura extendida, registro continuo de opciones y pruebas
coordinadas de recuperación/RDP/reinicio. No reiniciar para guardar en Git.

Las credenciales DPAPI, claves OAuth/Telegram, cuentas, bases y sus respaldos,
operaciones privadas y evidencia de infraestructura permanecen locales, fuera
de Git. Esta copia de código no incluye el estado necesario para operar desde
otra máquina: no iniciar otro colector ni tareas por clonar el repositorio.
