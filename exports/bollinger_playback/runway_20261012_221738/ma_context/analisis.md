# Contexto de medias y salidas Bollinger

SMA provisional; no se supone que la clase especifica SMA. Pares 20/40 y 100/200 en Hora y Diario, usando solo velas cerradas al detectarse la salida. No se verificó duración mínima de tendencia de dos días; alineación aquí significa únicamente orden de las medias.
Misma base de 1181 eventos completos del estudio de recorrido. Relación descriptiva agregada, mezclando compañías, direcciones y regímenes; no es causal ni demuestra mejora de certeza. Distancias de 0,10 y 0,50% son grupos exploratorios, no filtros activos. Sin medias por delante no significa camino libre; datos parciales pueden omitir niveles.

| Factor | Grupo | Casos | Avance medio antes del primer retroceso % | Sin avance % |
|---|---|---:|---:|---:|
| 1H 20/40 | ALINEADO | 613 | 0.0711 | 48.6 |
| 1H 20/40 | CONTRARIO | 568 | 0.0833 | 49.8 |
| 1H 100/200 | ALINEADO | 616 | 0.0756 | 49.2 |
| 1H 100/200 | CONTRARIO | 565 | 0.0784 | 49.2 |
| 1D 20/40 | ALINEADO | 579 | 0.0719 | 49.4 |
| 1D 20/40 | CONTRARIO | 602 | 0.0819 | 49.0 |
| 1D 100/200 | ALINEADO | 562 | 0.0782 | 51.6 |
| 1D 100/200 | CONTRARIO | 619 | 0.0758 | 47.0 |
| DISTANCIA_A_MEDIA_POR_DELANTE | 0.10–0.50% | 277 | 0.0667 | 48.0 |
| DISTANCIA_A_MEDIA_POR_DELANTE | <0.10% | 101 | 0.0449 | 52.5 |
| DISTANCIA_A_MEDIA_POR_DELANTE | >=0.50% | 523 | 0.0896 | 48.4 |
| DISTANCIA_A_MEDIA_POR_DELANTE | SIN_MEDIA_POR_DELANTE_DISPONIBLE | 280 | 0.0751 | 50.7 |

No se cambiaron condiciones de detección, umbrales de aprobación ni supresión de Telegram. La integración actual añade contexto a cada aviso para estudio y revisión humana.
