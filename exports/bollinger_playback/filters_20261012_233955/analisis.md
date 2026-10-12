# Comparacion de filtros Bollinger con medias y niveles

Corte UTC: 2026-10-12T23:39:55.806979+00:00. Ventana 180 dias; 120 entrenamiento, 30 validacion, 30 prueba reciente.
Los candidatos se fijaron antes de ejecutar. La prueba reciente ya fue explorada en conversaciones anteriores: no es validacion prospectiva independiente. No se usa cierre futuro para medias ni confirmaciones. No se considera ATH real: maximo del historial disponible previo.
Espera dentro de la misma vela; cancela al regresar dentro. Se recalculan precio y momento de cada aviso retenido. Evaluacion a 5 y 15m desde ese nuevo momento. Ventanas incompletas se excluyen y cada candidato se desolapa por simbolo/fuente, incluso entre direcciones. Diferentes muestras pueden sesgar comparaciones.
Espacio toma posibles pisos/techos, roles SMA desconocidos por delante, cierre anterior y maximo disponible. Datos insuficientes o cierre no verificado impiden dar por suficiente el espacio. Continuidad favorable de una SMA no se trata automaticamente como barrera.
No hay beneficios de opciones, costos ni ejecuciones. Las companias pueden moverse correlacionadas. No se elige un ganador por porcentaje reciente ni se cambian alertas automaticamente.

| Candidato | Periodo | Avisos | Casos sin solapar | Positivo 15m % | Retorno medio 15m % | Positivos suprimidos* | Negativos suprimidos* | Demora media m |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| BASE | ENTRENAMIENTO | 1829 | 1306 | 47.47 | -0.0094 | 0 | 0 | 0.0 |
| BASE | VALIDACION | 446 | 322 | 51.86 | 0.0253 | 0 | 0 | 0.0 |
| BASE | PRUEBA_RECIENTE | 446 | 293 | 49.15 | 0.0107 | 0 | 0 | 0.0 |
| EXPOSICION_1 | ENTRENAMIENTO | 1583 | 1135 | 48.11 | -0.0099 | 75 | 113 | 0.13 |
| EXPOSICION_1 | VALIDACION | 392 | 288 | 55.21 | 0.0361 | 11 | 26 | 0.08 |
| EXPOSICION_1 | PRUEBA_RECIENTE | 400 | 266 | 49.62 | 0.0155 | 12 | 18 | 0.11 |
| EXPOSICION_3 | ENTRENAMIENTO | 1246 | 898 | 46.21 | -0.0165 | 191 | 248 | 0.39 |
| EXPOSICION_3 | VALIDACION | 324 | 241 | 57.68 | 0.0441 | 26 | 61 | 0.43 |
| EXPOSICION_3 | PRUEBA_RECIENTE | 315 | 217 | 48.39 | 0.012 | 35 | 49 | 0.39 |
| EXPOSICION_1_PERSISTENCIA | ENTRENAMIENTO | 1046 | 783 | 47.64 | -0.0108 | 229 | 337 | 1.24 |
| EXPOSICION_1_PERSISTENCIA | VALIDACION | 266 | 204 | 52.45 | 0.0434 | 46 | 86 | 1.19 |
| EXPOSICION_1_PERSISTENCIA | PRUEBA_RECIENTE | 274 | 189 | 43.39 | -0.0189 | 48 | 67 | 1.2 |
| EXPOSICION_1_ESPACIO_010 | ENTRENAMIENTO | 1014 | 715 | 46.99 | -0.0231 | 295 | 330 | 0.17 |
| EXPOSICION_1_ESPACIO_010 | VALIDACION | 378 | 278 | 55.76 | 0.0362 | 16 | 31 | 0.16 |
| EXPOSICION_1_ESPACIO_010 | PRUEBA_RECIENTE | 348 | 235 | 48.51 | 0.0191 | 29 | 33 | 0.14 |
| EXPOSICION_1_ESPACIO_020 | ENTRENAMIENTO | 966 | 685 | 47.59 | -0.0229 | 305 | 351 | 0.21 |
| EXPOSICION_1_ESPACIO_020 | VALIDACION | 364 | 269 | 56.13 | 0.0359 | 19 | 38 | 0.25 |
| EXPOSICION_1_ESPACIO_020 | PRUEBA_RECIENTE | 330 | 227 | 48.46 | 0.017 | 33 | 38 | 0.17 |
| EXPOSICION_1_PAR_HORA | ENTRENAMIENTO | 565 | 420 | 47.62 | -0.0127 | 443 | 489 | 0.23 |
| EXPOSICION_1_PAR_HORA | VALIDACION | 131 | 94 | 58.51 | 0.0297 | 118 | 123 | 0.11 |
| EXPOSICION_1_PAR_HORA | PRUEBA_RECIENTE | 156 | 100 | 48.0 | -0.0093 | 104 | 105 | 0.19 |
| EXPOSICION_1_PARES_HORA_DIARIO | ENTRENAMIENTO | 312 | 218 | 46.79 | -0.0048 | 547 | 592 | 0.12 |
| EXPOSICION_1_PARES_HORA_DIARIO | VALIDACION | 45 | 30 | 73.33 | 0.1554 | 152 | 154 | 0.11 |
| EXPOSICION_1_PARES_HORA_DIARIO | PRUEBA_RECIENTE | 94 | 55 | 45.45 | -0.0229 | 128 | 129 | 0.11 |
| EXPOSICION_1_PAR_LARGO_HORA | ENTRENAMIENTO | 756 | 530 | 47.36 | -0.0277 | 387 | 427 | 0.16 |
| EXPOSICION_1_PAR_LARGO_HORA | VALIDACION | 175 | 129 | 56.59 | 0.043 | 101 | 103 | 0.13 |
| EXPOSICION_1_PAR_LARGO_HORA | PRUEBA_RECIENTE | 219 | 139 | 49.64 | -0.0033 | 79 | 87 | 0.11 |
| EXPOSICION_1_CIERRE_HORA | ENTRENAMIENTO | 1110 | 789 | 47.4 | -0.0111 | 256 | 300 | 0.41 |
| EXPOSICION_1_CIERRE_HORA | VALIDACION | 254 | 186 | 53.23 | 0.0365 | 71 | 81 | 0.35 |
| EXPOSICION_1_CIERRE_HORA | PRUEBA_RECIENTE | 272 | 178 | 50.56 | 0.0006 | 59 | 69 | 0.21 |
| EXPOSICION_1_ESPACIO_010_PAR_HORA | ENTRENAMIENTO | 342 | 255 | 45.1 | -0.0318 | 533 | 570 | 0.23 |
| EXPOSICION_1_ESPACIO_010_PAR_HORA | VALIDACION | 128 | 91 | 58.24 | 0.0264 | 120 | 124 | 0.12 |
| EXPOSICION_1_ESPACIO_010_PAR_HORA | PRUEBA_RECIENTE | 139 | 90 | 46.67 | -0.0154 | 110 | 109 | 0.19 |

