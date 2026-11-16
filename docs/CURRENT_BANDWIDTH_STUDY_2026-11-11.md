# Ancho total actual de Bollinger - 11/11/2026

Usuario pide analizar la SEPARACION entre bandas, proponiendo que mayor distancia
es mejor. Este estudio mide nivel actual, separandolo del3% de expansion por borde
y del ancho anterior que aparecia en la investigacion previa de factores comunes.

BandWidth=100*(superior-inferior)/media central, conforme a Fidelity:
https://www.fidelity.com/learning-center/trading-investing/technical-analysis/technical-indicator-guide/bollinger-band-width
Tambien conserva USD, porcentaje del precio original y relacion con mediana de
20anchos previos cerrados (minimo10). El3% por borde no exige ancho3% del precio:
ambos bordes al3% aumentan al menos6% el ancho enUSD, aun pudiendo quedar estrecho.

1096eventos historicos/19companias/62sesiones: grupo mas ancho tiene avance maximo
medio primer minuto0.1040% yretroceso0.0988%; grupo mas estrecho0.0398% y0.0384%.
Son movimientosdel subyacente: amplitud favorable2.61x, adversa2.57x. Al comparar
cuartiles propios de cada compania no hay mejora monotona: avanceQ1 0.0749%,
Q2 0.0885%,Q3 0.0855%,Q4 0.0701%. Resultado conjunto no prueba efecto causal.
No escoger un ancho universal por mezclar companias con volatilidades distintas.

Cuartiles se ajustan en22sesionesde desarrollo y se conservan en20de contraste y
20posteriores. Historial previamente examinado, no prueba nueva prospectiva.
Ancho actual calculado con precio conocido en la senal, sin cierre futuro. Baseline
previo exige cierres completos sin saltar huecos;45historicos sinbaseline.14sin
suficiente muestra de entrenamiento para cuartiles de su propia compania.

73senalesV7 de9/10/11Nov separadas deproxyminutal.21evaluablesa30s,16sinbaseline
recientereconstruibleporrecepcionoriginal,13sincuartilespropios. No hay evidencia
para aprobar un nuevo umbral operativo, ni para traducir ancho a gananciaopciones.

Desarrollados bollinger_bandwidth_research.py, scripts/study_current_bandwidth.py
ytests/test_bollinger_bandwidth_research.py.18pruebasOK0.042s,6nuevas;19fuentes
historicas verificadas y16SHA256 de entrega. Reporte privado reproducible:
exports/trade_review/2026-11-11_current_bandwidth/REPORT.md (plan,rows,CSV,fuentes,
validacion ychecksums). SQLRO/query_only solo para congelar referenciahistoria.

No nuevo filtro ni minimo/maximo de ancho, cambio3%, precioobjetivo/stop, servicio,
cola, armado, brokerAPI, Telegram, ordenes, commit o push. La futura evaluacion de
ancho debe usar escala de cada compania y estar precalculada para no demorar entrada.
