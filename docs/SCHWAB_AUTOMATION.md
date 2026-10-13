# Integración propuesta con Charles Schwab

Estado: diseño preparado; sin conexión al broker y sin envío de órdenes.

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
