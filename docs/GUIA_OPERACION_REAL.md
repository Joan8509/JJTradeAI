# Guía para operar en REAL en JJTradeAI

Actualizada 04/11/2026. Esta guía describe los controles; el estado de conexión,
cola y ejecución se comprueba en la app.

1. Entra en **Operar en Real**.
2. En **Cuenta**, pulsa **Consultar conexión y cuentas** y elige tu cuenta.
   Se verifica y conserva para el resto del recorrido; no debes conectarla otra
   vez en la cola. Consultar/elegir cuenta no activa compras.
3. En **Con mi saldo**, revisa el efectivo liquidado disponible. La lista por
   rango es orientativa; un contrato debe existir y cumplir precio, costos,
   spread, vencimiento y cercanía al spot. Preparar candidatas solo selecciona.
4. En **Preparar compañías**, elige una, varias o todas. Aplica contratos y
   objetivo; puedes ajustar cada fila. Revisa el Rango Ask de cada compañía.
5. Pulsa **Activar preparación**. Esta acción guarda la selección y autoriza
   las compras automáticas REALES de esa cola. La app abre **Cola real**; comprueba
   las filas **Bajo el radar** y la sesión indicada. Un botón deshabilitado o un
   fallo de activación requiere revisar el motivo; cargar o visitar no activa.
6. La primera señal nueva válida, con contrato y fondos aptos, reserva una entrada.
   La primera compra confirmada, incluso parcial, excluye a las demás compañías.
   No se reactivan al vender. La ventana original de señal continúa siendo30s.
7. **Cola real** se actualiza sola. **Pausar** detiene nuevas entradas y pasa a
   **Activar** para reanudar solo las compañías pausadas de la misma sesión.
   No reanuda órdenes inciertas, filas retiradas/excluidas ni sesiones vencidas.
   **Quitar compañía de la cola real** retira una pendiente.
   **Eliminar todas las compañías en espera** retira todas las que aún no tienen
   compra/claim en curso. Ninguno de esos controles cierra posiciones existentes.
8. Sigue la operación en la cola y las confirmaciones por Telegram. Tras el fill
   final se valida y coloca la venta LIMIT DAY por el objetivo elegido en Schwab.
   Una orden activa no es un fill. El stop20% se vigila desde la VPS al Bid
   disponible; es un umbral de salida, no un precio garantizado. Cerrar manualmente
   desde la app coordina primero cualquier salida pendiente para evitar duplicados.
   Si vendes desde thinkorswim/Schwab, el observador concilia el contrato de la app,
   pausa nuevas entradas y mantiene la gestión del remanente si el cierre es parcial.
9. En **Operaciones y resultados**, consulta ganadas/perdidas, Hoy/Todo el historial,
   cierres manuales conciliados y resultado bruto antes de cargos.

Cerrar el navegador o cambiar de pantalla no pausa las compras: usa **Pausar**.
La VPS necesita seguir encendida/conectada para sus monitores. Para otra sesión,
activa una nueva preparación explícitamente. La simulación permanece independiente.
La preparación previa de calendarios adelanta trabajo; cada compra conserva
cotizaciones, estrategia, contrato, costos y fondos actuales. No espera Telegram,
recarga del dashboard ni cierre de la vela.
