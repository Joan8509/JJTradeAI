# Estudio de oportunidades rápidas — 13/11/2026

Se compararon 110 señales de 19 compañías con la estrategia actual V7, fuente
IEX y sesión regular. Se conservaron las 73 del 9–11/11 como desarrollo y las
37 del 12–13/11 como contraste posterior; el día 13 estaba incompleto al corte.
El caso real que motivó el estudio y sus comprobantes permanecen privados.

El playback mide movimiento del subyacente a 10, 30 y 60 segundos, con el mismo
precio original de señal. No interpreta esos resultados como ganancias de
opciones. Hay cobertura exacta de 42, 33 y 42 casos, respectivamente; los huecos
no son pérdidas. Las medias añadidas asíncronamente no se consideran datos
demostrados como disponibles para decidir la compra original.

Los criterios mantienen umbrales de estudios anteriores: expansión contraria,
recorrido fuera de banda, volumen relativo, velocidad, apertura de bandas y
edad de ruptura. No se optimizan umbrales usando los días posteriores.

Observaciones útiles para continuar:

- El 5% obligatorio habría descartado el caso ganador que originó esta revisión.
  Se conserva el 3% y la detección inmediata.
- Volumen relativo y recorrido fuera de banda son candidatos descriptivos. En
  el contraste, volumen >=1,5 tuvo 4/6 movimientos favorables a 10 segundos
  cubiertos, frente a 2/5 en el grupo descartado. Recorrido >=1% del ancho previo
  tuvo 3/3, con muestra demasiado pequeña para llamarlo acierto operativo; también
  habría descartado el caso ganador al primer evento.
- Dos casos de resultado distinto tenían las medias 20/40 alineadas en hora y
  diario: la alineación sola no los distingue.
- La rapidez también depende de llegar con el catálogo preparado. Los recibos
  locales del caso revisado muestran una primera búsqueda de 4,91 segundos que
  terminó con referencia vencida; un intento posterior se preparó en 1,40
  segundos, incluido el preview. La causa de la preparación inicial lenta debe
  comprobarse antes de modificar ese mecanismo ya existente.

No se activó ningún filtro ni se modificaron compras, objetivos, stop, servicios
o colas. El selector exige 30 resultados retenidos y el desarrollo tiene solo
30 cubiertos a 10 segundos: no puede validar un descarte. Esto expresa falta de
soporte para elegir automáticamente, no una prueba de ineficacia general.

La siguiente mejora a evaluar es preparar anticipadamente los contratos de las
compañías seleccionadas, incluida la recuperación después de renovar la
autorización de datos, manteniendo cotización y preview actuales. Para estudiar
certeza deben unirse contexto causal, fases de entrada y trayectoria del mismo
contrato; detectar rápido y alcanzar la ganancia son medidas distintas.

Herramientas reproducibles: `scripts/study_fast_opportunities.py` y
`scripts/render_fast_opportunities.py`. Evidencia privada congelada en
`exports/trade_review/2026-11-13_fast_opportunities/`, con todos los candidatos,
descartes, cobertura, fills locales, tiempos, validación y checksums. Las pruebas
de los módulos de análisis y fuerza: 25 aprobadas en 8,522 segundos.
