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
 incluye contexto, pero no esta publicado. Este contexto no cambia el detector vigente;
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

## 2026-11-09 - Direccion y recorrido incorporados a la interfaz

Nueva lectura compartida REAL/SIM en ma_price_outlook.py y ma_outlook_panel.py.
Usa exclusivamente contexto SMA guardado y causal: orden y pendientes20/40,
fondo100/200, validacion de cruces y sesiones, acuerdo/desacuerdoHoraDiario.
Ordena medias por delante del movimiento (ascendente paraCALL, descendente
paraPUT) con valor ydistanciaUSD/% respecto al precio ORIGINAL de la senal.
Una media favorable por delante puede ser continuidad: no se etiqueta toda
media como resistencia. Posibles limites conservan rolespiso/techo ya existentes.

REAL: Estado de la estrategia > Actualizar diagnostico, seccion Medias moviles
y posibles niveles de recorrido. SIM: tarjetas de senal con contexto SMA.
No se agrega tab ni boton, ni autorefresco. Son lecturas de senales guardadas,
con fecha/hora, fuente ypreciooriginal visibles; no cotizaciones actuales.
No cambia objetivo/stop20%, seleccion decontrato, cronometroV7, apertura ni3%.
Calculo de contexto sigue en workerauxiliar existente; nueva presentacion no
interviene en compra, emisorTelegram o monitor de salidas.

Faltantes, cruces no validados y temporalidades en conflicto quedan explicitos.
LecturaSQLRO solo200eventosmaxdehoy,750mslimiteSQL, sinagregacion/historico ni
llamadas a broker/feed; no rescata contexto viejo ante ultimo faltante/futuro.
Validacion:68pruebasOK25.505s en8modulos; despuesdeoptimizarconsulta yreforzar
causalidad,20pruebasOK12.691s incluidas9nuevas, dashboardSIM yvista REAL.
Prueba lectura guardada: primera importacionfria2.4s, posteriores14.03/18.66ms
para6companias, soloUI, no latencia de entrada. Cinco companias tienencontexto
guardado; QQQsinseñalhoy no se inventa lectura. No es estudio predictivo ni
adaptacion automatica de objetivos. Evidencia privada2026-11-09_ma_outlook.
