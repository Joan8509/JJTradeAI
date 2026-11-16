# Fuerza de apertura: actualizacion al 3%

Playback offline completado el 9 de noviembre. Fuentes congeladas IEX/RTH:
19 companias, 62 sesiones del 5 de agosto al 30 de octubre, 288781 muestras
de apertura de minuto. Predicado actual de expansion 3% por banda y apertura
inicial dentro. La resolucion minutal NO reproduce el reloj intraminuto30sV7;
se etiqueta proxy, separado del analisis por segundos. No aplicar filtros nuevos.

Primer minuto despues de cada senal reconstruida:

| Vela ET | Casos | Avance maximo medio | Retroceso maximo medio |
|---|---:|---:|---:|
|09:30-09:45|157|0.160%|0.183%|
|09:45-10:00|93|0.124%|0.073%|
|10:00-10:15|95|0.076%|0.085%|

Porcentajes del subyacente, no ganancias del contrato. OHLC no determina el
orden intraminuto de avance/retroceso. A5min primera156casos, avance0.349%,
retroceso0.390%, finala favor46.8%; segunda93casos0.313%/0.175%/58.1%;
tercera95casos0.189%/0.227%/46.3%. Mayor fuerza no equivale a continuidad.

Bootstrap pareado por dia, igual peso compania/dia,51fechas comunes: primera
menossegunda+tercera en MFE5min +0.102pp IC95%[+0.023,+0.184], MAE+0.209pp
[+0.136,+0.278]; diferenciafrecuenciafinalafavor-5.05pp[-16.63,+7.52].
Historial ya examinado; contraste descriptivo, no validacion independiente.
Ultimas20sesiones preservadas en informe: no elegir horario por pequenas
muestras recientes. 30628velas potenciales,19366estrictas,11047sin20cierres
completos y215sinapertura oficial, faltantes nunca cero.

Archivo ticks06Nov: geometria causal guardada, predicadoactual, reloj30s desde
primera salida observada porlado, solo velas con primer tick temprano<=3s y
preciofresco. Resultan2senalesC1,1C2,0C3,5resto. Un dia y cobertura escasa:
solo1C1 evaluablea10s; ninguna trayectoria30s continua<=1s. No presentar
porcentajes porsegundos como tasas fiables ni inferir barreras de opciones.
Ausencia de gaps de retencion no prueba cobertura total de todoslosmercados.

Aplicacion propuesta: preparacion antes09:30, reaccion inmediata a estrategia
completa, conservar oportunidadessegunda/tercera ystop20%. No comprar solo
porhorario, esperar cierre15m, ampliar stop ni cambiar objetivo por este estudio.
No se cambio ninguna regla, cola, proceso oconfiguracion; sinAPI, avisos uordenes.
IPCpreparado06Nov sigue pendiente de despliegue, no confundir estudio con carga.

18pruebasOK1.501s (nuevo estudio, origen, reloj yobservador);8checksums verificados.
Evidencia privada: exports/trade_review/2026-11-09_opening_strength/REPORT.md,
report.json, minute_events.json, tick_events.json, summary.csv, validation.json,
checksums.json. Script scripts/study_opening_strength.py reproducible sobre
fuentes congeladas; ningun archivo del estudio5% anterior sobrescrito.
Contexto de descubrimiento de precio/subasta: https://www.nyse.com/trade/auctions .
