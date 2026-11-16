# Ancho y apertura en el aviso de estrategia

Desde el 12/11, el mismo aviso describe las bandas con palabras sencillas. Se
retiran del texto los porcentajes de ancho y variación incorporados el 11/11,
porque el usuario los encontraba confusos. Esos valores continúan disponibles
en el contexto numérico guardado del evento. La segunda línea conserva lado,
precio y banda tocada. Se conservan las cuatro líneas y el rango del contrato.

Ejemplo ilustrativo: `Bandas: se están separando cada vez más rápido`.
Ese ejemplo explica el formato, no representa una señal autorizada.

El ancho actual es `100 × (superior − inferior) / media`. La regla operativa del
3% por cada borde utiliza como denominador el ancho de la vela anterior: son
mediciones diferentes. Una expansión mínima de ambos bordes implica al menos
6% de aumento del ancho en USD, sin exigir un ancho equivalente al 3% del precio.

El radar reutiliza las geometrías ya recibidas para describir el ritmo. Necesita
dos observaciones distintas para velocidad y tres para aceleración. No espera
estas observaciones para enviar el aviso. Con datos insuficientes muestra
«todavía no se puede medir si se abren más rápido o más lento». Solo utiliza intervalos entre 0,25 y 3 segundos,
separados por fuente, compañía, vela y referencias. Una banda que retrocede
no se presenta como apertura de ambas. Lecturas repetidas o anteriores no
generan una aceleración artificial; los huecos reinician la comparación.

Es una descripción del movimiento observado, no un nuevo requisito de compra
ni una clasificación de probabilidad de ganancia. El estudio de ancho actual
no justificó activar un mínimo universal adicional; ver
[estudio del ancho](CURRENT_BANDWIDTH_STUDY_2026-11-11.md).

Implementación: `bollinger_notice_bandwidth.py` y `bollinger_phone_worker.py`.
Sin nuevas consultas, red, espera, esquema SQL o mensajes adicionales. Contexto
acotado a 128 referencias; se adjunta al evento existente para su revisión.
No cambia estrategia, deduplicación, caducidad, compra, objetivo o stop.
Pruebas: `tests/test_bollinger_notice_bandwidth.py`, además de regresiones del
radar, reloj y ejecución. Evidencia y despliegue en el registro diario.
