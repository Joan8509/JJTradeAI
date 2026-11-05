# Continuidad de JJTradeAI — 4 de noviembre de 2026

Resumen público para el guardado solicitado en GitHub. El contexto íntegro anterior
y los originales resumidos se conservan localmente en
exports/trade_review/2026-11-04_github_checkpoint/. Los diarios SESSION_STATE y
revisiones privadas conservan el historial operativo. Leerlos en la VPS antes de
diagnosticar eventos concretos; un clon no contiene configuración ni datos privados.

## Decisiones vigentes

- Simulación automática independiente de cuenta, permisos, journal y cola REAL.
- Estrategia v5, Bollinger15m20/2 ddof0, apertura dentro de bandas actuales,
  ruptura direccional y expansión mínima3% por cada banda respecto al ancho previo.
  El5% es histórico/comparativo; no sustituye el3% actual.
- Prioridad de entrada inmediata con estrategia válida; caducidad30s desde la
  primera señal y frescura3s. No renovar señales ni quitar controles para acelerar.
- ITM y primeros5strikes OTM; QQQ0.30–0.70 autorizado. Fondos, costos, expiración,
  spread y cotizaciones actuales siguen siendo requisitos de cada compra.
- Primera compra REAL confirmada, incluso parcial, excluye las demás compañías
  de la cola. Vender no las rearma automáticamente.
- Objetivo elegido: tras compra final, preview exacto y venta LIMIT DAY en Schwab.
  WORKING y FILLED son distintos. Stop20% local vigilado en VPS; cancelar y conciliar
  salidas pendientes antes de vender el remanente al Bid. Sin STOP/OCO nativo.
- Ventas externas del contrato propio se concilian y mantienen pausa/exclusiones;
  no se adoptan compras externas ni se repiten órdenes inciertas.

## Dashboard y módulos guardados

Cuenta se elige una vez mediante Consultar conexión y cuentas, y se conserva.
Activar preparación guarda/arma explícitamente y abre Cola real. Pausar cambia a
Activar para reanudar la misma sesión; Quitar una y Eliminar todas retiran solo
pendientes sin solicitud/reserva. Las salidas continúan durante la pausa.
Se retiran Propuestas y botones redundantes. Seis pestañas REAL ejecutan solo el
contenido activo. Streamlit mínimo1.66, versión instalada y probada; no se instaló
ninguna dependencia para este guardado. Resultados muestran fills confirmados,
cierres conciliados y ganancias/pérdidas brutas.

Diagnósticos conservan primer intento/fallo en memoria acotada, publicados en
heartbeat cifrado; no se recuperan tras reiniciar el host. TLS y preparación de
contratos se adelantan fuera de la entrada; precios, órdenes, avisos y cierres
externos usan roles independientes. Nasdaq Basic no está conectado; el contexto
privado mantiene la comparación con TC2000 y la fuente IEX de esta instalación.

## Validación y continuidad

379 pruebas offline aprobadas en36.913s el04/11, sin órdenes ni avisos reales.
Interfaz de pestañas comprobada por HTTPS/WSS a21:35ET, conservando ejecutor y
estados privados. Es evidencia histórica, no acredita procesos, cuenta o cola
actuales. El guardado Git no reinicia servicios ni activa compras.

Publicación: GITHUB_CHECKPOINT_2026-11-04.md y log Git. Credenciales, bases, estados,
operaciones individuales y diarios privados quedan excluidos del repositorio.
Siguiente paso operativo: comprobar procesos, heartbeat, conexión y estado de cola
antes de declarar disponibilidad; no rearmar por abrir la app o clonar Git.
Reglas: STRATEGY_OPERATING_CONTRACT.md. Uso: GUIA_OPERACION_REAL.md.
