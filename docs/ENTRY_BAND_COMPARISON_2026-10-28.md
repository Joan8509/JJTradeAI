# Comparación observacional de expansión3% y5%

El usuario eligió28/10/2026 comparar5% manteniendo activo3%. Esta decisión
sustituye la consulta pendiente; no autoriza activar5% como filtro de entrada.

`entry_band_comparison.py` calcula la expansión de CADA banda con la fórmula
compartida y el ancho previo, usando el snapshot ya disponible. Registra PASS_5,
BELOW_5 oUNKNOWN; falta de evidencia nunca se transforma en una aprobación.
No solicita datos, espera confirmación temporal, autoriza, rechaza ni despacha.

En simulación observada, la compra guarda metadatos junto al payload existente:
revisión, umbral activo/candidato, porcentajes y timestamp de la geometría.
No agrega transacción SQLite, WebSocket o consulta REST a la ruta de entrada.
SIGNAL_READY incorpora la comparación calculada con el tick ya validado,
sin una lectura adicional de estado. Un fallo del estudio no impide comprar.

`scripts/report_entry_band_comparison.py --day AAAA-MM-DD` lee el ledger sin
modificarlo y agrupa operaciones realmente llenadas y resultados reales de
esa simulación por categoría. El día corresponde a la entrada ET; una operación
abierta permanece abierta. Operaciones antiguas sin metadatos quedan UNKNOWN.
La salida privada se guarda en exports/trade_review/band_comparison/.

Esto compara calidad descriptiva en los instantes de entrada del sistema3%.
NO simula un segundo sistema que esperara5%, ni sus opciones/fills/resultados;
5% podría cumplirse después y generar entradas distintas. No imputar PnL de
ese sistema alternativo ni convertir el estudio de un día en filtro aprendido.
La memoria sigue siendo descriptiva; estrategia, tolerancias,30s,stop y avisos
permanecen iguales. Órdenes realesOFF. Carga y pruebas: CURRENT_CONTEXT/diario.
