# Checkpoint de desarrollo - 16 de noviembre de 2026

Guardado solicitado por el usuario a 2026-11-16T13:49:57-05:00. Incluye mejoras acumuladas desde
el checkpoint del 4 de noviembre: recuperacion de acuses y salidas, avisos
independientes de la compra, seleccion persistente de cuenta, controles de
preparacion/cola, ruptura temprana V7, preparacion anticipada, prioridad de
cotizaciones, despertar local, consultas indexadas y lector REAL reutilizado.
Incluye estudios reproducibles de apertura, medias, ancho, fuerza y objetivo10%,
asi como registro asincrono de cotizaciones ya recibidas. Estudios descriptivos
no se convierten en nuevos filtros de entrada. SEV25 sigue bloqueado por decision
del usuario; conservar3%, reloj30s, frescura3s, objetivo elegido y stop local20%.

Validacion de este guardado: 503 pruebas dirigidas aprobadas en 87.955 segundos, seleccionando todos los modulos de pruebas
modificados o nuevos incluidos. No equivale a repetir toda la bateria: la corrida
amplia del15Nov tuvo fallos/errores documentados, algunos fixtures corregidos
despues; pendientes descritos en ENTRY_LATENCY_REVIEW_2026-11-15.md. Comprobacion
de secretos por patrones sin hallazgos en los archivos seleccionados. Diff de
formato y contenido del indice se comprueban antes de crear el commit.

Excluidos y conservados en VPS: credenciales, tokens, DPAPI, configuracion privada,
cuentas/operaciones individuales, SQLite/estados, diarios operativos, revisiones
privadas y79documentos historicos locales que no forman parte de esta seleccion
revisada. No se borraron. Contexto operativo completo previo preservado en
exports/trade_review/2026-11-16_github_checkpoint/CURRENT_CONTEXT.before.md y diario.
La documentacion tecnica revisada y todos los cambios de codigo/pruebas/scripts
detectados se incluyen. GitHub conserva desarrollo, no un backup restaurable de
todos los datos de la VPS. No se reinician servicios, arman colas, envian ordenes
o prueban avisos durante este guardado. Publicacion pendiente hasta verificar
que HEAD coincide con refs/heads/main remoto.
