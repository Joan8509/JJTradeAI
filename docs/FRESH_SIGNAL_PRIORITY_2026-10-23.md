# Prioridad de señales nuevas

Petición23/10: reducir cada espera evitable entre estrategia y compra.
La cola conserva el mismo detector, protocolo de mercado, autorizaciones,
contratos, stop20, límite de rango, caducidad10s y claims persistentes.

Antes una fila reintentando obtener contrato podía atenderse antes que una
señal nueva en otra fila. Ahora se pospone ese reintento hasta revisar las
restantes filas elegibles. La primera señal nueva se atiende inmediatamente,
sin esperar a terminar de revisar todos los símbolos. Empates conservan el
orden rotativo. La clave es símbolo/vela/lado; cambios de precio dentro de
la misma señal no crean prioridad nueva ni eliminan sus pausas.

Una vela/lado nuevos no heredan la pausa local de5s de un intento anterior.
Esto solo aplica antes de dispatch: nunca elimina claims ni rearma filas
consumidas o inciertas. El retry_at del cliente sigue bloqueando consultas
durante Retry-After/429, aunque la clave cambie.

Si una pasada intentó procesar una entrada, la siguiente puede comenzar sin
añadir200ms artificiales. Al agotarse trabajo elegible vuelve la espera200ms;
no hay bucle ocupado. Se mantiene como máximo un intento por pasada, las
pausas de la misma señal, el backoff HTTP y la vigilancia independiente de
salidas/Telegram. Una consulta REST ya en vuelo sigue sin ser interrumpible.

Medición RO local de los19símbolos:70.737ms total,max16.608ms por lectura.
No es latencia de red, de fill ni una prueba de éxito en mercado. No se
garantiza comprar donde faltan datos o contratos aptos. Estado de carga y
regresiones en continuidad; evidencia privada fresh_signal_priority/.
