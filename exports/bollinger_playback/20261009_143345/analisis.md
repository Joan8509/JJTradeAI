# Playback: salida de Bollinger con volatilidad, 15 minutos

Corte UTC: 2026-10-09T14:33:45.098655+00:00. Ventana: últimos 30 días naturales.
Versión fija: v2_sin_apertura_expuesta. Fuente: barras disponibles; cada proveedor/feed se mantiene separado.

Se reconstruye minuto a minuto la vela de 15m en formación, sin usar su cierre futuro. Se exige cierre previo dentro de bandas, apertura dentro de las bandas previas, expansión de ambas bandas y pendiente del centro a favor de la salida. Se excluyen aperturas ya expuestas fuera de las bandas previas.

Positivo significa que el precio del subyacente termina a favor de la salida. No mide rentabilidad de opciones ni incluye spread, comisiones o deslizamiento. Las alertas son observaciones tempranas. Este estudio no demuestra precisión futura.

Los porcentajes usan ventanas completas sin solapamiento dentro de cada compañía/dirección/fuente/horizonte. Los casos sin datos completos se excluyen: esto puede sesgar la muestra. No se suman horizontes como operaciones independientes.

## Continuidad por horizonte y fuente

| Fuente | Minutos | Casos | Positivos | Negativos | Sin cambio | % positivo |
|---|---:|---:|---:|---:|---:|---:|
| ALPACA/iex | 5 | 350 | 176 | 166 | 8 | 50.3 |
| ALPACA/iex | 15 | 280 | 141 | 136 | 3 | 50.4 |
| ALPACA/iex | 30 | 235 | 116 | 118 | 1 | 49.4 |
| ALPACA/iex | 60 | 180 | 82 | 98 | 0 | 45.6 |

## Cada compañía: continuidad a 15 minutos

| Compañía | Fuente | Salida | Casos | Sesiones | % positivo | Intervalo descriptivo 95% | Retorno direccional medio % | Evidencia |
|---|---|---|---:|---:|---:|---|---:|---|
| AAPL | ALPACA/iex | Bajista | 12 | 10 | 25.0 | 8.89–53.23 | -0.1645 | MUESTRA_INSUFICIENTE |
| AAPL | ALPACA/iex | Alcista | 18 | 12 | 55.56 | 33.72–75.44 | 0.0491 | MUESTRA_INSUFICIENTE |
| NVDA | ALPACA/iex | Bajista | 12 | 10 | 41.67 | 19.33–68.05 | 0.0253 | MUESTRA_INSUFICIENTE |
| NVDA | ALPACA/iex | Alcista | 10 | 7 | 30.0 | 10.78–60.32 | -0.3217 | MUESTRA_INSUFICIENTE |
| TSLA | ALPACA/iex | Bajista | 13 | 9 | 61.54 | 35.52–82.29 | 0.2004 | MUESTRA_INSUFICIENTE |
| TSLA | ALPACA/iex | Alcista | 9 | 9 | 66.67 | 35.42–87.94 | 0.2936 | MUESTRA_INSUFICIENTE |
| AMD | ALPACA/iex | Bajista | 5 | 5 | 40.0 | 11.76–76.93 | -0.5169 | MUESTRA_INSUFICIENTE |
| AMD | ALPACA/iex | Alcista | 8 | 7 | 50.0 | 21.52–78.48 | 0.1744 | MUESTRA_INSUFICIENTE |
| META | ALPACA/iex | Bajista | 13 | 10 | 61.54 | 35.52–82.29 | 0.2158 | MUESTRA_INSUFICIENTE |
| META | ALPACA/iex | Alcista | 16 | 10 | 18.75 | 6.59–43.01 | -0.2671 | MUESTRA_INSUFICIENTE |
| MSFT | ALPACA/iex | Bajista | 13 | 7 | 61.54 | 35.52–82.29 | 0.0773 | MUESTRA_INSUFICIENTE |
| MSFT | ALPACA/iex | Alcista | 12 | 8 | 58.33 | 31.95–80.67 | 0.0203 | MUESTRA_INSUFICIENTE |
| BABA | ALPACA/iex | Bajista | 7 | 5 | 85.71 | 48.69–97.43 | 0.0579 | MUESTRA_INSUFICIENTE |
| BABA | ALPACA/iex | Alcista | 5 | 3 | 40.0 | 11.76–76.93 | -0.0793 | MUESTRA_INSUFICIENTE |
| SPY | ALPACA/iex | Bajista | 13 | 8 | 61.54 | 35.52–82.29 | 0.0379 | MUESTRA_INSUFICIENTE |
| SPY | ALPACA/iex | Alcista | 3 | 3 | 33.33 | 6.15–79.23 | -0.0376 | MUESTRA_INSUFICIENTE |
| QQQ | ALPACA/iex | Bajista | 12 | 8 | 66.67 | 39.06–86.19 | 0.1134 | MUESTRA_INSUFICIENTE |
| QQQ | ALPACA/iex | Alcista | 6 | 5 | 50.0 | 18.76–81.24 | -0.037 | MUESTRA_INSUFICIENTE |
| IWM | ALPACA/iex | Bajista | 8 | 7 | 87.5 | 52.91–97.76 | 0.0769 | MUESTRA_INSUFICIENTE |
| IWM | ALPACA/iex | Alcista | 6 | 5 | 50.0 | 18.76–81.24 | 0.0294 | MUESTRA_INSUFICIENTE |
| DIA | ALPACA/iex | Bajista | 1 | 1 | 100.0 | 20.65–100.0 | 0.0241 | MUESTRA_INSUFICIENTE |
| DIA | ALPACA/iex | Alcista | 2 | 2 | 100.0 | 34.24–100.0 | 0.1718 | MUESTRA_INSUFICIENTE |
| MU | ALPACA/iex | Bajista | 11 | 6 | 54.55 | 28.01–78.73 | 0.0391 | MUESTRA_INSUFICIENTE |
| MU | ALPACA/iex | Alcista | 13 | 8 | 23.08 | 8.18–50.26 | -0.1059 | MUESTRA_INSUFICIENTE |
| NIO | ALPACA/iex | Bajista | 1 | 1 | 100.0 | 20.65–100.0 | 0.4049 | MUESTRA_INSUFICIENTE |
| NIO | ALPACA/iex | Alcista | 0 | 0 | None | 0.0–0.0 | None | MUESTRA_INSUFICIENTE |
| GLD | ALPACA/iex | Bajista | 2 | 2 | 100.0 | 34.24–100.0 | 0.138 | MUESTRA_INSUFICIENTE |
| GLD | ALPACA/iex | Alcista | 1 | 1 | 100.0 | 20.65–100.0 | 0.0931 | MUESTRA_INSUFICIENTE |
| AMZN | ALPACA/iex | Bajista | 13 | 9 | 46.15 | 23.21–70.86 | 0.0739 | MUESTRA_INSUFICIENTE |
| AMZN | ALPACA/iex | Alcista | 9 | 7 | 55.56 | 26.66–81.12 | 0.0913 | MUESTRA_INSUFICIENTE |
| NFLX | ALPACA/iex | Bajista | 12 | 9 | 33.33 | 13.81–60.94 | -0.0172 | MUESTRA_INSUFICIENTE |
| NFLX | ALPACA/iex | Alcista | 14 | 7 | 35.71 | 16.34–61.24 | -0.1128 | MUESTRA_INSUFICIENTE |
| AVGO | — | — | 0 | 0 | — | — | — | Sin historial evaluable |

