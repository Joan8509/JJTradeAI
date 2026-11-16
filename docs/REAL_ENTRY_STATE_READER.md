# Lecturas de senal en la entrada REAL

16/11/2026: RealEntryStateReader reutiliza una conexion SQLite de sololectura
por hilo para las revalidaciones automaticas. Cada llamada abre y cierra una
transaccion de lectura nueva; no guarda resultados ni una snapshot entre
llamadas. El timeout/presupuesto2s anterior y query_only permanecen. La
identidad de archivo se comprueba antes de reutilizar la conexion. Un error
cierra esa conexion y bloquea la lectura; no retorna la ultima senal buena.

La consulta comun _read_manual_document conserva sesion oficial, heartbeat,
ultimo tick y primer instante original de senal. Se omite solo la proyeccion
asincrona del panel, que no autoriza compras. Todos los controles posteriores
siguen: estrategia/apertura,3%,frescura3s,reloj30s,saldo,contrato,preview,
reserva durable y prohibicion de reenviar lo incierto. Cada tick se vuelve a
decodificar para no compartir un resultado mutable con el llamador.

El lector se inyecta solo en RealOpportunities cuando no hay lector explicito.
Las rutas manuales/UI/SIM conservan read_manual_state y su conexion habitual.
Diagnostico host entry_state_reader_revision=1 si esta cargado realmente.
Consultar CURRENT_CONTEXT para estado de carga y verificacion vigente.

Benchmark sintetico local300pares alternando orden de ejecucion: mediana
2,6296msantes frente0,2271msahora, resultados autoritativos iguales. No es una
medicion de Schwab ni de entrada total; el ahorro real debe medirse por fases
en la siguiente senal natural. El archivo de benchmark y resultados permanece
privado bajo2026-11-16_entry_state. No se prueba comprando en cuenta real.
