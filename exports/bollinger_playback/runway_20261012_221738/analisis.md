# Recorrido del precio después de una salida Bollinger

Corte UTC: 2026-10-12T22:17:38.398733+00:00; últimos 90 días naturales; regla v3_bandas_en_apertura.
Se mide desde el precio del primer aviso reconstruido, con los minutos posteriores, hasta el primer cierre que regresa dentro de bandas o termina la misma vela de 15m. Se incluyen salidas sin avance; no se seleccionan solo movimientos exitosos.
Las bandas se recalculan parcialmente con datos conocidos. Para evitar atribuir orden dentro de una barra, se excluye el minuto que termina regresando dentro. Puede haber movimientos breves dentro de ese minuto que aquí no se contabilizan.
La tabla usa el máximo avance observado en cierres de minuto: es un máximo conocido retrospectivamente, no una salida ejecutable garantizada. P25 es el percentil 25, no un mínimo asegurado. Se guarda también la excursión de máximos/mínimos y el primer retroceso entre cierres.
Estos porcentajes corresponden al subyacente, no a ganancias de opciones. Sin costos, spread ni precio real de entrada. Fuente IEX; datos incompletos se excluyen y esto puede sesgar resultados. Últimos 30 días separados como contraste descriptivo, no validación independiente.

| Compañía | Casos | Sin avance % | P25 avance % | Mediana avance % | Alcanzó 0,10% | Alcanzó 0,20% |
|---|---:|---:|---:|---:|---:|---:|
| AAPL (ALPACA/iex) | 96 | 37.5 | 0.000 | 0.027 | 31.2% | 20.8% |
| NVDA (ALPACA/iex) | 77 | 36.4 | 0.000 | 0.061 | 40.3% | 16.9% |
| TSLA (ALPACA/iex) | 101 | 41.6 | 0.000 | 0.057 | 44.6% | 32.7% |
| AMD (ALPACA/iex) | 68 | 44.1 | 0.000 | 0.038 | 42.6% | 27.9% |
| META (ALPACA/iex) | 97 | 36.1 | 0.000 | 0.094 | 49.5% | 33.0% |
| MSFT (ALPACA/iex) | 110 | 45.5 | 0.000 | 0.008 | 26.4% | 14.5% |
| BABA (ALPACA/iex) | 50 | 42.0 | 0.000 | 0.035 | 38.0% | 12.0% |
| SPY (ALPACA/iex) | 70 | 42.9 | 0.000 | 0.012 | 12.9% | 2.9% |
| QQQ (ALPACA/iex) | 75 | 32.0 | 0.000 | 0.032 | 26.7% | 18.7% |
| IWM (ALPACA/iex) | 70 | 28.6 | 0.000 | 0.027 | 17.1% | 8.6% |
| DIA (ALPACA/iex) | 29 | 48.3 | 0.000 | 0.004 | 10.3% | 0.0% |
| MU (ALPACA/iex) | 85 | 38.8 | 0.000 | 0.071 | 44.7% | 31.8% |
| NIO (ALPACA/iex) | 35 | 74.3 | 0.000 | 0.000 | 25.7% | 20.0% |
| GLD (ALPACA/iex) | 46 | 26.1 | 0.001 | 0.025 | 21.7% | 13.0% |
| AMZN (ALPACA/iex) | 94 | 36.2 | 0.000 | 0.038 | 36.2% | 21.3% |
| NFLX (ALPACA/iex) | 78 | 33.3 | 0.000 | 0.034 | 33.3% | 20.5% |
| AVGO | 0 | — | — | — | — | — |

## Desglose por dirección y periodo

