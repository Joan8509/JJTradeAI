# Comparacion de filtros Bollinger con medias y niveles

Corte UTC: 2026-10-13T00:25:55.000647+00:00. Ventana 180 dias; 120 entrenamiento, 30 validacion, 30 prueba reciente.
Los candidatos se fijaron antes de ejecutar. La prueba reciente ya fue explorada en conversaciones anteriores: no es validacion prospectiva independiente. No se usa cierre futuro para medias ni confirmaciones. No se considera ATH real: maximo del historial disponible previo.
Espera dentro de la misma vela; cancela al regresar dentro. Se recalculan precio y momento de cada aviso retenido. Evaluacion a 5 y 15m desde ese nuevo momento. Ventanas incompletas se excluyen y cada candidato se desolapa por simbolo/fuente, incluso entre direcciones. Diferentes muestras pueden sesgar comparaciones.
Espacio toma posibles pisos/techos, roles SMA desconocidos por delante, cierre anterior y maximo disponible. Datos insuficientes o cierre no verificado impiden dar por suficiente el espacio. Continuidad favorable de una SMA no se trata automaticamente como barrera.
No hay beneficios de opciones, costos ni ejecuciones. Las companias pueden moverse correlacionadas. No se elige un ganador por porcentaje reciente ni se cambian alertas automaticamente.

| Candidato | Periodo | Avisos | Casos sin solapar | Positivo 15m % | Retorno medio 15m % | Positivos suprimidos* | Negativos suprimidos* | Demora media m |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| BASE | ENTRENAMIENTO | 4111 | 2356 | 49.58 | 0.0078 | 0 | 0 | 0.0 |
| BASE | VALIDACION | 966 | 517 | 49.13 | 0.0043 | 0 | 0 | 0.0 |
| BASE | PRUEBA_RECIENTE | 1043 | 545 | 48.44 | 0.0226 | 0 | 0 | 0.0 |
| EXPOSICION_1 | ENTRENAMIENTO | 3562 | 2056 | 50.0 | 0.0037 | 136 | 187 | 0.13 |
| EXPOSICION_1 | VALIDACION | 846 | 463 | 52.05 | 0.0114 | 17 | 39 | 0.09 |
| EXPOSICION_1 | PRUEBA_RECIENTE | 903 | 487 | 49.08 | 0.0268 | 25 | 41 | 0.11 |
| EXPOSICION_3 | ENTRENAMIENTO | 2815 | 1646 | 48.91 | 0.0047 | 333 | 417 | 0.4 |
| EXPOSICION_3 | VALIDACION | 687 | 378 | 53.7 | 0.009 | 47 | 96 | 0.41 |
| EXPOSICION_3 | PRUEBA_RECIENTE | 724 | 401 | 48.38 | 0.025 | 62 | 98 | 0.35 |
| EXPOSICION_1_PERSISTENCIA | ENTRENAMIENTO | 2307 | 1413 | 49.68 | 0.0086 | 407 | 578 | 1.24 |
| EXPOSICION_1_PERSISTENCIA | VALIDACION | 555 | 313 | 50.48 | 0.0216 | 80 | 140 | 1.2 |
| EXPOSICION_1_PERSISTENCIA | PRUEBA_RECIENTE | 594 | 351 | 46.44 | 0.0138 | 82 | 130 | 1.21 |
| EXPOSICION_1_ESPACIO_010 | ENTRENAMIENTO | 1231 | 801 | 47.82 | -0.0292 | 814 | 796 | 0.16 |
| EXPOSICION_1_ESPACIO_010 | VALIDACION | 819 | 450 | 52.22 | 0.0091 | 24 | 45 | 0.16 |
| EXPOSICION_1_ESPACIO_010 | PRUEBA_RECIENTE | 832 | 453 | 49.01 | 0.0332 | 43 | 59 | 0.14 |
| EXPOSICION_1_ESPACIO_020 | ENTRENAMIENTO | 1177 | 770 | 48.31 | -0.0295 | 825 | 818 | 0.19 |
| EXPOSICION_1_ESPACIO_020 | VALIDACION | 788 | 438 | 52.05 | 0.0057 | 29 | 54 | 0.22 |
| EXPOSICION_1_ESPACIO_020 | PRUEBA_RECIENTE | 793 | 440 | 48.64 | 0.0307 | 50 | 67 | 0.16 |
| EXPOSICION_1_PAR_HORA | ENTRENAMIENTO | 1253 | 743 | 49.39 | -0.0025 | 835 | 845 | 0.19 |
| EXPOSICION_1_PAR_HORA | VALIDACION | 284 | 150 | 54.0 | 0.011 | 181 | 204 | 0.11 |
| EXPOSICION_1_PAR_HORA | PRUEBA_RECIENTE | 348 | 182 | 52.2 | 0.0585 | 181 | 208 | 0.15 |
| EXPOSICION_1_PARES_HORA_DIARIO | ENTRENAMIENTO | 615 | 356 | 48.6 | 0.0162 | 1037 | 1035 | 0.16 |
| EXPOSICION_1_PARES_HORA_DIARIO | VALIDACION | 127 | 61 | 63.93 | 0.0789 | 224 | 252 | 0.13 |
| EXPOSICION_1_PARES_HORA_DIARIO | PRUEBA_RECIENTE | 200 | 96 | 48.96 | 0.0271 | 232 | 249 | 0.1 |
| EXPOSICION_1_PAR_LARGO_HORA | ENTRENAMIENTO | 1643 | 922 | 50.33 | 0.0076 | 727 | 762 | 0.14 |
| EXPOSICION_1_PAR_LARGO_HORA | VALIDACION | 400 | 207 | 54.59 | 0.0251 | 154 | 171 | 0.12 |
| EXPOSICION_1_PAR_LARGO_HORA | PRUEBA_RECIENTE | 438 | 234 | 48.72 | 0.006 | 159 | 176 | 0.11 |
| EXPOSICION_1_CIERRE_HORA | ENTRENAMIENTO | 2432 | 1416 | 48.94 | -0.0083 | 477 | 517 | 0.39 |
| EXPOSICION_1_CIERRE_HORA | VALIDACION | 570 | 303 | 49.83 | -0.0014 | 110 | 125 | 0.26 |
| EXPOSICION_1_CIERRE_HORA | PRUEBA_RECIENTE | 609 | 319 | 47.65 | 0.0124 | 116 | 131 | 0.25 |
| EXPOSICION_1_ESPACIO_010_PAR_HORA | ENTRENAMIENTO | 406 | 286 | 45.8 | -0.0364 | 1085 | 1064 | 0.2 |
| EXPOSICION_1_ESPACIO_010_PAR_HORA | VALIDACION | 279 | 146 | 54.11 | 0.0088 | 184 | 205 | 0.12 |
| EXPOSICION_1_ESPACIO_010_PAR_HORA | PRUEBA_RECIENTE | 328 | 172 | 51.74 | 0.0588 | 187 | 212 | 0.15 |

