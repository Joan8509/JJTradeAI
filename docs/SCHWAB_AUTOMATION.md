# Automatización con Charles Schwab

## Estado vigente23/10/2026

Ensayo local manual y automático con datos reales de mercado; órdenes reales
deshabilitadas. Nuevas operaciones stop20%, objetivos elegidos y cierre manual.
Entrada automática con límite al techo del rango autorizado, caducidad10s,
monitor despertado al registrar y prioridad de señales nuevas sobre reintentos.
No se modifican planes ya ejecutados. Ver [checkpoint](GITHUB_CHECKPOINT_2026-10-23.md)
y [contexto vigente](CURRENT_CONTEXT.md). Un resultado simulado no modifica
saldos ni posiciones de la cuenta Schwab.

## Estado histórico18/10/2026

OAuth/DPAPI y DATOS reales Schwab verificados; ensayo manual local habilitado,
stop10%, objetivos elegidos y cierre manual. Perfil actual MARKET_DATA_ONLY.
Acceso real a saldos/posiciones/cuentas no probado y envío real NO implementado:
permanece bloqueado por código. La cuenta vinculada por consentimiento OAuth
no acredita permisos de trading ni convierte resultados del ensayo en dinero.
Ruta revisada hacia cuenta real: [SCHWAB_REAL_READINESS_2026-10-18](SCHWAB_REAL_READINESS_2026-10-18.md).
Estado/pruebas del ensayo: [CURRENT_CONTEXT](CURRENT_CONTEXT.md).

## Estado histórico16/10, sustituido por el estado vigente anterior

Estado16/10/2026: conexión de lectura/OAuth, contratos, ejecución local y
conciliación implementados y probados en simulación. Cuenta real no conectada;
órdenes reales deshabilitadas por código. Informe vigente:
[SCHWAB_IMPLEMENTATION_2026-10-16](SCHWAB_IMPLEMENTATION_2026-10-16.md).

Se conserva el [contrato v4](STRATEGY_OPERATING_CONTRACT.md): apertura propia
dentro, ambas bandas abriéndose y dirección de precio/apertura/media, sin veto
por cierre previo fuera. El disparador actual es intraminuto por trades IEX,
máximo3s, rechazo de futuro y relectura antes de preparar entrada. SuperiorCALL,
inferiorPUT. SMA/niveles/memoria siguen descriptivos. Avisos y dedup intactos.

El selector ITM existente se comparte ahora en option_contract_selection.py sin
cambiar su función. Schwab normaliza identidad OCC y datos de contratos estándar,
exige cotización vigente/tiempo real y un incremento de precio verificado.
La guarda30s del contrato no reemplaza la guarda3s del detector.

El ensayo utiliza dos bases independientes, ledger y broker local. Una política
incompleta bloquea entradas; las pruebas usan valores sintéticos identificados
como tales. Estado incierto persistente no reenvía; fills parciales y cancelación
se concilian antes de vender solo lo comprado. Objetivo bruto20% sobre VWAP del
contrato, redondeado al tick; pérdida y tiempo según plan explícito. La pausa
bloquea entradas y conserva gestión de posiciones. No se presume OCO real.

OAuth y su receptor están preparados, no configurados ni desplegados: callback
HTTPS exacto, state/cookie de un solo uso, secretos/tokens cifrados con DPAPI bajo
Administrator y renovación persistida. Solo GET de recursos y POST de OAuth;
sin transporte de envío/cancelación/reemplazo de órdenes. App/cuenta, permisos,
saldos, respuestas reales y parámetros del usuario siguen pendientes.

Validación:128pruebas relevantesOK,46nuevas Schwab, ensayo completo con detector
real sobre mercado sintético y auditoría estática sin hallazgos. No es prueba de
API real, recepción RTH, entrega Telegram ni rentabilidad.

```powershell
.\venv\Scripts\python.exe -m unittest tests.test_schwab_connection tests.test_schwab_contracts tests.test_schwab_simulation tests.test_schwab_reconciliation tests.test_schwab_workflow -v
.\venv\Scripts\python.exe schwab_rehearsal.py
```

El ensayo usa una carpeta temporal nueva; --directory RUTA_NUEVA conserva evidencia
y rechaza rutas existentes. No usar las bases sintéticas como datos de mercado.
La consola Hyper-V y el reinicio son pendientes operativos independientes, sin
bloquear desarrollo; no reiniciar ahora. Radar mantiene sus controles vigentes.

