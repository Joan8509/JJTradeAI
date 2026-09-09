# Estrategias registradas

Este documento es la fuente oficial para verificar que ninguna estrategia o
metodología Investep se pierda durante el desarrollo de JJTrade AI.

## Estados documentales

- `DOCUMENTADA`: cuenta con criterios documentales oficiales.
- `EN_PROCESO`: existe documentación parcial, pero falta completar su ficha.
- `PENDIENTE`: todavía no cuenta con documentación estratégica.
- `IMPLEMENTACION_PARCIAL`: existe un detector auditable, pero conserva
  criterios obligatorios manuales o pendientes de umbral.
- `IMPLEMENTADA`: la función asignada está codificada y probada; no significa
  que pueda decidir por sí sola.

Los valores `POR_DEFINIR` indican que el rol correspondiente requiere criterios
oficiales antes de clasificarse. No deben interpretarse como reglas operativas.

## Prioridad Alta - Documentadas

| Nombre | Categoría | Prioridad | Estado | Archivo asociado | ¿Detector futuro? | ¿Confirmación? | ¿Invalidación? | Notas |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Expuesto en Bollinger | `BOLLINGER` | `ALTA` | `IMPLEMENTADA` | [`docs/INVESTEP_ENGINE.md`](INVESTEP_ENGINE.md) | Sí | No | No | Detecta exposición; nunca emite una entrada directa. |
| CT15 - Cambio de Tendencia en 15 | `CAMBIO_TENDENCIA` | `ALTA` | `IMPLEMENTACION_PARCIAL` | [`docs/strategies/CT15.md`](strategies/CT15.md) | Sí | No | No | Estrategia principal; solo aplica en la primera vela de 15 minutos. |

## Prioridad Alta - Pendiente de Documentar

