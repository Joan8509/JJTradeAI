# TSLA: esperar exposición mínima antes de avisar

Datos congelados a 2026-10-12T17:41:55.935094+00:00; base de 90 casos evaluables del estudio anterior. Umbral exploratorio fijo: 1% del ancho de bandas.
Si ya cumple, avisa inmediatamente. Si no, espera dentro de la misma vela de 15m. Cancela al primer cierre de minuto que regresa dentro. Exige mantener la regla de expansión y dirección al avisar. No vuelve a activar ese evento tras la cancelación.
El resultado filtrado se calcula desde el nuevo precio y momento del aviso, nunca desde el aviso original. Estos datos ya fueron explorados: la separación temporal no es una prueba independiente ni permite afirmar rentabilidad futura.

| Periodo | Avisos originales | Retenidos | Cancelados dentro | No fortalecidos | Demorados | Demora media* | Positivos original | Positivos filtrado** |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| ANTERIOR_60_DIAS | 64 | 55 | 7 | 2 | 5 | 1.2m | 29/64 | 25/55 |
| RECIENTE_30_DIAS | 26 | 23 | 3 | 0 | 2 | 1.0m | 13/26 | 13/23 |

*Media entre avisos demorados. **A 15m desde cada aviso; los distintos momentos cambian el recorrido evaluado.

Se incluyen solo los 90 casos completos y sin solapamiento de la base original. La espera puede crear solapamiento entre avisos retenidos: los porcentajes son descriptivos, no operaciones independientes. No incluye contratos de opciones, costos, ejecución ni noticias. No se modificaron las alertas reales.

## Coste de suprimir avisos
- ANTERIOR_60_DIAS: se suprimieron 5 casos que terminaron negativos y 4 que terminaron positivos en la evaluación original. Exclusiones después de esperar: {}.
- RECIENTE_30_DIAS: se suprimieron 3 casos que terminaron negativos y 0 que terminaron positivos en la evaluación original. Exclusiones después de esperar: {}.

Caso TSLA de hoy, aviso 10:34: REGRESO_DENTRO.