| Compañía | Dirección | Periodo | Casos | P25 % | Mediana % | Alcanzó 0,10% |
|---|---|---|---:|---:|---:|---:|
| AAPL | SUPERIOR | TOTAL | 59 | 0.000 | 0.050 | 42.4% |
| AAPL | SUPERIOR | ANTERIOR_60_DIAS | 38 | 0.000 | 0.107 | 50.0% |
| AAPL | SUPERIOR | RECIENTE_30_DIAS | 21 | 0.000 | 0.024 | 28.6% |
| AAPL | INFERIOR | TOTAL | 37 | 0.000 | 0.016 | 13.5% |
| AAPL | INFERIOR | ANTERIOR_60_DIAS | 25 | 0.000 | 0.027 | 16.0% |
| AAPL | INFERIOR | RECIENTE_30_DIAS | 12 | 0.000 | 0.007 | 8.3% |
| NVDA | SUPERIOR | TOTAL | 37 | 0.000 | 0.018 | 32.4% |
| NVDA | SUPERIOR | ANTERIOR_60_DIAS | 22 | 0.000 | 0.000 | 22.7% |
| NVDA | SUPERIOR | RECIENTE_30_DIAS | 15 | 0.000 | 0.079 | 46.7% |
| NVDA | INFERIOR | TOTAL | 40 | 0.000 | 0.090 | 47.5% |
| NVDA | INFERIOR | ANTERIOR_60_DIAS | 29 | 0.000 | 0.108 | 55.2% |
| NVDA | INFERIOR | RECIENTE_30_DIAS | 11 | 0.005 | 0.031 | 27.3% |
| TSLA | SUPERIOR | TOTAL | 49 | 0.000 | 0.026 | 36.7% |
| TSLA | SUPERIOR | ANTERIOR_60_DIAS | 35 | 0.000 | 0.009 | 40.0% |
| TSLA | SUPERIOR | RECIENTE_30_DIAS | 14 | 0.000 | 0.062 | 28.6% |
| TSLA | INFERIOR | TOTAL | 52 | 0.000 | 0.127 | 51.9% |
| TSLA | INFERIOR | ANTERIOR_60_DIAS | 30 | 0.000 | 0.101 | 50.0% |
| TSLA | INFERIOR | RECIENTE_30_DIAS | 22 | 0.000 | 0.154 | 54.5% |
| AMD | SUPERIOR | TOTAL | 35 | 0.000 | 0.002 | 34.3% |
| AMD | SUPERIOR | ANTERIOR_60_DIAS | 24 | 0.000 | 0.085 | 50.0% |
| AMD | SUPERIOR | RECIENTE_30_DIAS | 11 | 0.000 | 0.000 | 0.0% |
| AMD | INFERIOR | TOTAL | 33 | 0.000 | 0.117 | 51.5% |
| AMD | INFERIOR | ANTERIOR_60_DIAS | 25 | 0.000 | 0.059 | 48.0% |
| AMD | INFERIOR | RECIENTE_30_DIAS | 8 | 0.000 | 0.208 | 62.5% |
| META | SUPERIOR | TOTAL | 61 | 0.000 | 0.140 | 57.4% |
| META | SUPERIOR | ANTERIOR_60_DIAS | 45 | 0.000 | 0.157 | 60.0% |
| META | SUPERIOR | RECIENTE_30_DIAS | 16 | 0.000 | 0.079 | 50.0% |
| META | INFERIOR | TOTAL | 36 | 0.000 | 0.016 | 36.1% |
| META | INFERIOR | ANTERIOR_60_DIAS | 21 | 0.000 | 0.025 | 33.3% |
| META | INFERIOR | RECIENTE_30_DIAS | 15 | 0.000 | 0.000 | 40.0% |
| MSFT | SUPERIOR | TOTAL | 65 | 0.000 | 0.010 | 30.8% |
| MSFT | SUPERIOR | ANTERIOR_60_DIAS | 51 | 0.000 | 0.014 | 31.4% |
| MSFT | SUPERIOR | RECIENTE_30_DIAS | 14 | 0.000 | 0.005 | 28.6% |
| MSFT | INFERIOR | TOTAL | 45 | 0.000 | 0.005 | 20.0% |
| MSFT | INFERIOR | ANTERIOR_60_DIAS | 29 | 0.000 | 0.005 | 24.1% |
| MSFT | INFERIOR | RECIENTE_30_DIAS | 16 | 0.000 | 0.012 | 12.5% |
| BABA | SUPERIOR | TOTAL | 19 | 0.000 | 0.094 | 47.4% |
| BABA | SUPERIOR | ANTERIOR_60_DIAS | 12 | 0.000 | 0.000 | 33.3% |
| BABA | SUPERIOR | RECIENTE_30_DIAS | 7 | 0.100 | 0.124 | 71.4% |
| BABA | INFERIOR | TOTAL | 31 | 0.000 | 0.005 | 32.3% |
| BABA | INFERIOR | ANTERIOR_60_DIAS | 12 | 0.000 | 0.000 | 25.0% |
| BABA | INFERIOR | RECIENTE_30_DIAS | 19 | 0.000 | 0.028 | 36.8% |
| SPY | SUPERIOR | TOTAL | 30 | 0.000 | 0.017 | 13.3% |
| SPY | SUPERIOR | ANTERIOR_60_DIAS | 23 | 0.000 | 0.020 | 17.4% |
| SPY | SUPERIOR | RECIENTE_30_DIAS | 7 | 0.000 | 0.000 | 0.0% |
| SPY | INFERIOR | TOTAL | 40 | 0.000 | 0.010 | 12.5% |
| SPY | INFERIOR | ANTERIOR_60_DIAS | 29 | 0.000 | 0.006 | 10.3% |
| SPY | INFERIOR | RECIENTE_30_DIAS | 11 | 0.000 | 0.032 | 18.2% |
| QQQ | SUPERIOR | TOTAL | 29 | 0.000 | 0.028 | 17.2% |
| QQQ | SUPERIOR | ANTERIOR_60_DIAS | 21 | 0.000 | 0.041 | 14.3% |
| QQQ | SUPERIOR | RECIENTE_30_DIAS | 8 | 0.000 | 0.009 | 25.0% |
| QQQ | INFERIOR | TOTAL | 46 | 0.000 | 0.043 | 32.6% |
| QQQ | INFERIOR | ANTERIOR_60_DIAS | 31 | 0.003 | 0.041 | 25.8% |
| QQQ | INFERIOR | RECIENTE_30_DIAS | 15 | 0.000 | 0.044 | 46.7% |
| IWM | SUPERIOR | TOTAL | 33 | 0.000 | 0.027 | 15.2% |
| IWM | SUPERIOR | ANTERIOR_60_DIAS | 24 | 0.000 | 0.027 | 16.7% |
| IWM | SUPERIOR | RECIENTE_30_DIAS | 9 | 0.000 | 0.025 | 11.1% |
| IWM | INFERIOR | TOTAL | 37 | 0.003 | 0.027 | 18.9% |
| IWM | INFERIOR | ANTERIOR_60_DIAS | 25 | 0.010 | 0.032 | 16.0% |
| IWM | INFERIOR | RECIENTE_30_DIAS | 12 | 0.000 | 0.023 | 25.0% |
| DIA | SUPERIOR | TOTAL | 15 | 0.000 | 0.000 | 0.0% |
| DIA | SUPERIOR | ANTERIOR_60_DIAS | 11 | 0.000 | 0.000 | 0.0% |
| DIA | SUPERIOR | RECIENTE_30_DIAS | 4 | 0.000 | 0.000 | 0.0% |
| DIA | INFERIOR | TOTAL | 14 | 0.000 | 0.008 | 21.4% |
| DIA | INFERIOR | ANTERIOR_60_DIAS | 7 | 0.002 | 0.005 | 14.3% |
| DIA | INFERIOR | RECIENTE_30_DIAS | 7 | 0.000 | 0.012 | 28.6% |
| MU | SUPERIOR | TOTAL | 45 | 0.000 | 0.007 | 37.8% |
| MU | SUPERIOR | ANTERIOR_60_DIAS | 30 | 0.000 | 0.004 | 40.0% |
| MU | SUPERIOR | RECIENTE_30_DIAS | 15 | 0.000 | 0.018 | 33.3% |
| MU | INFERIOR | TOTAL | 40 | 0.000 | 0.120 | 52.5% |
| MU | INFERIOR | ANTERIOR_60_DIAS | 28 | 0.000 | 0.133 | 57.1% |
| MU | INFERIOR | RECIENTE_30_DIAS | 12 | 0.023 | 0.074 | 41.7% |
| NIO | SUPERIOR | TOTAL | 15 | 0.000 | 0.000 | 33.3% |
| NIO | SUPERIOR | ANTERIOR_60_DIAS | 12 | 0.000 | 0.000 | 41.7% |
| NIO | SUPERIOR | RECIENTE_30_DIAS | 3 | 0.000 | 0.000 | 0.0% |
| NIO | INFERIOR | TOTAL | 20 | 0.000 | 0.000 | 20.0% |
| NIO | INFERIOR | ANTERIOR_60_DIAS | 12 | 0.000 | 0.000 | 25.0% |
| NIO | INFERIOR | RECIENTE_30_DIAS | 8 | 0.000 | 0.000 | 12.5% |
| GLD | SUPERIOR | TOTAL | 24 | 0.000 | 0.024 | 20.8% |
| GLD | SUPERIOR | ANTERIOR_60_DIAS | 12 | 0.024 | 0.062 | 25.0% |
| GLD | SUPERIOR | RECIENTE_30_DIAS | 12 | 0.000 | 0.004 | 16.7% |
| GLD | INFERIOR | TOTAL | 22 | 0.003 | 0.030 | 22.7% |
| GLD | INFERIOR | ANTERIOR_60_DIAS | 15 | 0.013 | 0.059 | 26.7% |
| GLD | INFERIOR | RECIENTE_30_DIAS | 7 | 0.001 | 0.004 | 14.3% |
| AMZN | SUPERIOR | TOTAL | 38 | 0.000 | 0.014 | 34.2% |
| AMZN | SUPERIOR | ANTERIOR_60_DIAS | 25 | 0.000 | 0.000 | 28.0% |
| AMZN | SUPERIOR | RECIENTE_30_DIAS | 13 | 0.031 | 0.095 | 46.2% |
| AMZN | INFERIOR | TOTAL | 56 | 0.000 | 0.049 | 37.5% |
| AMZN | INFERIOR | ANTERIOR_60_DIAS | 38 | 0.004 | 0.051 | 42.1% |
| AMZN | INFERIOR | RECIENTE_30_DIAS | 18 | 0.000 | 0.022 | 27.8% |
| NFLX | SUPERIOR | TOTAL | 42 | 0.000 | 0.017 | 21.4% |
| NFLX | SUPERIOR | ANTERIOR_60_DIAS | 29 | 0.000 | 0.012 | 24.1% |
| NFLX | SUPERIOR | RECIENTE_30_DIAS | 13 | 0.000 | 0.021 | 15.4% |
| NFLX | INFERIOR | TOTAL | 36 | 0.011 | 0.083 | 47.2% |
| NFLX | INFERIOR | ANTERIOR_60_DIAS | 22 | 0.014 | 0.069 | 45.5% |
| NFLX | INFERIOR | RECIENTE_30_DIAS | 14 | 0.022 | 0.122 | 50.0% |

