# Apertura dentro antes de recalcular Bollinger

El 17/11 el usuario aclara expresamente que la vela nunca puede abrir fuera:
debe venir de dentro y salir con volatilidad. Confirma la pregunta que utiliza
como referencia las bandas de la vela anterior, antes de recalcular la nueva.

`v8_apertura_dentro_bandas_previas` exige apertura oficial entre el inferior y
superior de la ultima vela completada, inclusive. Una apertura fuera se excluye
durante toda esa vela, aunque el precio reentre o las bandas se ensanchen.
Se conservan tambien las comprobaciones de bandas iniciales (19 cierres mas
apertura) y actuales. Esto sustituye la suficiencia de la referencia inicial
del 06/11, documentada en STRATEGY_ORIGIN_REVIEW_2026-11-06.md.

La funcion compartida `detect_values` cubre avisos, replay, simulacion y
revalidacion REAL. No espera cierre ni agrega llamadas de red: compara valores
ya disponibles. Conserva 3% por cada banda, direccion/media, precio fuera,
primer cruce y primera senal sin renovar sus 30s, y frescura de 3s. No cambia
contratos, salidas, objetivo, stop ni armado de colas.

Se conserva EVENT_KEY_VERSION v4 y los alias v5/v6/v7 para no repetir eventos
o avisos por cambiar version. No se convierte un evento historico a v8 ni se
rearma una cola consumida. La version del payload permite rechazar fuentes
antiguas durante una recarga parcial.
La identidad REAL de v8 conserva la version v7 en su hash para que un intento
previo de la misma senal y primer instante no se convierta en otra compra.

Pruebas, evidencia de replay privado y carga efectiva se registran en
CURRENT_CONTEXT y el diario. Codigo en disco no demuestra carga en procesos.

Validacion final17/11:379pruebas aprobadas,75.397s. Incluye stream para ambos
sentidos, gap dentro de bandas recalculadas pero fuera de previas, reentrada,
limites inclusivos, rechazoREAL antes de buscar contrato y migraciondedup v7/v8.
Carga comprobada16:02ET en colector, radar yREAL con versionV8 yheartbeats
actuales; monitores de salidas intactos y cola pausada/consumida conservada.
Recarga tuvo arranque costoso y recuperacion de radar; detalle en continuidad.
