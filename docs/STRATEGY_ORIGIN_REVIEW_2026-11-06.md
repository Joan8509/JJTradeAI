# Origen de la vela: correccion autorizada el 6 de noviembre

Usuario confirma expresamente: si una vela ya empieza fuera de Bollinger,
descartarla para esta estrategia. Sustituye la comparacion de apertura con bandas
posteriores autorizada26/10. Version nueva v6_apertura_dentro_bandas_iniciales.

Debe abrir dentro de las bandas calculadas con19cierres anteriores y su apertura
oficial. Despues puede salir y cumplir3% por CADA banda, direccion y midpoint.
Se conserva tambien apertura dentro de bandas actuales. No se espera cierre de
vela/minuto, no se anade red, volumen, velocidad, un nuevo porcentaje ni veto del
cierre anterior fuera. La membresia inicial no puede aparecer retroactivamente
cuando las bandas se ensanchan.

Historia comprobada Git:12/10 b6236bb habia veto del cierre previo y apertura
inicial dentro;13/10 a10ec0a retiro el veto del cierre anterior.22/10 se introdujo
minimo1%;26/10 Git7e613b5 contiene3% y apertura con bandas al detectar.30/10
se autorizo5%, sustituido02/11por3%. No se encontro filtro de velocidad que
existiera y luego se hubiera quitado. La volatilidad programada era expansion
de ambas bandas; no prueba por si sola fuerza/velocidad independiente.

En19eventos de hoy con geometria original,5tenian apertura fuera de bandas
iniciales pero dentro de las posteriores. La regla nueva los excluye por origen;
eso no demuestra que fueran perdedores ni que hubiera compras. SLV pasa las dos
interpretaciones, por lo que esta correccion no basta para explicar ese caso.

Implementacion compartida en detect_values; el stream pasa bandas iniciales
exactas de19cierres. El replay usa las mismas referencias. Cuando solo estan
disponibles las bandas/mean del precio actual, sus momentos permiten reemplazar
ese precio por la apertura enO(1), sin otra consulta; no se usan datos futuros.
RealPreparation revalida con campos iniciales; diagnostico explica nueva condicion.
Version distinta para separar resultados, claves canonicasv4 y aliasesv5 se
conservan para no renovar la primera senal ni repetir avisos por la migracion.

SLVexport1517filas reproduce1497paresTC20/2 con maxerror0.00000816USD. Termina
13:44:14ETantes del aviso13:53:14; ultima fila parcial ysinbandas no certifica
ese intervalo. IWM/SLV muestran~15min entre ultimo timestamp ycreacion dearchivo;
puede ser retraso o transferencia, requiere indicadorRT/15-MinuteDelayed deTC.
WindowsNTP consultado sololectura reporta sync13:51:03ET,sinwarning,dispersion31ms.
TC2000 explica indicador ytooltip en https://www.tc2000.com/features/whatsnew .
No cambiar feed, reloj o suscripcion basandose solo en creacion dearchivo.

Pruebas/carga efectiva quedan en CURRENT_CONTEXT y diario. No confundir codigo
preparado con procesos activos, ni esta correccion con resolucion de todas las
diferencias visuales. Evidencia privada slv_notice/ e initial_origin/.
