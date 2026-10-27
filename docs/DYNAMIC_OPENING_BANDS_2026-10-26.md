# Apertura dentro de las bandas del momento

Usuario confirma expresamente26/10, tras comparar captura: al detectar salida,
el precio real de apertura de esa misma vela debe estar dentro de las bandas
dibujadas/calculadas en ese momento. Esta aclaración sustituye la comparación
con bandas congeladas al inicio de la vela de v4; no elimina apertura dentro.

Versión de payload v5_apertura_dentro_bandas_actuales. Mantiene Bollinger15m,
20/2ddof0,19cierres completos + precio ahora, apertura oficial no sustituible,
expansión mínima3% en CADA banda (autorización posterior26/10, sustituye1%), dirección de precio/apertura/media y señales
intravela sin cierre futuro. No cambia IEX, referenciaREGULAR, controles3s,
cuarentena, contratos, rango, spread08,OTM5,stop20 o realesOFF.

Regla central detect_values aplica lower_actual <= apertura <= upper_actual.
Parámetros antiguos opening_upper/lower quedan compatibles para herramientas
históricas, pero no autorizan/vetan la señal. TickGeometry conserva bandas
iniciales solo como diagnóstico y declara opening_referenceCURRENT_BANDS;
preview/minuto/estudio comparten el mismo predicado. Vela que siga abriendo
fuera de las bandas actuales no cumple; tocar la banda con el precio no basta.

Identidad de eventos EVENT_KEY_VERSION continúa en v4 para no duplicar ni
sobrescribir primer evento por símbolo/vela/lado. Payload nuevo declara v5;
lector de referencias admite aliases de versión y conserva referencias
manuales v4 entregadas, sin relabelarlas. Avisos v1/chat/proveedor/vela/lado
y claims automáticos no cambian. No replay de avisos o compras históricos.

Regresión/replay y estado real de carga en diario26/10. Preparar fuentes no
demuestra que colector/radar/interfaz ya cargaron la versión: comprobar
strategy_version, hashes y snapshots vivos. Nunca dos conexiones simultáneas
al endpoint de Alpaca para desplegarlo.
