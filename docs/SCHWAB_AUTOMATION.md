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