## Comportamiento y exclusiones

Las excursiones miden el máximo avance favorable y el máximo retroceso adverso dentro de la ventana; no indican cuál ocurrió primero. Las medias siguientes incluyen todas las detecciones evaluables, incluidas ventanas solapadas; son exploratorias.

- 5m: 352 detecciones evaluables; avance favorable medio 0.169%; retroceso adverso medio 0.153%; 141 tuvieron algún avance favorable pero terminaron negativas. Exclusiones: {'SIN_RECORRIDO_ANTES_DEL_CIERRE': 12, 'DATOS_INCOMPLETOS': 45}.

- 15m: 294 detecciones evaluables; avance favorable medio 0.291%; retroceso adverso medio 0.267%; 129 tuvieron algún avance favorable pero terminaron negativas. Exclusiones: {'DATOS_INCOMPLETOS': 75, 'SIN_RECORRIDO_ANTES_DEL_CIERRE': 40}.

- 30m: 262 detecciones evaluables; avance favorable medio 0.373%; retroceso adverso medio 0.371%; 122 tuvieron algún avance favorable pero terminaron negativas. Exclusiones: {'DATOS_INCOMPLETOS': 89, 'SIN_RECORRIDO_ANTES_DEL_CIERRE': 58}.

- 60m: 218 detecciones evaluables; avance favorable medio 0.496%; retroceso adverso medio 0.488%; 115 tuvieron algún avance favorable pero terminaron negativas. Exclusiones: {'DATOS_INCOMPLETOS': 110, 'SIN_RECORRIDO_ANTES_DEL_CIERRE': 80, 'PENDIENTE': 1}.

Detecciones reconstruidas desde 2026-09-09T14:37:00+00:00 hasta 2026-10-09T13:35:00+00:00 (UTC).

Los intervalos de Wilson son descriptivos: las compañías pueden moverse juntas y no hay una validación fuera de muestra. No se optimizaron parámetros usando estos resultados. Se necesita contrastar las detecciones en vivo y ampliar la cobertura antes de establecer filtros de aprobación.
