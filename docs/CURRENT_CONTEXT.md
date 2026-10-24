# Contexto vigente de JJTrade AI

23/10/2026 20:42 ET: código guardado y push verificado en origin/main,
commit79f76ff50ee92c039b61961dabcf17675b2b7c78.210archivos de código,
pruebas y documentación técnica; índice exacto y ASTPython comprobados,
auditoría sin credenciales reales.84documentos/artefactos históricos privados
u obsoletos conservados localmente y excluidos. Bases, cuentas y configuración
privada fuera de Git. No reinicios ni cambios operativos por esta publicación.
El registro de publicación se guarda en un commit documental posterior;
consultar Git log para su SHA y el del código. No asumir estado operativo
actual por el hecho de estar guardado en GitHub.

Actualizado23/10/2026 ET. Instrucciones actuales del usuario prevalecen.
Leer AGENTS.md, docs/SESSION_STATE_2026-10-23.md y
[checkpoint t?cnico](GITHUB_CHECKPOINT_2026-10-23.md).

## Estado vigente

Solo SIMULACI?N LOCAL con cotizaciones reales Schwab; no es paperMoney.
?rdenes reales deshabilitadas, perfil MARKET_DATA_ONLY.
Detector intravela IEX3s, Bollinger15m20/2ddof0, apertura propia dentro,
ambas bandas1% del ancho previo y direcci?n de precio/apertura/media.
Referencia regular; extendida preparada sin cobertura acreditada.

Entrada manual o cola con compa??a/cantidad/objetivo/sesi?n expl?citos.
CALL superior/PUT inferior. ITM o primeros5strikesOTM inclusive, Ask en rango,
spreadm?ximo0.08 y Schwab30s. Stop20% para nuevas operaciones; planes anteriores
inmutables. Objetivos10/20/35/100/manual y cierre manual conservados.

Revisi?n fresh_signal_priority_v1: nuevas se?ales preceden reintentos, primera
nueva corta escaneo; sin200ms tras trabajo, reposo200ms. Clave nueva no hereda
pausa5s previa; respeta429/Retry-After. Compra despierta monitor. L?mite
al techo del rango autorizado; fill al Ask posterior real con tama?o; caducidad
remanente10s, sin rearme ni replay. Telegram estrategia4l?neas sin botones;
compra/cierre confirmados tienen avisos independientes.154deduporiginales,
incluidos16inciertos, intactos. No borrar claims para obtener m?s avisos.

?ltima verificaci?n23/10 20:26ET: radar cargado/monitor listo, servicios
AdministratorSession0, colector/interfaz preservados, HTTPS200, realesOFF.
No acredita ticks/fills futuros; revalidar procesos, heartbeat y recepci?n
antes de afirmar funcionamiento. No reiniciar por guardar Git.
75regresionesOK48.281s y6focalesOK2.875s; tandas previas116/113 se solapan.
No suite completa ni rentabilidad acreditadas.

## Pendientes y conservaci?n

Medir detecci?n?registro?fill y causas de noentrada en pr?xima regular, con
compa??as expl?citamente armadas. Pendientes cobertura extendida, captura
continua de opciones y pruebas coordinadas de recuperaci?n/RDP/reinicio.
No otro colector ni avisos hist?ricos/?rdenes reales por clonar el c?digo.

Detalles en STRATEGY_OPERATING_CONTRACT.md, BOUNDED_ENTRY_STOP20_2026-10-23.md,
FRESH_SIGNAL_PRIORITY_2026-10-23.md, BAND_EXPANSION_FILTER_2026-10-22.md,
AUTOMATIC_ENTRY_LATENCY_2026-10-22.md y OPENING_PREPARATION_2026-10-22.md.

Bases, cuentas, credenciales DPAPI, operaciones y evidencia permanecen locales,
fuera de Git. Contexto anterior completo y cambios locales fueron respaldados
antes de compactar; diarios hist?ricos no se modifican. No restaurar bases
con Git ni asumir configuraci?n privada disponible en otro equipo.