| Nombre | Categoría | Prioridad | Estado | Archivo asociado | ¿Detector futuro? | ¿Confirmación? | ¿Invalidación? | Notas |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Disipadores | `DISIPADORES` | `ALTA` | `EN_PROCESO` | [`docs/strategies/DISIPADORES.md`](strategies/DISIPADORES.md) | `POR_DEFINIR` | Sí | Sí | Componente definido; falta confirmar si existe estrategia independiente. |
| Cambio de Tendencia en Hora | `CAMBIO_TENDENCIA` | `ALTA` | `IMPLEMENTACION_PARCIAL` | [`docs/strategies/CAMBIO_TENDENCIA_HORA.md`](strategies/CAMBIO_TENDENCIA_HORA.md) | Sí | Sí | Sí | Detector parcial con línea y cierre explícitos. |
| Punto Medio | `PUNTO_MEDIO` | `ALTA` | `EN_PROCESO` | [`docs/strategies/PUNTO_MEDIO.md`](strategies/PUNTO_MEDIO.md) | No | Sí | Sí | Componente transversal; umbrales cuantitativos pendientes. |
| Volatilidad | `VOLATILIDAD` | `ALTA` | `EN_PROCESO` | [`docs/strategies/VOLATILIDAD.md`](strategies/VOLATILIDAD.md) | No | Sí | Sí | Estados metodológicos extraídos; umbrales cuantitativos pendientes. |
| Momentum de una Empresa | `MOMENTUM` | `ALTA` | `IMPLEMENTACION_PARCIAL` | [`docs/strategies/MOMENTUM.md`](strategies/MOMENTUM.md) | Sí | Sí | Sí | Exige volatilidad abierta en Diario. |
| Primer Salto / Segundo Salto | `PRIMER_SALTO` | `ALTA` | `IMPLEMENTACION_PARCIAL` | [`docs/strategies/PRIMER_SALTO.md`](strategies/PRIMER_SALTO.md) | Sí | Sí | Sí | Evalúa un primer salto respetado y confirmaciones para el siguiente. |
| Salto de Lateralidad en Hora | `PRIMER_SALTO` | `ALTA` | `IMPLEMENTACION_PARCIAL` | [`docs/strategies/SALTO_LATERALIDAD_HORA.md`](strategies/SALTO_LATERALIDAD_HORA.md) | Sí | Sí | Sí | Nueva clase de repaso; detecta continuidad desde lateralidad en Hora con revisiones obligatorias. |
| Saliendo de Bollinger con Volatilidad | `BOLLINGER` / `VOLATILIDAD` | `ALTA` | `IMPLEMENTACION_PARCIAL` | [`docs/strategies/SALIENDO_BOLLINGER_VOLATILIDAD.md`](strategies/SALIENDO_BOLLINGER_VOLATILIDAD.md) | Sí | Sí | Sí | Variante registrada como retorno desde lateralidad. |
| Efecto Imán | `PUNTO_MEDIO` | `ALTA` | `IMPLEMENTACION_PARCIAL` | [`docs/strategies/EFECTO_IMAN.md`](strategies/EFECTO_IMAN.md) | Sí | Sí | Sí | Detector multitemporal con revisiones externas. |
| Rebote en Punto Medio | `PUNTO_MEDIO` | `ALTA` | `IMPLEMENTACION_PARCIAL` | [`docs/strategies/REBOTE_PUNTO_MEDIO.md`](strategies/REBOTE_PUNTO_MEDIO.md) | Sí | Sí | Sí | Requiere vela cerrada de Hora. |
| Panorama General Multi-temporal | `PANORAMA` | `ALTA` | `IMPLEMENTACION_PARCIAL` | [`docs/strategies/PANORAMA_GENERAL.md`](strategies/PANORAMA_GENERAL.md) | No | Sí | Sí | Resumen objetivo con aprobación humana. |
| Índices y ETF | `PANORAMA` | `ALTA` | `EN_PROCESO` | [`docs/strategies/INDICES.md`](strategies/INDICES.md) | No | Sí | Sí | Contexto dinámico; requiere composición, ponderaciones y noticias actualizadas. |
| Movimientos en Bloque | `PANORAMA` | `ALTA` | `EN_PROCESO` | [`docs/strategies/MOVIMIENTOS_EN_BLOQUE.md`](strategies/MOVIMIENTOS_EN_BLOQUE.md) | No | Sí | Sí | Confirmación contextual; nunca sustituye la evaluación individual del activo. |
| Confirmaciones | `CONFIRMACION` | `ALTA` | `IMPLEMENTADA` | [`docs/strategies/CONFIRMACIONES.md`](strategies/CONFIRMACIONES.md) | No | Sí | No | Contrato obligatorio de criterios. |
| Invalidaciones | `INVALIDACION` | `ALTA` | `IMPLEMENTACION_PARCIAL` | [`docs/strategies/INVALIDACIONES.md`](strategies/INVALIDACIONES.md) | No | No | Sí | Bloqueos comunes y específicos. |
| Techos y Pisos por Medias Móviles | `PANORAMA` | `ALTA` | `IMPLEMENTACION_PARCIAL` | [`docs/strategies/MEDIAS_TECHOS_PISOS.md`](strategies/MEDIAS_TECHOS_PISOS.md) | No | Sí | Sí | Mapa geométrico sin umbral inventado. |
| Distancia Spot / Strike | `RIESGO` | `ALTA` | `EN_PROCESO` | [`docs/strategies/OPCIONES_COMPRA_VENTA.md`](strategies/OPCIONES_COMPRA_VENTA.md) | No | Sí | Sí | Regla identificada; falta tabla oficial por activo. |
| Bid / Ask Spread | `RIESGO` | `ALTA` | `EN_PROCESO` | [`docs/strategies/OPCIONES_COMPRA_VENTA.md`](strategies/OPCIONES_COMPRA_VENTA.md) | No | Sí | Sí | Invalida la entrada si es excesivo; límite exacto pendiente. |
| Plan de entrada y salida | `RIESGO` | `ALTA` | `EN_PROCESO` | [`docs/strategies/OPCIONES_COMPRA_VENTA.md`](strategies/OPCIONES_COMPRA_VENTA.md) | No | No | Sí | Datos mínimos definidos; gestión monetaria y salida pendientes. |
| Falsos cambios de tendencia | `INVALIDACION` / `CAMBIO_TENDENCIA` | `ALTA` | `EN_PROCESO` | [`docs/strategies/FALSOS_CAMBIOS_TENDENCIA.md`](strategies/FALSOS_CAMBIOS_TENDENCIA.md) | No | No | Sí | Casos documentados se expresan como criterios fallidos. |

## Regla de mantenimiento

Toda estrategia o metodología nueva debe agregarse a este índice antes de ser
implementada. Su estado, categoría, prioridad, archivo y rol dentro del pipeline
deben mantenerse actualizados durante todo su ciclo de vida.

Un elemento `PENDIENTE` o `POR_DEFINIR` no puede convertirse en lógica. Una
`IMPLEMENTACION_PARCIAL` puede medir evidencia objetiva, pero no puede superar
la decisión mientras conserve criterios obligatorios sin confirmar.
