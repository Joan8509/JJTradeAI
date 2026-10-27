# Checkpoint de mejoras — 27 de octubre de 2026

Guardado solicitado por el usuario. Conserva el desarrollo posterior al
checkpoint del23Oct: detectorv5 con apertura dentro de bandas actuales y
expansión mínima3% por banda; contratos y controles de datos conservados.

Incluye entradas prioritarias, calendarios preparados, caché/consultas fuera
de bloqueos compartidos, informes y recibos aparte del dispatch, ventas
pendientes con consulta nueva y diagnóstico privado asíncrono acotado.
Compra, seguimiento y avisos permanecen independientes y deduplicados.
No se cambia el límite de venta al primer Bid, stop20% ni objetivos aprobados.

Dashboard móvil con preparación por lotes, objetivos/cantidades por compañía,
borrador/consentimiento, verificaciónSchwab sin bloquear edición y GETnuevo
obligatorio al armar. Sin refrescos que interrumpan edición, fondo estático,
historial y referencias descriptivas sin aprendizaje que cambie entradas.
Rango AAPLAsk0.45–0.95 según tabla actualizada; otras52referencias iguales,
SPCXsinrango aprobado. No altas adicionales al radar por importar la tabla.

Autenticación de lecturaSchwab, renovación y supervisor preventivo preparados;
registrar/validar tarea preventiva sigue pendiente. Token/API y navegador son
independientes. RealesOFF; simulación local con quotes, no paperMoney deSchwab.

## Validación y límites

Regresiones focales de cada mejora fueron ejecutadas antes de sus cargas.
Validación amplia del checkpoint:355testsOK en158.411s, datos ficticios y bases
aisladas, sin compras/avisos activos. Primera pasada tuvo3fallos por dos
aserciones antiguas del rangoAAPL; corregidas al rango aprobado del Excel,
sin modificar producción para pasar pruebas. No se afirma suite completa.
Revisión de privacidad del paquete sin hallazgos de secretos o identificadores
privados; bases/credenciales/historiales y diarios operativos excluidos.
No se declara suite total ni ganancias futuras. Medir próxima sesión regular:
detección→orden→fill, espera deRLock y causas de salida pendiente. Datos y
contratos no aptos continúan bloqueando. Cobertura extendida y pruebas de
recuperación/reinicioRDP pendientes. No reiniciar servicios para subir código.

Los diarios operativos extensos, claves/configuraciónDPAPI, cuentas, bases,
respaldos, operaciones y revisiones privadas permanecen locales. La continuidad
completa anterior se conserva localmente antes de compactar CURRENT_CONTEXT.
No se eliminan por excluirlas deGit. No clonar e iniciar un segundo colector
ni asumir independencia operativa completa a partir de esta copia de código.

La publicación se acredita con el SHA remoto, no por la existencia de este
documento. CURRENT_CONTEXT contiene contrato vigente y comprobaciones con fecha.
