# Refrescos y estabilidad de la preparación

26/10/2026 20:59 ET. Usuario nota recargas frecuentes y sensación de pérdida
al navegar/editar. La reducción del fondo y la conexión no bloqueante no
habían eliminado los temporizadores de presentación.

Medición antes del cambio: navegador móvil390px, campo numérico enfocado
con valor7 sin confirmar,16 segundos.308 muestras:50 con elementos stale,
0 reemplazos de campo,0 pérdida de foco,0 deshabilitaciones,0 cambios de
valor,0 excepciones. La prueba acredita actualizaciones repetidas, no un
borrado de datos. No se compró ni armó la cola activa.

Cambios solo de interfaz:

- Indicador Schwab deja de tener temporizador2s. Se recoge su recibo de
  fondo al interactuar; botón Comprobar pide consulta explícita. Guardar la
  cola sigue requiriendo consulta nueva autenticada, autorización y el resto
  de controles. No caduca ni se relaja ninguna tolerancia operativa.
- Preparación de cola sin temporizador por defecto. Un control Seguimiento
  en vivo permite actualizar solo la cola cada2s. Se activa tras guardado
  exitoso, y se desactiva al editar compañías, cantidades, objetivos, modo
  o sesión. **Esto no pausa QueueStore ni entradas/salidas/Telegram.**
- Actualizar cola refresca su fragmento manualmente, sin recrear formulario.
- Mis operaciones deja de releer historial cada5s; conserva Actualizar y
  actualización al entrar/interactuar. Estrategia en Vivo conserva3s y el
  monitor operativo sigue independiente de las pantallas.
- No se vuelve a escribir el parámetro vista si ya tiene su valor correcto.
  Diseño y fondo preservados.

40 pruebas OK en2 tandas:30 en19,045s y10 en8,103s (distintas). Incluyen
selección/cantidad/objetivo/autorización, lote atómico, conexión, navegación,
historial y seguimiento visual. Nueva prueba confirma que apagar el
seguimiento no llama pause/arm/archive, y editar tras un envío no modifica
el lote guardado. py_compile/diffcheck OK.

Prueba antes y fuentes previas privadas en
`exports/trade_review/2026-10-26_refresh_stability/`. Recarga solo interfaz
y comparación móvil posterior pendientes al crear este registro. No cambios
en DB activa, estrategia, detector, dedup ni órdenes reales deshabilitadas.
Sin commit/push. Siguiente paso: repetir16s para comparar stale y foco.

Resultado posterior21:01:33 ET:319 muestras en16 segundos, **0 stale**,
0 reemplazos/blur/deshabilitaciones/cambios de valor/excepciones. Valor7
sin confirmar se conserva, ancho390px sin desbordamiento. Comparado con
50/308 stale antes: eliminada la actividad periódica observada durante
la preparación, sin afirmar mejora de latencia de todos los endpoints.
Interfaz recargada únicamente21:00:13 ET, health200 y procesos de mercado
preservados. Evidencia after.json, before.json y observe.py privados.
Ningún armado/orden/mensaje. Cambios activos; seguimiento al guardar y
edición posterior acreditados en pruebas aisladas. Confirmación de uso
en el teléfono del usuario sigue pendiente. Fuentes/pruebas empaquetadas
privadamente para continuidad. No commit/push.