## Referencia histórica anterior al desarrollo del16/10

El contenido siguiente conserva acuerdos y antecedentes. Sus menciones de
fuente exclusivamente por minuto o integración únicamente propuesta quedaron
sustituidas por el estado y el contrato enlazados arriba.

## Disparador autorizado para diseñar la integración

Salida de Bollinger con expansión de volatilidad en 15 minutos, sin esperar
el cierre de la vela. Salida superior: comprar CALL. Salida inferior: comprar PUT.
Se utiliza el evento del radar de Bollinger: precio anteriormente dentro,
ambas bandas abriéndose y punto medio acompañando. El aviso puede revertirse;
no equivale a una estrategia confirmada al cierre ni a una probabilidad calibrada.

La fuente actual entrega barras de un minuto: no promete detectar el primer tick.
La simulación inicial será local; no se presupone un entorno paperMoney por API.

## Flujo de la orden

1. Autorización de la cuenta mediante la API oficial de Schwab, con aplicación
   de desarrollador aprobada y permisos para el contrato correspondiente.
2. Recibir evento vigente durante la sesión y descartar duplicados. Verificar
   órdenes pendientes y posiciones antes de comprar; no repetir una petición
   cuando se desconoce si Schwab la aceptó.
3. Elegir contrato con reglas explícitas de vencimiento, strike o delta,
   liquidez, spread, cantidad, presupuesto y precio límite. Estas reglas
   todavía están pendientes del usuario.
4. Registrar la orden y conciliar estados, rechazos y ejecuciones parciales.
5. Calcular objetivo bruto del 20% sobre el precio efectivamente ejecutado
   del contrato, ajustado al incremento de precio permitido. No se aplica
   al movimiento porcentual de la acción ni implica una ganancia neta garantizada.
6. Gestionar salida por objetivo, pérdida máxima y tiempo, solo por cantidad
   efectivamente comprada. Verificar soporte de órdenes vinculadas/OCO en
   documentación y cuenta autorizada; no asumir que la plantilla de escritorio
   es equivalente a una petición API.
7. Botón de pausa y límites por operación y día. La pausa no elimina por sí
   sola posiciones ni órdenes de protección existentes.

## Pendientes antes de activar operaciones reales

- Acceso de desarrollador, aplicación aprobada y autorización de la cuenta.
- Cantidad o presupuesto, selección del contrato, pérdida máxima y salida por tiempo.
- Pruebas locales y revisión de los casos de fallos de red y reinicio.
- Servidor continuo, gestión de secretos y monitorización de autorizaciones.
- Habilitación explícita del plan concreto de ejecución real.

Fuentes:
- https://developer.schwab.com/
- https://international.schwab.com/story/set-up-thinkorswim-desktop-options-trading


## Primer paso de operacion manual desde Telegram
Implementada una pantalla movil de revision (?operar=SIMBOLO&lado=CALL|PUT&senal=FECHA), sin ejecucion de ordenes. Incluye grafico OHLC 15m y Bollinger con las barras IEX locales, marca datos antiguos, CALL/PUT y referencia del listado separada de cotizaciones. Los botones Comprar/Vender estan deshabilitados: falta conexion autorizada a Schwab, cotizaciones reales, contratos, cuenta, posiciones y conciliacion de ordenes. No hay simulacion de fills ni precios inventados.
Telegram puede adjuntar inline_keyboard con URL a la compania cuando exista JJTRADE_APP_URL o exports/telegram/app_link.json. En Notificaciones se guarda la direccion que abre desde el telefono; rechaza localhost y credenciales en el enlace. GET solo abre revision y nunca compra. Radar reiniciado para cargar soporte del boton, deduplicacion preservada. Falta direccion del usuario para activar enlaces y saber si tiene app aprobada en el portal Schwab; se solicito sin pedir secretos por chat. No se desplego web publica ni se envio un mensaje de prueba.
Selector ITM can?nico preparado y probado con snapshots OPRA: CALL strike menor que precio accion, PUT mayor; rechaza quote/accion antiguos (>30s), futuros, bid/ask incoherentes o sin tamano, datos indicative y expirados. Aun NO conectado a datos ni al formulario. Esta tolerancia solo comprueba antiguedad del dato, no valida rentabilidad ni calidad de ejecucion. Pendientes unidades del rango de primas, vencimiento, cantidad/presupuesto y precio limite antes de preparar ordenes reales.
