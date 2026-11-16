# Ruptura temprana: correccion del 6 de noviembre

Peticion del usuario: revisar y corregir los avisos recientes de SPCX, META,
AAPL y TSLA, investigando tambien cambios que deterioraron el comportamiento.

## Defecto encontrado y alcance

El reloj de30segundos existente empezaba cuando la geometria cumplia TODAS las
condiciones. El precio podia llevar minutos fuera antes de alcanzar el3% de la
banda contraria y aparecer entonces como oportunidad nueva. No es un retraso
demostrado de Telegram: los cuatro envios fueron aceptados entre0.665y1.530s
desde sus trades fuente; no mide llegada al telefono.

Replay causal del archivo conservado: SPCX llevaba665.845937s fuera desde la
primera salida observada; META312.951518s; AAPL72.640854s. Sus avisos aparecieron
al llegar al3%. TSLA cruzo y cumplio en el mismo trade: esta correccion NO lo
descarta ni demuestra resolver su discrepancia visual. Los1355ticks con geometria
de estos cuatro intervalos coinciden con la aritmeticaV6; esto no prueba que
representen la estrategia que el usuario observa enTC2000.

## Cambio V7

`v7_ruptura_temprana_30s` conserva la geometriaV6 y limita la primera oportunidad
a30segundos desde el primer precio observado fuera por cada lado de esa vela,
aunque todavia falte3%. No espera30s. El instante30exacto ya esta vencido.
Es un inicio de caducidad mas estricto que el anterior, autorizado en el contexto
de corregir entradas/avisos tardios; puede descartar una continuacion posterior.
No presentarlo como comparacion descriptiva ni como regla antigua sin cambios.

El reloj persiste porfeed/alcance/simbolo/vela/lado en nueva tablaSQLite. Se
publica en la misma transaccion asincrona que la proyeccion, con UPSERT que solo
acepta un instante mas temprano. La evaluacion usa memoria, sin HTTP ni sleeps.
Una reconexion dentro del proceso conserva memoria; un proceso nuevo recupera
por clave indexada. Si reconecta dentro de vela y falta prueba del primer cruce,
no inventa una oportunidad: debe recuperar reloj conocido o esperar otra vela.
Las barras de respaldo tampoco fabrican reloj: requieren prueba persistida.

La señal incluye primera ruptura y vencimiento. Radar comprueba el plazo al
evaluar y antes de enviar; lectores comunes/SIM/REAL comprueban otra vez y
acotan la autorizacion al menor plazo. La caducidad original de primera señal
tambien permanece: un reloj no amplía al otro. Apertura inicial dentro,3% por
cada banda,price/midpoint,frescura3s yperiodosoficiales intactos. Sin nuevo umbral
de volumen, fuerza absoluta, distancia al borde o confirmacion futura.

Claves canonicasV4 yavisosV1 no cambian; agrega aliasV6 sin borrar eventos.
No reinicia colas, primera entrada, solicitudes, incertidumbres ni dedup.
Objetivos/stop20%/salidas manuales y monitores no dependen de la nueva caducidad.

## Evidencia y carga

Privado `exports/trade_review/2026-11-06_breakout_clock/`: replay de cuatro casos,
migracion de relojes originales, guardas previas/post, recarga y verificacion.
El seed combina archivo del observador con auditoria reciente de produccion,
solo geometria conocida entonces; no usa cierres futuros ni emite eventos.
En la migracion se examinaron218797filas y se recuperaron69relojes para evitar
reiniciar su edad al cargarV7. No se modificaron colas ni ordenes.

Pruebas especificas: ruptura debil que llega tarde al3%, ruptura valida rapida,
30sexactos,retraccion,primer cruce desconocido,reconexionantesdepublicar,nuevo
proceso conSQLite,rechazo de relojes manipulados,lectoresSIM/REAL,versiones,
dedup/referencias/heartbeat. Estado efectivo y limites en CURRENT_CONTEXT;
no declarar cargado mientras la recarga siga esperando el backup obligatorio.

Pendientes que NO resuelveV7: datos NasdaqBasic deTC frente aIEX, aperturaTSLA
distinta porfuente y discrepancia visual del ultimoTSLA. No aumentar3% ni
invertir lados sin evidencia; no usar exportaciones historicas para ordenar.

## Carga verificada15:31:28ET

Receptor6536 con V7, revisionclock1 y hashes de stream/detector/clock coinciden;
heartbeat conectado. Radar/companion3532 actual y SIMmonitorready. UIHTTP200.
HostREAL544 cargaV7/clock1 y conserva ACK/exitrevision1, pero workersREAL no
estan actuales y cuenta no actual: no certificar conexion ni operacionREAL.
Bloqueos locales reportadosLIVE_EXIT_MONITOR_NOT_CURRENT,
LIVE_HOST_REQUIRES_REVIEW,LIVE_OPTION_DATA_AUTH_NOT_CURRENT. La reautorizacion
Schwab estaba pendiente antes de esta recarga; no se hizo consulta de broker
ni envio de orden para verificarla. Conservados hashes de control/cola/journal/
ledgerSIM, sinarming niTGtest. Primer snapshotposterior contiene14proyeccionesV7
y5registrosV6todaviasintrade nuevo; no afirmar19simbolosV7recientes. La version
vigente y frescura impiden usar esos registros viejos para entradas nuevas.

Detencion ultimoheartbeat15:24:34; V7loaded15:31:00, conectado verificado15:31:28:
interrupcion aproximadamente7min. BackupAPI SQLite1,585,410,048B integraOK,
snapshotpinnedreadtransaction yportableDELETE;copy212.783s. Se completo el mismo
arranque, sin repetir receptor. Nuevas posiciones/solicitudespropias0enledger;
eso no equivale a consultar todas las posiciones actuales de la cuentaSchwab.

Suites exitosas89tests23.559s,89tests26.893s y8tests0.910s con solapamiento;
no sumar como casos distintos. Hubo un comando amplio206 con modulo dehost mal
nombrado,205funcionales sin fallos pero comandoFAIL; seleccion corregida usa
real_host_integration yreal_host_refresh. Otras expectativas de fixtures/esquema
se actualizaron al nuevo contrato y se repitieron las selecciones pertinentes.
No se declara suite general206OK. No commit ni push en este bloque.
