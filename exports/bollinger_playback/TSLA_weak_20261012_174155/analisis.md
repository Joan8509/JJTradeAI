# TSLA: salidas débiles de Bollinger 15m

Corte UTC: 2026-10-12T17:41:55.935094+00:00. Regla: v3_bandas_en_apertura. Últimos 90 días naturales; últimos 30 separados para comparación temporal.

Débil en este análisis = vuelve a cerrar dentro de sus bandas parciales en alguno de los dos minutos posteriores. Se compara también continuidad a 15m. Las bandas se recalculan en cada minuto sin usar el cierre futuro de la vela. No mide resultado de opciones ni precio de ejecución.

Los grupos de exposición (<1%, 1–5%, >=5% del ancho de bandas) son exploratorios, no umbrales aprobados. Persistencia es un resultado posterior: no está disponible en el aviso inicial. Se excluyen ventanas incompletas y solapadas; las exclusiones pueden sesgar resultados.

## Fuente ALPACA/iex
Detectadas: 107. Exclusiones: {'SIN_RECORRIDO_ANTES_DEL_CIERRE': 9, 'VENTANA_SOLAPADA': 6, 'DATOS_INCOMPLETOS': 2}.

| Periodo | Comparación | Grupo | Casos | Regresa dentro en 2m % | Positivo a 15m % | Retorno medio 15m % |
|---|---|---|---:|---:|---:|---:|
| ANTERIOR_60_DIAS | TOTAL | Todas | 64 | 46.9 | 45.3 | -0.0391 |
| ANTERIOR_60_DIAS | exposure_group | 1–5% | 28 | 50.0 | 46.4 | -0.0084 |
| ANTERIOR_60_DIAS | exposure_group | <1% | 14 | 71.4 | 35.7 | -0.0119 |
| ANTERIOR_60_DIAS | exposure_group | >=5% | 22 | 27.3 | 50.0 | -0.0956 |
| ANTERIOR_60_DIAS | time_group | 09:30–10:00 | 17 | 58.8 | 58.8 | 0.1209 |
| ANTERIOR_60_DIAS | time_group | 10:00–11:00 | 19 | 42.1 | 36.8 | -0.0727 |
| ANTERIOR_60_DIAS | time_group | 11:00–14:00 | 14 | 42.9 | 35.7 | -0.0514 |
| ANTERIOR_60_DIAS | time_group | 14:00–16:00 | 14 | 42.9 | 50.0 | -0.1757 |
| ANTERIOR_60_DIAS | side | INFERIOR | 31 | 38.7 | 51.6 | 0.0445 |
| ANTERIOR_60_DIAS | side | SUPERIOR | 33 | 54.5 | 39.4 | -0.1177 |
| ANTERIOR_60_DIAS | COMPARACION_EXPLORATORIA | Exposición >=1% | 50 | 40.0 | 48.0 | -0.0467 |
| ANTERIOR_60_DIAS | COMPARACION_EXPLORATORIA | Exposición >=5% | 22 | 27.3 | 50.0 | -0.0956 |
| ANTERIOR_60_DIAS | COMPARACION_EXPLORATORIA | Expansión >=5% | 60 | 48.3 | 43.3 | -0.0501 |
| RECIENTE_30_DIAS | TOTAL | Todas | 26 | 38.5 | 50.0 | 0.1065 |
| RECIENTE_30_DIAS | exposure_group | 1–5% | 11 | 36.4 | 63.6 | 0.3015 |
| RECIENTE_30_DIAS | exposure_group | <1% | 5 | 80.0 | 40.0 | 0.121 |
| RECIENTE_30_DIAS | exposure_group | >=5% | 10 | 20.0 | 40.0 | -0.1152 |
| RECIENTE_30_DIAS | time_group | 09:30–10:00 | 9 | 33.3 | 66.7 | 0.2735 |
| RECIENTE_30_DIAS | time_group | 10:00–11:00 | 7 | 57.1 | 57.1 | 0.1802 |
| RECIENTE_30_DIAS | time_group | 11:00–14:00 | 4 | 50.0 | 25.0 | -0.1006 |
| RECIENTE_30_DIAS | time_group | 14:00–16:00 | 6 | 16.7 | 33.3 | -0.0921 |
| RECIENTE_30_DIAS | side | INFERIOR | 17 | 29.4 | 41.2 | 0.0074 |
| RECIENTE_30_DIAS | side | SUPERIOR | 9 | 55.6 | 66.7 | 0.2936 |
| RECIENTE_30_DIAS | COMPARACION_EXPLORATORIA | Exposición >=1% | 21 | 28.6 | 52.4 | 0.103 |
| RECIENTE_30_DIAS | COMPARACION_EXPLORATORIA | Exposición >=5% | 10 | 20.0 | 40.0 | -0.1152 |
| RECIENTE_30_DIAS | COMPARACION_EXPLORATORIA | Expansión >=5% | 26 | 38.5 | 50.0 | 0.1065 |

Asociaciones descriptivas, no causas demostradas. Las muestras pequeñas y condiciones de mercado pueden explicar diferencias. No se cambiaron alertas ni se seleccionó automáticamente un filtro. Las medias 20/40/100/200 quedan pendientes de confirmar SMA o EMA.