*Resultados originales de todos los casos suprimidos evaluables, pueden solaparse; son coste de filtrado descriptivo, no suma de operaciones independientes.

## Cobertura
- AAL: 170 eventos. Excluidos antes de comparar: {}.
- AAPL: 199 eventos. Excluidos antes de comparar: {}.
- AMD: 162 eventos. Excluidos antes de comparar: {}.
- AMZN: 198 eventos. Excluidos antes de comparar: {}.
- AVGO: 173 eventos. Excluidos antes de comparar: {}.
- AXP: 166 eventos. Excluidos antes de comparar: {}.
- BA: 159 eventos. Excluidos antes de comparar: {}.
- BABA: 129 eventos. Excluidos antes de comparar: {}.
- C: 166 eventos. Excluidos antes de comparar: {}.
- CCL: 175 eventos. Excluidos antes de comparar: {}.
- COIN: 151 eventos. Excluidos antes de comparar: {}.
- CVS: 194 eventos. Excluidos antes de comparar: {}.
- DAL: 147 eventos. Excluidos antes de comparar: {}.
- DASH: 190 eventos. Excluidos antes de comparar: {}.
- DIA: 135 eventos. Excluidos antes de comparar: {}.
- GLD: 139 eventos. Excluidos antes de comparar: {}.
- GOOG: 181 eventos. Excluidos antes de comparar: {}.
- HD: 143 eventos. Excluidos antes de comparar: {}.
- HOOD: 179 eventos. Excluidos antes de comparar: {}.
- IBM: 155 eventos. Excluidos antes de comparar: {}.
- INTC: 191 eventos. Excluidos antes de comparar: {}.
- IWM: 168 eventos. Excluidos antes de comparar: {}.
- LI: 122 eventos. Excluidos antes de comparar: {}.
- LOW: 146 eventos. Excluidos antes de comparar: {}.
- LYFT: 193 eventos. Excluidos antes de comparar: {}.
- MA: 211 eventos. Excluidos antes de comparar: {}.
- META: 195 eventos. Excluidos antes de comparar: {}.
- MRNA: 187 eventos. Excluidos antes de comparar: {}.
- MSFT: 171 eventos. Excluidos antes de comparar: {}.
- MU: 176 eventos. Excluidos antes de comparar: {}.
- NFLX: 166 eventos. Excluidos antes de comparar: {}.
- NIO: 140 eventos. Excluidos antes de comparar: {}.
- NVDA: 188 eventos. Excluidos antes de comparar: {}.
- QQQ: 159 eventos. Excluidos antes de comparar: {}.
- SPY: 174 eventos. Excluidos antes de comparar: {}.
- TSLA: 222 eventos. Excluidos antes de comparar: {}.

Desglose por compania, decisiones y exclusiones: report.json. Los criterios de separacion saludable, debilitamiento por rebotes y tolerancias no fueron inventados. Los contactos y observaciones de cierre se conservan en la app como contexto.
