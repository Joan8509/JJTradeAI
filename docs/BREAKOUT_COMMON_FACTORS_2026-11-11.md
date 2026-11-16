# Playback de factores comunes - 11/11/2026

Peticion: encontrar condiciones conocidas antes de la entrada que distingan
impulso favorable de reversion, preservando rapidez. Se desarrollo comparador,
modelo interpretable y replay contrafactual; no se activo ningun filtro.

Fuentes privadas congeladas: 1096 eventos historicos de19companias/62sesiones,
muestreo de apertura de minuto con predicado3% y apertura inicial dentro;
73 senales reales del detectorV7 de09/10/11Nov, separadas de versiones antiguas.
Minutos no permiten reproducir cronometro30s. Resultados del subyacente, no P&L
de contratos. Historial ya estudiado, controles retrospectivos, no prueba nueva
prospectiva. Desarrollo22sesiones/contraste20/posteriores20; los parametros del
modelo se eligen en desarrollo, no con datos posteriores.

Resultado operativo claro:72/73 senales primeras tenian banda contraria<5%.
Esperar5% con todas las reglas y mismo plazo30s encontro12entradas aptas observadas,
11demoradas,mediana8.14s ydesplazamiento favorable medio0.0917%subyacente. No
se observo oportunidad5% en61; no implica conocer prints no archivados. No subir
umbral ni esperarconfirmacion5% por este estudio.

Volumen relativo cerrado>=1.5x: asociacion bruta55.1% de cierres1min favorables
sobre410casos conocidos, vs45.9% sobre303 con volumen<1x. Contraste por dia y
compania no concluyente; datos actualesV7 no confirman ventaja. Volumen previo
cerrado no mide el volumen del impulso actual. Bandas5%+volumen1.5x amplian
avanceyretroceso; criterio pierde estabilidad: toque favorable claro cae de
68.8%desarrollo/73.7%contraste a46.7%posteriores, base posterior53.4%.

Se desarrollo arbolprofundidad2/minimo50porhoja,caracteristicascausales y umbrales
deciles entrenamientosolamente. Modelo cierre1min empeora en tramo posterior
46.6%vs49.2%base. Arbolalternativo primer toque se abstiene. Preservarlos como
investigacion, sin enlace con ejecutor/detector. La hipotesis aparentemente buena
no se transforma en bloqueo operativo. Tasas no equivalen a ganancias de opciones.

Nueva medicion investigacion de velocidad de banda contraria en primera senal:
utiliza ultimo tick anterior<=3s con misma referencia, no espera futuros;38/73
casos calculables. Tiempo desde primera salida conocido73,60instantaneos;
recortar plazo1s tampoco acredita mejora. Etiquetas30s estrictas21/73cubiertas,
10s30/73,60s25/73. No sustituir faltantes por perdidas. No hay operaciones
simuladas de esta cohorte en ledger consultado (historial termina30Oct).

Archivos: breakout_quality_research.py; scripts/study_breakout_common_factors.py,
study_breakout_interactions.py,study_initial_impulse.py,study_waiting_for_five.py,
render_breakout_common_report.py; tests/test_breakout_quality_research.py.
28pruebasOK5.751s,12nuevas; reproduccion40comparaciones y140tasas. Planes, fuentes,
reportes ychecksum en exports/trade_review/2026-11-11_common_factors/REPORT.md.
Protegida nueva SQLite privada movement_strength.sqlite3 yauxiliares mediante
.gitignore; ninguna publicacion, reinicio, activacion, orden o aviso por estudio.
