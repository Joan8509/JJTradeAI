# Estado del trabajo — 12 de octubre de 2026

## Objetivo y reglas vigentes

Radar exclusivamente de salida Bollinger con volatilidad en velas parciales de
15 minutos. Avisos informativos por Telegram, sin aprobar ni ejecutar operaciones.
El análisis utiliza barras de un minuto, no ticks. Las bandas deben expandirse
en ambas direcciones y el centro acompañar la salida. Cierre anterior dentro de
bandas. Se notifica una vez por símbolo/vela/dirección/chat.

Corrección aplicada y radar reiniciado: `v3_bandas_en_apertura`. Se calculan las
bandas al abrir usando 19 cierres completos conocidos y el precio de apertura.
Se excluye una apertura ya fuera de esas bandas, pero no se rechaza simplemente
por estar fuera de las bandas de la vela anterior. Se requiere avanzar respecto
a la apertura. AAPL del 12/10, vela 09:30 ET: apertura 338,13 dentro de banda
superior recalculada 338,3627; primer cierre de minuto 341,06. Detectado en replay.
No se envió una alerta atrasada. Los estudios anteriores con v2 quedan históricos.

## TSLA: investigación de salidas débiles

Aviso real de 12/10 10:34:09 ET, fuente minuto 10:33: precio 379,625,
banda inferior 379,6648. Exposición 0,69% del ancho de bandas. Regresó dentro
al siguiente cierre de minuto. El usuario lo observó aproximadamente a las 10:35.

Playback v3, últimos 90 días naturales, corte 2026-10-12T17:41:55.935094Z:
107 detecciones, 90 evaluables sin ventanas solapadas en la base.
Informes en `exports/bollinger_playback/TSLA_weak_20261012_174155/`.
Exposición <1%: reentrada dentro de 2m en 71,4% de 14 casos antiguos y
80% de 5 recientes. Profundidad mayor reduce reentradas tempranas, pero no
demuestra más continuidad favorable a 15m ni rentabilidad de opciones.

Simulación adicional en subcarpeta `waiting_1pct`: esperar si exposición <1%
del ancho; avisar si gana exposición conservando regla; cancelar al primer
cierre de minuto dentro, sin reactivar ese evento. Solo dentro de la misma vela.
Resultado desde nuevo momento/precio, no desde aviso antiguo:
- Periodo antiguo: 64 -> 55 avisos, 5 negativos suprimidos y 4 positivos perdidos;
  positividad 29/64 -> 25/55. Cinco avisos demorados, media 1,2m.
- Reciente: 26 -> 23 avisos, 3 negativos suprimidos, 0 positivos perdidos;
  positividad 13/26 -> 13/23. Dos avisos demorados, media 1m.
- Habría evitado TSLA 10:34. Umbral exploratorio, no validado independientemente.
  Los datos ya se exploraron; no constituye validación fuera de muestra.

**No se aplicó supresión de avisos débiles al radar real.** Recomendación
aceptada para continuar: probar las demás compañías y luego registrar en
paralelo durante sesiones nuevas antes de aplicar un filtro obligatorio.
Última verificación: 22 pruebas de detector/estudio/simulación pasaron.

## Preferencias y pendientes

Medias utilizadas por Joan: pares 20/40 y 100/200. Pendiente confirmar SMA/EMA
y temporalidad; todavía no incorporadas al filtro ni investigación.
Watchlist 17: AAPL NVDA TSLA AMD META MSFT BABA SPY QQQ IWM DIA MU NIO GLD
AMZN NFLX AVGO. AVGO sin historial/actividad en el antiguo scanner de 16.
No detener ese scanner sin asegurar credenciales y continuidad de datos.

Telegram habilitado y chat vinculado; configuración local protegida por DPAPI
de Windows. Clave cifrada no es portable a otro usuario/PC sin reconectar bot.
El radar sigue dependiendo del PC encendido, Internet y procesos vivos. Guardar
el proyecto no garantiza reinicio automático ni alertas durante un apagado.

Vercel: frontend privado y backend continuo preparados, no publicados.
`docs/VERCEL_DEPLOYMENT.md`, `web_vercel/`, `deployment/`, `cloud_runtime.py`.
Falta cuenta/autenticación, servidor continuo, DNS y configuración privada.
No se contrató alojamiento ni se conectó Schwab. No órdenes automáticas.

## Cómo retomar

Leer este documento y contrastar los procesos/heartbeat reales (los PID cambian).
Antes de cambiar reglas, conservar versión y separar resultados históricos.
No publicar credenciales ni copiar tokens al chat. Mantener deduplicación de
`bollinger_phone_notifications` y la base `exports/market_data.db` al restaurar.
Scripts reproducibles: `scripts/analyze_tsla_weak_exits.py` y
`scripts/test_tsla_wait_playback.py` (este último referencia el informe congelado).
