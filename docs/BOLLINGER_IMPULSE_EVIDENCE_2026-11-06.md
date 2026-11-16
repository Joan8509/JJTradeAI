# Evidencia de ruptura e impulso

El usuario autoriza comenzar el estudio de ruptura de Bollinger con volatilidad
y conservar evidencia futura. No autoriza con ello un filtro nuevo de compra.
Se mantienen los criterios operativos actuales y la prioridad de entrada.

## Instrumentacion independiente

`bollinger_impulse_observer.py` consulta `bollinger_tick_audit` y
`bollinger_live_events` mediante SQLite `mode=ro`, `query_only`, lotes de1000
y presupuesto SQL200ms. Cierra la conexion fuente antes de escribir el archivo
de investigacion. No importa componentes de cuenta, ordenes, avisos o conexion.
No abre otra suscripcion de mercado. Conserva ticks con geometria calculada,
incluidos los neutrales; no convierte prints excluidos en cotizaciones aptas.

Destino privado: `exports/trade_review/2026-11-06_impulse_study/`.
Cursor y filas se confirman juntos; reintentar no duplica datos. Las discontinuidades
de IDs posteriores al cursor quedan registradas. El inicio disponible no equivale
a historial completo. Conservar heartbeat y revisar errores/cobertura cada sesion.
La captura reintenta lecturas interrumpidas sin avanzar cursor. Tope de archivo2GiB
y minimo libre2GiB: al alcanzar cualquiera se detiene la captura con ERROR local;
requiere revisar almacenamiento antes de seguir. No se borran originales ni archivo.

Tarea nueva `JJTrade-ObservacionImpulso`: prioridad inferior a normal, instancia
unica, inicio de Windows y comprobacion cada minuto. Solo esta tarea utiliza S4U,
pues consulta archivos locales sin DPAPI ni red; no sustituye las tareas de mercado
o ejecucion que requieren otra identidad/autenticacion. No modifica sus definiciones.
Registro: `scripts/register_impulse_observer.ps1`.

## Estudio reproducible

Ejecutar `venv\Scripts\python.exe scripts/build_impulse_study.py`.
Produce `causal_playback.json` privado. Separar version, fuente, sesion y umbral
realmente aplicado. Ventanas ET:09:30-09:45,09:45-10:15 y resto de sesion.

Caracteristicas disponibles al decidir: expansion de cada banda, distancia de
ruptura y desplazamiento direccional previo1s/3s normalizado por ancho anterior.
Solo se usan ticks recibidos al decidir y con timestamp no posterior a la senal.
La ancla admite hasta1s adicional de antiguedad: son desplazamientos aproximados,
no velocidades exactas por segundo. Ausencia de ancla se registra como desconocida.

Etiquetas posteriores separadas: retorno del subyacente1/3/5/10/30/60s con extremo
observado a menos1s; no garantizan trayectoria intermedia. MFE/MAE30s solo si las
observaciones no presentan huecos superiores1s. La falta de cobertura no es perdida
ni ganancia. Aun con cobertura son extremos observados IEX, no todos los mercados.
Estos retornos no permiten estimar directamente ganancias10/20/35% de una opcion.

Elegir candidatos en sesiones anteriores completas y evaluar en sesiones posteriores
sin usarlas para elegir. Comparar frecuencia, continuidad, retrocesos, movimientos
favorables descartados y resultados de opciones cuando existan cotizaciones/fills.
No activar un porcentaje por una captura, una ganadora o por alcanzar un numero
arbitrario de senales. El resultado inicial tiene cobertura insuficiente de apertura.

Validacion: pruebas focales de lectura exclusiva, cursor/deduplicacion, huecos,
causalidad y etiquetas sin cobertura. Estado efectivamente desplegado y resultados
actuales en CURRENT_CONTEXT y diario local; esta especificacion no acredita uptime.
