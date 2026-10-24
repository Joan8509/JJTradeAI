# Apertura mínima del1% en ambas bandas

El22/10 el usuario eligió explícitamente **1%**. Sustituye la preparación
pendiente1%/2% y la regla anterior de cualquier apertura positiva. El estado
de carga comprobado en procesos se consulta en CURRENT_CONTEXT y diario.

    ancho_anterior = superior_anterior − inferior_anterior
    superior_pct = 100 × (superior − superior_anterior) / ancho_anterior
    inferior_pct = 100 × (inferior_anterior − inferior) / ancho_anterior

Cada porcentaje debe alcanzar1%, inclusive, y ser positivo. No equivale al1%
del precio ni del incremento total del ancho. Una banda plana o cerrándose
no pasa por mayor aumento de la otra. Se rechazan no finitos/bandas invertidas
y ancho previo cero. No es BandWidth estándar.

bollinger_expansion.py define la medida y constante única. detect_values usa
ese mínimo; tanto detect_exit como el stream llaman la misma regla. Sigue
siendo intravela, sin esperar cierre: si alcanza1% más tarde, puede dar señal
en ese momento solo si las otras reglas cumplen. No reenvía avisos ya enviados.

Las señales nuevas guardan band_expansion con bandas previas/actuales,
porcentajes y mínimo requerido. El evento persistente hereda esa evidencia
sin depender de la retención corta de ticks. No se reescriben eventos viejos.
El recibo de arranque del colector incluye mínimo y hashes de tres módulos.
La versión basev4 y claves dedup permanecen para evitar avisos duplicados por
cambiar filtro. No se alteran apertura dentro, dirección/media, REGULAR/IEX,
3s/30s, contratos/rangos/spread0.08/OTM5,stop10 ni formatoTelegram. RealesOFF.

El1% es una decisión autorizada de filtrado; no hay todavía mejora predictiva
o rentabilidad demostrada. Validación de ambas direcciones/límites inclusivos,
banda débil/plana/cerrándose, apertura exterior/media/dirección, escala,
traslación/no finitos, fast path débil→más abierto y evidencia/recibo.
84pruebas expansión+phone+stream+cola+home pasaron. Tras añadir metadatos al
recibo se repitieron22stream, todasOK. Comparación11avisos:11con0%,9con1%,
7con2%; no es replay completo ni rendimiento. Medir días nuevos y retrasos.
