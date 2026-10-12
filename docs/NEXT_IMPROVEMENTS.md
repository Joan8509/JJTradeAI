# Próximas mejoras: datos y evaluación de señales

Estado inicial: 6 de octubre de 2026. El scanner y el informe de investigación
están activos. El informe se actualiza cada cinco minutos mientras el equipo y
los procesos estén encendidos. No implica supervisión continua por parte del chat.

## Fase actual: detectar lo que falta

Se agregó una auditoría de requisitos NO_DISPONIBLE y REQUIERE_REVISION en todas
las evaluaciones, incluidas las que no detectaron una configuración. Cada requisito
se cuenta una vez por escaneo y detector, y se conserva el último detalle por
símbolo. Los NO_CUMPLE no se confunden con datos faltantes.

Prioridades verificadas en el motor:

| Prioridad | Problema | Trabajo necesario | Información pendiente |
|---|---|---|---|
| 1 | Efecto Imán exige cruce de Worden | Identificar una fuente verificable o revisión registrada con hora y símbolo | Fuente y definición exacta de la línea roja; Alpaca no entrega esa línea |
| 2 | Momentum exige camino libre | Precisar niveles y revisar si se pueden evaluar con datos disponibles | Qué niveles cuentan y cómo invalidan el recorrido |
| 3 | Primer Salto y Salto de Lateralidad exigen ausencia de noticias invalidantes | Definir calendario/fuente, eventos cubiertos y ventana temporal | Eventos y ventanas aprobados; la ausencia de una noticia recibida no prueba ausencia de eventos |

Las ambigüedades metodológicas están documentadas en
`docs/METHODOLOGY_VALIDATION_MATRIX.md`. No se sustituyen requisitos por indicadores
parecidos ni se aprueba una estrategia a partir de un movimiento posterior favorable.

## Próximo paso de implementación: entradas y salidas reproducibles

Preparar una evaluación que registre el momento en que la señal estuvo disponible
y el primer precio posterior utilizable, sin asumir ejecución al precio de una
vela ya cerrada. Conservar tanto ese estudio como los resultados actuales.

Antes de evaluar stop y objetivo hay que definirlos por estrategia según la
metodología. No introducir distancias arbitrarias. Cuando se habilite evaluación
de opciones, registrar contrato, vencimiento, bid/ask y costos definidos.

Criterios para revisar el siguiente avance:

- Entrada posterior a la disponibilidad de la señal, sin usar información futura.
- Salidas y resultados trazables a las barras o cotizaciones originales.
- Datos insuficientes identificados, sin inventar ejecuciones.
- Candidatas y confirmadas separadas; metodología y feed conservados.
- Cambios contrastados con sesiones posteriores, también cuando pierden.

## Momento de decidir sobre los filtros

Las tres hipótesis actuales quedaron registradas el 6 de octubre. La prueba futura
excluye la sesión del registro. El informe mostrará muestras nuevas conforme
maduren sus horizontes. Diez observaciones de tres sesiones es solo el mínimo
descriptivo del informe, no aprobación para cambiar señales.

Si el retorno sigue negativo, empeora el recorrido adverso o el resultado depende
de pocos símbolos/sesiones, no se considera una mejora lista para implementar.
No hay una fecha garantizada para aprobar cambios: depende de la evidencia.
