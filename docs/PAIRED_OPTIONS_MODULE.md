# RETIRADO: CALL + PUT simultaneos

18/11/2026: por decision expresa del usuario se elimina la modalidad del inicio,
la ruta y los cinco archivos de implementacion/pruebas. El enlace anterior
modo=call-put vuelve al inicio. Observador paper desautorizado en su journal;
no modifica la simulacion habitual ni REAL. Codigo y evidencia de desarrollo
archivados privadamente en exports/trade_review/2026-11-18_paired_retired.
El contenido siguiente se conserva solo como historia y NO describe funciones
disponibles en la aplicacion. La prioridad vuelve a entrada direccional rapida.

---

# CALL + PUT: simulación automática independiente

18/11/2026. Sustituye la página de preparación: el usuario autorizó el módulo
y eligió explícitamente simulación automática con datos actuales.

## Uso

Inicio → CALL + PUT simultáneos. Seleccionar entre 1 y 10 compañías, presupuesto
virtual máximo por pareja, cantidad por lado y costo estimado por contrato y
por transacción. «Activar prueba en simulación» inicia únicamente el observador
paper. No necesita saldo ni selección de una cuenta real. Se requieren las
credenciales de datos de mercado ya autorizadas en la VPS.

Una activación espera una señal NUEVA posterior a esa activación. La primera
compañía que complete señal y pareja apta consume la activación. El resto no
entra. Cada prueba sigue hasta cerrar los tres escenarios. Otra prueba requiere
una nueva activación expresa. No se ha activado ninguna prueba como parte de
la instalación; el usuario elige compañías y presupuesto.

## Reglas y cálculo

- Se reutiliza solo la validación `_signal` del contrato V9 vigente: apertura,
  bandas/expansión, precio actual, calendario y plazo30s, sin cambiar el detector.
- Cotizaciones CALL y PUT OPRA de Schwab: mismo vencimiento seleccionado con
  las reglas existentes. Se reutilizan rangos de primas, spread y selección
  ITM/primeros5OTM. Los strikes pueden diferir; no se presenta como straddle
  obligatorio. Se consideran hasta20 contratos más baratos aptos por lado y
  se elige la pareja de menor costo que cumpla presupuesto y mismo vencimiento.
- Consulta de catálogos por lado en paralelo; luego cotización de ambos
  contratos fijos en paralelo. Revalidación de cada contrato y señal al final.
  Tamaño Bid/Ask suficiente, cotizaciones con antigüedad máxima30s y diferencia
  temporal máxima3s. Se bloquean datos futuros, retrocedidos o sin Bid positivo.
- Ambas compras PAPER se modelan al Ask observado; ambas ventas al Bid observado.
  Entrada atómica en el modelo, no ejecución atómica real. No representa una
  prueba de fills ni de ejecución de órdenes multi-leg en Schwab.
- Presupuesto incluye ambas primas×100×cantidad y costos de entrada configurados.
  Resultado neto estimado incluye costos de entrada y salida. La tarifa inicial
  0.65USD por contrato/transacción es una hipótesis editable, no dato de cuenta.
- Tres escenarios ALTERNATIVOS sobre los mismos dos contratos: objetivos netos
  conjuntos10/15/20%, denominador costo total inicial incluyendo costos de compra.
  No se suman los escenarios como si fueran seis contratos ni como cartera única.
- Stop conjunto20% en todos los escenarios. Stop individual20% opcional,
  inicialmente seleccionado; congela la venta simulada de esa pata y mantiene
  el seguimiento de la otra. Al alcanzar objetivo/stop conjunto se venden las
  patas aún abiertas de ese escenario. Precio de salida = Bid observado, puede
  superar el umbral de pérdida si hubo un salto o hueco de observaciones.
- Cierre al final de la sesión oficial de la señal o cierre manual PAPER solo
  con cotizaciones válidas. Si faltan, queda pendiente: no se inventa una salida.
- No hay trailing stop, objetivo óptimo calibrado ni comparación contra una
  posición direccional implementados en esta entrega. Son estudios posteriores.

## Controles y persistencia

«Pausar nuevas entradas» conserva vigilancia de posiciones paper abiertas.
«Cerrar prueba al próximo Bid válido» solicita salida simulada. «Reanudar
seguimiento» recupera una prueba abierta tras detenerse el observador; no
compra de nuevo ni activa la cola REAL. Tras reinicio de la interfaz no se
reanuda automáticamente. Servidor web debe seguir funcionando, no depende
solo de mantener el navegador abierto. Un único ensayo abierto a la vez;
propietario/heartbeat en SQLite impide doble observación desde otros procesos,
y las escrituras vuelven a comprobar dueño/activación/pausa antes de entrar.

Muestreo REST aproximadamente1s más el tiempo de solicitudes; no es tick replay
ni captura todos los precios intermedios. Las estadísticas son de las
observaciones disponibles, sin extrapolar ganadoras entre muestras. Los
catálogos/cotizaciones pueden tardar varios segundos, especialmente en frío.

Journal exclusivo `exports/paired_paper/journal.sqlite3`, ignorado por Git.
Guarda configuración, señales, ambas compras estimadas, resultados de los tres
escenarios, salidas, mejor/peor% observado y cotizaciones muestreadas en tabla
separada. Descarga JSON de resultados y hasta50000 últimas observaciones.
No se consultan cuentas, balances, previews ni endpoints de órdenes. No se
importan posiciones manuales ni registros de la simulación actual/REAL.

Archivos: paired_paper_engine.py, paired_paper_store.py, paired_paper_runtime.py,
paired_options_panel.py. Navegación en operating_mode_page.py. Pruebas de
aritmética, recuperación, pausa, aislamiento y panel en tests/test_paired_paper.py.
Validación efectiva y comprobaciones actuales figuran en CURRENT_CONTEXT y
registro diario; evidencia privada en exports/trade_review/2026-11-18_paired_paper/.

Las horas de la interfaz se muestran en ET. Si una posición virtual no puede
recuperar datos (p.ej. expiró durante una interrupción), se puede archivar como
INCOMPLETE: sin inventar ventas y excluyendo escenarios pendientes de las
estadísticas de pruebas cerradas. Una prueba puede tener escenarios ya cerrados
y otros incompletos; la comparación presenta los conteos respectivos.
