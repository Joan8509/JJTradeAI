# Playback de filtros con medias y niveles — 12 de octubre de 2026

Ventana de 180 días naturales, con historial anterior para calentar SMA y
Bollinger. Corte 2026-10-12T23:39:55.806979Z. Se reconstruyeron 2721 eventos
en 16 símbolos; AVGO sigue sin datos. Detector v3 sin cambios.

## Método

Once variantes fijadas antes de ejecutar: base; exposición 1%/3% del ancho;
exposición 1% durante dos minutos consecutivos; exposición más espacio de
0,10%/0,20% del precio; exposición más tendencias validadas 20/40 Hora,
20/40 Hora y Diario, 100/200 Hora; exposición más cierre de Hora a favor;
exposición más espacio y tendencia de Hora.

Medias y último cierre de Hora usan solo información cerrada al aviso.
Referencias de precio: cierre de sesión anterior, verificado por calendario y
última barra; máximo del historial anterior disponible, no ATH real verificado.
Los papeles SMA de continuidad no se clasifican automáticamente como barreras.
Roles desconocidos por delante se mantienen como posibles obstáculos. Los filtros
de espacio no aceptan como suficiente un contexto sin historial o cierre verificado.
No se inventaron tolerancias ni reglas de debilitamiento de contactos.

Espera dentro de la misma vela; cancela al primer regreso dentro. Cada aviso
retenido usa su nuevo momento/precio, no el antiguo, para resultados a 5/15m.
Ventanas incompletas se excluyen; se desolapa por compañía/fuente cada variante,
incluso entre direcciones. Distintos subconjuntos limitan la comparación causal.
Se mide también regreso dentro en alguno de los dos minutos posteriores.

120 días de entrenamiento, 30 de validación, 30 de prueba reciente. Los datos
recientes ya habían sido explorados; no es validación prospectiva independiente.
Criterios de revisión establecidos sin usar el resultado reciente: al menos
100/40 casos en entrenamiento/validación, retener >=50% de avisos, mejorar
>=3 puntos de continuidad a 15m y no empeorar retorno medio en ambos periodos.
Son criterios de investigación, no reglas del mentor ni garantía de precisión.

## Resultado

Ninguna variante cumple todos los criterios. No se activó filtro universal.
Últimos 30 días:

| Variante | Casos sin solapar | A favor 15m | Regresó dentro en 2m |
|---|---:|---:|---:|
| Base | 293 | 49,15% | 38,91% |
| Exposición 1% | 266 | 49,62% | 34,96% |
| Exposición 1% durante dos minutos | 189 | 43,39% | 24,34% |
| Exposición 1% + espacio 0,10% | 235 | 48,51% | 34,04% |

Esperar dos minutos reduce reentradas tempranas en la muestra pero retrasa
avisos, pierde movimientos y no mejora continuidad posterior. Exposición 1%
muestra mejoras pequeñas/inestables: no justifica supresión obligatoria.
Los retornos son del subyacente, sin opciones, costos o ejecución.

## Mejora aplicada

Avisos y tarjetas muestran exposición porcentual del ancho y señalan exposición
pequeña (<1%) como información, sin llamar fuerte o aprobada a las demás.
El radar sigue enviando avisos tempranos; no suprime señales por estos candidatos.
Seguimiento de resultados contiene comparación de filtros por periodo y compañía.
Los grupos son descriptivos; las muestras pequeñas se señalan.

Resultados en `exports/bollinger_playback/filters_20261012_233955/`:
`revision.md`, `analisis.md`, `summary.json`, `resumen.csv`, `report.json.gz`.
La copia comprimida contiene 29931 comparaciones y fue verificada al descomprimir.
El JSON bruto queda local y excluido de Git; datos completos comprimidos en Git.

Reproducción: `scripts/research_bollinger_filters.py` seguido de
`scripts/review_bollinger_filters.py`. No cambian alertas automáticamente.
Próximo paso: contrastar en sesiones nuevas y por dirección/compañía, sin
optimizar umbrales con unos pocos ejemplos favorables.


## Ajuste solicitado: playback silencioso
Se elimina la nueva comparacion de filtros del dashboard y la nueva linea de exposicion de Telegram y tarjetas. Las mediciones siguen internas. El radar ahora registra historical_support junto al evento, sin cambiar ni retrasar las notificaciones. Una memoria compacta de 2026 resultados completos compara misma compania, direccion, proveedor/feed, fase de sesion y rango de exposicion; excluye resultados todavia no conocidos y ventanas solapadas. Requiere 20 casos y cinco fechas para mostrar internamente una frecuencia descriptiva. No estima una probabilidad calibrada, no aprende ajustes automaticamente y no considera ciclos una garantia. Esta primera memoria NO empareja SMA/barreras: el estudio de esos factores sigue separado y no valido un filtro universal. Actualizar memoria requiere ejecutar scripts/build_bollinger_pattern_memory.py despues de un playback nuevo; no es una actualizacion continua automatica.
