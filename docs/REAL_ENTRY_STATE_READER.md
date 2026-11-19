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

## Revalidacion final del contrato elegido

16/11: despues del preview, REAL limita la ultima seleccion al contrato exacto
ya elegido. Conserva el calendario completo y TODO el inventario de strikes:
filtrar las cotizaciones no convierte el sexto OTM en el primero. Relee la senal
y comprueba direccion, precio actual, vigencia de cadena y quote, vencimiento,
rango y spread con las mismas funciones. Si no esta o deja de cumplir, bloquea;
no sustituye contrato ni reutiliza una admision previa. La busqueda inicial y
la alternativa por fondos siguen evaluando todos los candidatos necesarios.
Manual/SIM no pasan el nuevo parametro y conservan su recorrido anterior.

Prueba sintetica de300pares/49contratos: mediana2.21285ms completa contra1.30205ms
acotada. Ahorro local aproximado0.91ms, no tiempo total broker. Las pruebas de
equivalencia incluyen sextoOTM con inventario completo, quote vieja, retraccion,
contrato ausente, cadena vieja y direccion distinta. Estado cargado se identifica
por entry_selected_revalidation_revision=1 y se registra en continuidad local.