*Resultados originales de todos los casos suprimidos evaluables, pueden solaparse; son coste de filtrado descriptivo, no suma de operaciones independientes.

## Cobertura
- AAPL: 199 eventos. Excluidos antes de comparar: {}.
- AMD: 162 eventos. Excluidos antes de comparar: {}.
- AMZN: 198 eventos. Excluidos antes de comparar: {}.
- BABA: 129 eventos. Excluidos antes de comparar: {}.
- DIA: 135 eventos. Excluidos antes de comparar: {}.
- GLD: 139 eventos. Excluidos antes de comparar: {}.
- IWM: 168 eventos. Excluidos antes de comparar: {}.
- META: 195 eventos. Excluidos antes de comparar: {}.
- MSFT: 171 eventos. Excluidos antes de comparar: {}.
- MU: 176 eventos. Excluidos antes de comparar: {}.
- NFLX: 166 eventos. Excluidos antes de comparar: {}.
- NIO: 140 eventos. Excluidos antes de comparar: {}.
- NVDA: 188 eventos. Excluidos antes de comparar: {}.
- QQQ: 159 eventos. Excluidos antes de comparar: {}.
- SPY: 174 eventos. Excluidos antes de comparar: {}.
- TSLA: 222 eventos. Excluidos antes de comparar: {}.
Sin datos: AVGO

Desglose por compania, decisiones y exclusiones: report.json. Los criterios de separacion saludable, debilitamiento por rebotes y tolerancias no fueron inventados. Los contactos y observaciones de cierre se conservan en la app como contexto.
