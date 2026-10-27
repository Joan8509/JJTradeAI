# Supervisión de autorización Schwab

Implementada26/10/2026 para detectar indisponibilidad antes de una señal.
No sustituye el consentimiento interactivo del proveedor ni garantiza que
una sesión nunca sea revocada. No automatiza contraseñas, MFA o login web.

`schwab_auth_watchdog.py` comprueba perfil MARKET_DATA_ONLY y realesOFF,
renueva el acceso cuando quedan cinco minutos o menos, usando el mismo
SchwabOAuth y bóveda DPAPI con bloqueo entre procesos. Comprueba GET de
cotizaciones antes de la apertura y durante el mercado, independientemente
de que exista una compañía armada o una señal. Fuera de ese horario verifica
GET tras renovar; no abre otra conexión de streaming ni consulta cuentas.
Respeta Retry-After de429 entre ejecuciones. No cambia caducidades ni edad
original de autorización para aparentar que la sesión se extendió.

`scripts/watch_schwab_authorization.py` publica recibo privado y alertas
operativas actuales por Telegram: autorización rechazada, fallo de conexión
o recordatorio preventivo desde cinco días de edad. Cinco días es una política
preventiva local, no una caducidad oficial comprobada. Claims privados propios
antes del envío; un envío incierto no se repite. Recordatorios diarios son
comprobaciones actuales nuevas, nunca reenvío de señales históricas. No se
abren bases de trading ni se alteran sus deduplicaciones. La falta de red
Telegram puede impedir la entrega; recibo local conserva SENT/UNCONFIRMED.

`scripts/register_schwab_watchdog.ps1 -Register` registra únicamente
JJTrade-Schwab-Autorizacion, cada cinco minutos y al iniciar Windows,
Administrator/Password, instanciasIgnoreNew, límite2min, sin depender de RDP.
Si Windows no acepta credencial ya guardada, `-PromptCredential` solicita
contraseña Windows exclusivamente mediante Read-Host -AsSecureString en
consola RDP; no secretos por chat, archivos, argumentos ni logs. No sobrescribe
tarea existente ni reinicia colector, radar, interfaz o equipo.

Recepción real de avisos y funcionamiento en Session0 requieren comprobar
el recibo y tarea instalados; que las pruebas unitarias pasen no los acredita.
La estrategia, selección de contratos, tolerancias y órdenes reales no se
modifican. La salud OAuth no acredita contrato apto, compra ni fill.

Validación26/10:28 pruebas unittest del watchdog, conexión y receptor local
exitosas,3.367s. Casos: renovación anticipada, rechazo, secreto en excepción,
perfil inseguro,429persistente, recordatorio y no reenvío tras envío incierto.
Instalación y comprobaciones operativas: ver diario26/10/2026 actualizado.

## Comprobación al preparar la cola

Petición posterior26/10: el operador debe conocer la conexión al elegir
compañías. `automatic_entry_panel.py` muestra resultado de GET autenticado
en «Operar Automáticamente», con horaET, botón de comprobación y resultado
saneado almacenado máximo30s. Distingue autorización necesaria de conexión
sin confirmar. Permite elegir campos aunque falte conexión, pero no confirmar
armado sin preflight. Al confirmar consulta de nuevo sin caché, reemplaza el
indicador con el resultado nuevo y conserva campos si falla; no crea el plan.
No pausa ni borra planes que ya estaban armados. Una conexión confirmada
ahora no garantiza disponibilidad posterior o contrato elegible para la señal.

Esto funciona independientemente de la tarea de mantenimiento: abrir la app
no requiere que el watchdog se haya instalado. No añade consulta de control
al camino rápido del detector o del QueueRunner. Reglas y validaciones de
entrada vigentes conservadas. Resultados unitarios/UI:80pruebasOK62.014s,
incluida caída de autorización entre indicador y clic; datos ficticios y
almacenes aislados, sin compras/avisos reales. Ver diario para prueba visual.
