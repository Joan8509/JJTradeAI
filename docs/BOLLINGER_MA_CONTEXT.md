# Medias SMA en la estrategia Bollinger

SMA 20/40 y 100/200 confirmadas por Joan en TC2000. Calculadas localmente
con barras Alpaca/IEX en Hora y Diario; no hay API TC2000.

## Reglas implementadas

- Orden de pares, pendiente individual, posicion y separacion porcentual.
- Ultimo cruce observado, sesiones desde cruce y fase. Se requieren dos
  transiciones entre sesiones presentes despues del cruce para validar tendencia.
  Sin cruce observado, no se valida. Corto: 2 a menos de 5; medio: 5 a 15;
  largo: mas de 15. No certifica continuidad de datos ni calendario completo.
- Cruces en las ultimas 20 velas como medicion, sin umbral de lateralidad.
- Papel segun tendencia validada y direccion de aproximacion: posible piso,
  techo, continuidad alcista/bajista o media por detras. Una media por delante
  en tendencia favorable puede ser continuidad y no un bloqueo.
- Distancia al precio del aviso y siguiente posible piso/techo. Peso relativo
  20 < 40 < 100 < 200 registrado, sin probabilidades ni puntajes arbitrarios.
- Contacto exacto con el rango de la ultima vela de Hora cerrada y cierre
  direccional distinguen rebote, rechazo y ruptura observados. Se usa la media
  conocida antes de esa hora, tambien para las diarias. Se muestra fecha;
  una observacion historica no confirma la nueva salida de Bollinger.
- Episodios de contacto en ultimas 20 horas para medias horarias. Contactos
  consecutivos cuentan como uno; no se afirma automaticamente debilitamiento.

Solo velas cerradas, sin cierre futuro. Datos insuficientes se indican.
Las barras recibidas pueden contener huecos; no se certifica cobertura completa.

## Integracion

Nuevos avisos Telegram, eventos guardados y tarjetas Streamlit con detalle
expandible de cruces, medias y cierres de Hora. Frontend Vercel preparado
incluye contexto, pero no esta publicado. Detector v3 permanece igual;
no se activa aprobacion de entrada ni supresion por medias/salidas debiles.

## Pendientes de validacion

La clase no define tolerancia de toque, separacion minima saludable, umbral
para cruces repetidos, debilitamiento por rebotes ni espacio minimo. Se miden
sin inventar limites. Conteo de contactos diarios, rebotes efectivos y peso
comparativo del primer acercamiento requieren un estudio independiente.

## Evidencia

El estudio geometrico previo de 1181 eventos no valida este nuevo clasificador.
Media por delante a <0,10%: 101 casos, avance medio inicial 0,0449%; >=0,50%:
523 casos, 0,0896%. Asociaciones agregadas, no causas ni certeza demostrada.
Antes de filtros, estudiar por compania, direccion y periodo y validar en vivo.