## Cobertura y exclusiones
- AAPL: 102 detecciones; exclusiones {'SIN_MINUTO_POSTERIOR_EN_VELA': 6}.
- AMD: 78 detecciones; exclusiones {'SIN_MINUTO_POSTERIOR_EN_VELA': 4, 'DATOS_INCOMPLETOS': 6}.
- AMZN: 97 detecciones; exclusiones {'SIN_MINUTO_POSTERIOR_EN_VELA': 3}.
- BABA: 70 detecciones; exclusiones {'DATOS_INCOMPLETOS': 17, 'SIN_MINUTO_POSTERIOR_EN_VELA': 3}.
- DIA: 61 detecciones; exclusiones {'DATOS_INCOMPLETOS': 29, 'SIN_MINUTO_POSTERIOR_EN_VELA': 3}.
- GLD: 65 detecciones; exclusiones {'SIN_MINUTO_POSTERIOR_EN_VELA': 5, 'DATOS_INCOMPLETOS': 14}.
- IWM: 79 detecciones; exclusiones {'SIN_MINUTO_POSTERIOR_EN_VELA': 9}.
- META: 103 detecciones; exclusiones {'SIN_MINUTO_POSTERIOR_EN_VELA': 5, 'DATOS_INCOMPLETOS': 1}.
- MSFT: 116 detecciones; exclusiones {'SIN_MINUTO_POSTERIOR_EN_VELA': 5, 'DATOS_INCOMPLETOS': 1}.
- MU: 95 detecciones; exclusiones {'SIN_MINUTO_POSTERIOR_EN_VELA': 10}.
- NFLX: 83 detecciones; exclusiones {'SIN_MINUTO_POSTERIOR_EN_VELA': 5}.
- NIO: 78 detecciones; exclusiones {'DATOS_INCOMPLETOS': 38, 'SIN_MINUTO_POSTERIOR_EN_VELA': 5}.
- NVDA: 81 detecciones; exclusiones {'SIN_MINUTO_POSTERIOR_EN_VELA': 3, 'DATOS_INCOMPLETOS': 1}.
- QQQ: 80 detecciones; exclusiones {'SIN_MINUTO_POSTERIOR_EN_VELA': 4, 'DATOS_INCOMPLETOS': 1}.
- SPY: 76 detecciones; exclusiones {'SIN_MINUTO_POSTERIOR_EN_VELA': 6}.
- TSLA: 109 detecciones; exclusiones {'SIN_MINUTO_POSTERIOR_EN_VELA': 8}.

No hay porcentaje mínimo positivo garantizado. El suelo observado puede ser cero. Un objetivo de precio debería validarse prospectivamente con entradas, stops y costos; no se cambiaron alertas ni se activó ejecución.
