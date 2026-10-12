# Estudio exclusivo de salida Bollinger con volatilidad

Se mantiene desconectado de Schwab y no modifica aprobaciones PAPER.

La definición actual `v2_sin_apertura_expuesta` se comparte con `bollinger_phone_worker.detect_values`:
la vela anterior cerró dentro de sus bandas, la apertura de la vela actual está
dentro de las bandas anteriores (conocidas antes de abrir), el precio conocido ahora sale
por la superior/inferior, ambas bandas se expanden respecto de la vela anterior
y el punto medio acompaña. No exige esperar el cierre de la vela 15m. Un toque
o un precio previamente expuesto no bastan. No hay un umbral de fuerza calibrado.

La reconstrucción calcula las bandas parciales con 19 cierres completos anteriores
y el último cierre de un minuto conocido; usa 20 períodos, 2 desviaciones y ddof=0,
como el radar. Deduplica por compañía, fuente, vela y dirección. No utiliza el
cierre futuro de la vela en formación. Guarda la primera detección por vela/lado.
El estudio no reproduce necesariamente las demoras, correcciones del proveedor
ni huecos que existían en el momento real. Las detecciones en vivo tienen una
tabla independiente con la hora real de observación, desde este cambio.

Resultados: a 5, 15, 30 y 60 minutos, compara el precio final del subyacente con
el precio observado al detectar la salida. Superior positivo = terminó arriba;
inferior positivo = terminó abajo. Cero se conserva separado. También mide el
máximo recorrido favorable y adverso. Para observaciones en vivo usa ventanas
posteriores a la disponibilidad efectiva, sin asignarles movimientos ya ocurridos.
Son movimientos descriptivos, no operaciones ejecutadas ni rendimiento de opciones.

Exige todas las barras de la ventana y OHLC válidos; no rellena minutos ausentes.
Excluye recorridos que pasan el cierre de sesión del calendario persistido,
incluidos cierres anticipados. Pendientes y datos faltantes no se cuentan como
aciertos ni errores. Debe revisarse el posible sesgo de excluir recorridos incompletos.

Los resultados se separan por compañía, feed, dirección, horizonte y origen.
La tasa usa ventanas sin solapamiento dentro de cada grupo. Direcciones distintas
y compañías distintas pueden seguir correlacionadas; no tratar la suma como ensayos
independientes. Menos de 20 casos o 5 sesiones se marca muestra insuficiente;
superar ese mínimo sigue siendo evidencia descriptiva y no valida precisión futura.
No se ajustan reglas ni seleccionan compañías automáticamente por estos resultados.

La revisión v2 excluye aperturas que saltan directamente fuera de la banda.
No establece un porcentaje arbitrario de gap ni rechaza cualquier diferencia
entre apertura y cierre previo; saltos que abren todavía dentro de las bandas
requieren una definición adicional si el usuario también desea excluirlos.
El estudio se reconstruye con v2 y conserva los eventos v1 en la base, excluidos
de las tasas actuales. El dashboard tampoco muestra estados v1 como activos.

Servicio: `python bollinger_strategy_study.py --watch`, informe actualizado cada
cinco minutos. Datos e informe en `exports/bollinger_study/`, excluido de Git.
Requiere el equipo y procesos activos; no funciona con el PC apagado.

En la app aparece primero en «Seguimiento de resultados». Antes de afirmar que
capta exactamente la estrategia visual del usuario, contrastar ejemplos de avisos
con su gráfico, misma fuente y configuración de bandas. Una reconstrucción favorable
no sustituye esa revisión ni un período nuevo de observación prospectiva.
