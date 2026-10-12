# Medias como contexto de Bollinger

El radar incorpora pares 20/40 y 100/200 en Hora y Diario como contexto,
no como aprobación ni filtro de notificaciones. SMA provisional: la documentación
de la clase no especifica SMA/EMA. No presentar la elección como regla del mentor.

Solo velas anteriores cerradas: se excluyen la hora en formación y el día actual.
Se registran orden de pares, pendientes, ubicación del precio y distancia desde
el precio del aviso a cada media disponible. Se muestra la más cercana por delante.
Orden alcista/bajista no verifica todavía los dos días desde el cruce exigidos
por la clase. Una media por delante no demuestra bloqueo; ausencia de medias
por delante no demuestra camino libre. Historial insuficiente se indica;
las barras recibidas pueden contener huecos, no se certifica cobertura completa.

Integración: eventos nuevos, estado del radar, mensajes nuevos de Telegram y
tarjetas Streamlit. Eventos históricos no se sobrescriben. Detector v3 sin cambios.
El frontend Vercel no está publicado ni muestra todavía este contexto.

`scripts/analyze_ma_context_playback.py` anotó los 1181 eventos del estudio
congelado de recorrido. Asociaciones descriptivas mezclando símbolos y direcciones,
no causales ni validadas fuera de muestra:
- Media por delante a <0,10%: 101 casos, avance medio al primer retroceso 0,0449%.
- Media por delante a 0,10–0,50%: 277 casos, avance medio 0,0667%.
- Media por delante a >=0,50%: 523 casos, avance medio 0,0896%.
- No se encontró ventaja clara de alinear simplemente el orden de pares.

Antes de filtros, desglosar por compañía, dirección y periodo, validar prospectivamente. El filtro de salidas débiles
continúa en simulación; no se activó ejecución.
