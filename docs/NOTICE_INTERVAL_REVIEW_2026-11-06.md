# Avisos: intervalo y discrepancias TC2000 del 6 de noviembre

El usuario reporta dirección inferior en las velas que identifica como 9:30 de
TSLA/META/MU/QQQ, 10:30 de AMZN y ausencia de contacto en SLV 13:45. Es evidencia
del usuario pendiente de conciliar, no motivo para invertir etiquetas.

La auditoría de seis eventos originales y barras posteriores IEX está en
`exports/trade_review/2026-11-06_initial_origin/six_case_review.json`.
Todos los precios fuente superan su banda superior. En las cinco primeras
velas hay 15 minutos observados; SLV tiene diez. Los cierres posteriores no se
usan para decidir señales históricas. Esto verifica coherencia interna IEX,
no coincidencia con TC2000/Nasdaq Basic ni calidad del impulso.

Existe una ambigüedad comprobada de presentación: el aviso mostraba solamente
inicio, mientras el usuario confirmó previamente primera vela regular TC2000
etiquetada 9:45, es decir cierre. En IEX, AMZN 10:15–10:30 baja, mientras
10:30–10:45 sube y contiene el evento. La diferencia de etiquetas puede explicar
parte de la discrepancia; no demuestra por sí sola que los seis casos estén
resueltos. El SLV exportado termina 13:44:14, antes del evento 13:53:14, y no
permite comparar ese instante. No afirmar retraso del gráfico a partir de ello.

Cambio de avisos: cuatro líneas, intervalo completo con fecha, hora ET de fuente
con segundos, feed real, precio y banda correspondiente con seis decimales.
Identidad/deduplicación y primer tiempo fuente no cambian. No se añade espera,
filtro, cambio de dirección, fuente, expansión o regla de compras/salidas.
La exclusión V6 de aperturas ya fuera sigue activa; no corrige SLV por sí sola.

Validación: 65 tests focales OK en 19.267s; 26 tests OK en 0.841s después de
añadir marcador de versión del formato, con solapamiento. Diff check correcto.
Recarga exclusiva radar a las 14:49:51 ET: PID12548, revisión formato1,
heartbeat actual y companion SIM ready. Guardas verifican sin posiciones propias,
sin solicitudes pendientes, colas pausadas y hashes de control/colas/ledgers
intactos antes y después. Receptor sin reiniciar; no órdenes ni avisos de prueba.
El hash antiguo del módulo completo en el recibo del receptor precede al cambio
de formato; no afirmar que coincide con el archivo actual. El predicado V6 no se
modificó en esta revisión ni requiere nueva carga para este cambio de mensaje.
REAL conserva pendiente de reautorización conocido; no se comprueba aquí broker.

Pendiente para cerrar la investigación: exportaciones TC2000 que cubran los
intervalos de los eventos y sus referencias, especialmente los cinco símbolos
sin exportación de hoy y SLV actualizado. Comparar inicio y cierre explícitos,
precio y bandas; no ajustar umbrales para forzar coincidencia con una captura.
