# Cierre anterior y máximo del historial

La salida de Bollinger incorpora referencias de precio además de SMA:

- Cierre de la sesión anterior en las barras Alpaca/IEX. El calendario identifica
  la sesión anterior, no el día natural anterior. Se verifica la presencia de
  su último minuto; si falta, el cierre disponible queda marcado sin verificar.
  Si falta toda la sesión, se muestra último cierre disponible, sin llamarlo
  cierre de ayer. No es un cierre oficial consolidado o precio de subasta.
- Máximo de los máximos diarios de sesiones anteriores del historial cargado.
  Se identifica fecha y cobertura; se excluyen datos futuros y la sesión actual.
  **No es un all-time high verificado**: no tenemos historial completo desde
  la salida a bolsa ni certificación de ajustes por splits y otras acciones.

Distancia porcentual desde precio del aviso y ubicación delante/detrás del
movimiento. Delante de una salida alcista: posible resistencia; delante de
una bajista: posible soporte. Si el precio ya pasó el nivel, no se marca como
barrera por delante. Contacto exacto queda señalado sin tolerancia inventada.

Se combina con posibles pisos/techos SMA para mostrar la barrera candidata
más próxima. Es contexto descriptivo: no bloquea ni aprueba señales y no
demuestra que el precio se frenará. El ATH real sigue pendiente de disponer
de una fuente histórica completa y coherente con precios actuales.

Incluido en nuevos avisos Telegram, eventos y estado del radar, dashboard
Streamlit y frontend Vercel preparado (no publicado). No se sobrescriben eventos
históricos. Versión del detector v3 permanece igual.
