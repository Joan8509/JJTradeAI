# Operaciones y resultados en REAL

El usuario solicita una opción de ganadas/perdidas como en simulación. Se añade
**Operaciones y resultados** al espacio REAL, con lectura del journal cifrado
de la cuenta seleccionada, independiente de la disponibilidad para armar compras.

Muestra resultado cerrado bruto, conteos de ganadas/perdidas/sin cambio, en curso
y por revisar; filtros Hoy/Todo el historial y por resultado; tarjetas compactas
con compañía, CALL/PUT, contratos, precios medios, dólares/porcentaje y horas ET.
Incluye cierres manuales conciliados. Paginación20, sin truncar totales al límite
anterior de20 filas del resumen de cola.

Solo fills confirmados cuentan: una compra sin fill no es operación; una venta
parcial muestra lo realizado y lo restante, sin contar una victoria/pérdida hasta
cerrar completamente y confirmar estados terminales. Hoy usa fecha de cierre en
Nueva York, incluyendo compras de días previos cerradas hoy. Abiertas y pendientes
de conciliación permanecen visibles. No se inventa una valoración de lo abierto.

Ganancia bruta = (ingresos de ventas confirmadas - primas de compras confirmadas),
con multiplicador100 y aritmética Decimal. Precios medios ponderados por contratos.
Porcentaje de cada cierre calculado sobre prima real ejecutada, no sobre objetivo
ni Ask. No se presentan como netas comisiones/cargos no conciliados. Estados
inciertos/datos incompletos no se contabilizan como cero ni como ganancia.

Actualización de solo este fragmento cada5s y botón manual. La vista no consulta
Schwab ni Telegram, no crea un ejecutor ni ofrece controles de compra/venta.
Una lectura consistente del journal por refresco; no modifica cola, órdenes,
historial, señales ni simulación. Se carga solo la interfaz, preservando host REAL
y procesos de mercado. Despliegue y comprobaciones efectivas en CURRENT_CONTEXT.
