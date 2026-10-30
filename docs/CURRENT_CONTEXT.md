# Continuidad de JJTrade AI

Checkpoint técnico del 30/10/2026, solicitado por el usuario para GitHub.
La continuidad operativa completa anterior se conserva localmente en
exports/trade_review/2026-10-30_no_entries/github_checkpoint/ y en los diarios
docs/SESSION_STATE_*.md. No se elimina al publicar este resumen sin datos privados.
Consultar docs/GITHUB_CHECKPOINT_2026-10-30.md y STRATEGY_OPERATING_CONTRACT.md.

Guardado GitHub publicado y comprobado30/10/2026 a las13:27ET:
commit636295e6e763df43ad1172c9de0ff4fbd5f420db, main remoto coincide.
146testsOK75,292s y diff --check sin errores. Paquete revisado sin hallazgos
de secretos/identificadores privados en59archivos seleccionados. Documentos
históricos privados y continuidad completa conservados locales, sin borrarlos.
Este recibo documental se publicará después del commit de código y se verificará
también contra el remoto; no se reinician servicios ni se envían avisos/órdenes.

## Estrategia y autorizaciones vigentes

Simulación local con cotizaciones de mercado; no es paperMoney de Schwab.
Órdenes reales deshabilitadas. Preparación de cuenta real pausada por el usuario;
el módulo nuevo es exclusivamente de lectura, sin permisos de despacho.
Clonar GitHub no restaura cuentas, bases, tokens, tareas ni una instalación activa.
No iniciar una segunda instancia ni inferir configuración privada desde el código.

Bollinger v5: 15 minutos, 20 períodos, desviación2, ddof0. Apertura real de la
misma vela dentro de las bandas del momento de detección, ambas expandiéndose
al menos3% cada una sobre el ancho previo. Comparar5% sigue siendo observacional.
CALLsuperior/PUTinferior; estrategia intravela, sin esperar cierre. IEX/REGULAR;
alineación extendida pendiente de cobertura. Trade3s y opciones/spot30s.
ITM o primeros5strikesOTM inclusive, ATMexcluido; Ask en rango aprobado,
spread máximo0.08; vencimiento más próximo, después14ET omitir mismo día.
Stop20%; objetivos10/20/35/100/manual. Datos/contratos no aptos siguen bloqueados.

## Ejecución y reloj

Ventana30s desde el primer EXIT auditado de símbolo/vela/dirección; persistente,
no se renueva por nuevos trades, avisos tardíos, planes o reinicios. La consulta
SQLite normaliza la vela ET a UTC antes de comparar texto indexado. Evidencia
incompleta/podada no permite inventar un inicio. Comprobación de arranque con
SQLite en memoria/caché aislada: ET invierno/verano, primera hora inmutable y
rechazo de ausencia de evidencia. Fallo detiene solo nuevas entradas automáticas
con motivo explícito; la gestión de posiciones y salidas conserva su monitor.

Dos búsquedas de contrato como máximo, una por plan, coordinador200ms y mismo
transporte/backoff. Claim durable y revalidación antes de despacho. Diagnóstico
opcional después del registro; no retrasa compra. Una solicitud por fila;
nuevas colas con consentimiento explícito de repetición pueden rearmarse tras
conciliación/cierre y solo para otra señal nueva. Incertidumbre nunca se reintenta.
Pausar/eliminar detiene sucesores, sin cancelar posiciones o ventas existentes.

Stop simulado al siguiente Bid válido, sin garantizar pérdida máxima20%; objetivo
con mínimo del porcentaje elegido. Objetivo pendiente que alcanza stop conserva
disparo durable, cancelación confirmada y conciliación del remanente. No modifica
fills antiguos. Avisos de estrategia sin botones; compra/cierre solo con fills
confirmados y enlace. Mantener deduplicación y envíos inciertos, sin replay.

## Interfaz, datos y límites

Tres pestañas y edición por lotes; guardado con consentimiento y comprobación de
conexión. Módulo de cuenta en lectura con vaultDPAPI separado, selección explícita,
sin fallback al de datos, OAuthloopback8186/8187; MiniApp8184 intacta. No consultas
de cuenta al abrir ni habilitación de órdenes. Requiere configuración/consentimiento
del usuario cuando reanude esa preparación. No automatizar contraseñas ni MFA.
Worker ordenado y acotado para guardar velas oficiales; no inventar referencias.
Memoria y estudios descriptivos no cambian reglas ni garantizan rentabilidad.

La corrección del reloj y protección se cargaron y comprobaron el30/10; último
corte operativo13:18ET con heartbeats y rutas de salud recientes. Esto no acredita
estado actual ni compra nueva completa tras la corrección. Verificar procesos,
conexión y trazabilidad señal→contrato→registro→fill antes de afirmar funcionamiento.
Pendientes: verificar nueva entrada, estudiar retrasos particulares con evidencia,
cobertura extendida y recuperación/reinicio de VPS. No reiniciar para este guardado.
