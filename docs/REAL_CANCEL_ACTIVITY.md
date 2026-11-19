# Confirmacion de cancelacion con patas de actividad

17/11/2026: se observo en un GET autentico de Schwab una orden SINGLE OPTION
CANCELED con actividad EXECUTION/executionType CANCELED, cantidad cancelada,
orderRemainingQuantity0 y executionLegs con precio0. El normalizador anterior
clasificaba toda actividad noFILL con patas como UNSUPPORTED_EXECUTION_ACTIVITY.
La orden quedaba RECONCILIATION_REQUIRED y conservaba reserva, impidiendo continuar
el stop tras cancelar el objetivo. No era un fill ni autorizaba ignorar reservas.

La correccion reconoce SOLO esa forma terminal y coherente: cuenta/orden/contrato
SINGLE ya verificados, estadoCANCELED, actividadEXECUTION/CANCELED, cantidad igual
al remanente sin llenar, remanente actividad0, una pata del mismo legId, cantidad
consistente, precio0, mismarked0, instrumento igual si se informa y tiempo con
zona dentro de entered/close cuando estan presentes. Lo demas conserva revision.
Nunca agrega un fill por esta actividad; los fills reales mantienen historia
completa, cantidades, precios, identidad, multiplicidad y ausencia de regresion.

El GET terminal valido libera exclusivamente la reserva sin llenar. El stop
persistido puede entonces vender el remanente propio al Bid vigente, con todas
las guardas habituales y sin repetir envios inciertos. Un fill durante cancelacion
reduce el remanente; un cierre manual detectado conserva hold y se concilia antes
de cualquier otra venta. No cambia objetivo,stop20%,entrada,simulacion oSEV25.

Las pruebas incluyen cancelacion sin fills, parcial, actividad desconocida,
precio positivo, cantidades/leg/tiempo incorrectos, cancelacion mientras sigue
WORKING, recuperacion de una conciliacion bloqueada con GET exacto y recorrido
de stop tras cancelacion con venta unica del remanente. Replay adicional privado
con los GET autenticos, solo memoria ysinHTTP/escrituras operativas, confirma
cancelacion y cierre manual sin cantidad pendiente. Revision diagnostica
cancel_activity_revision=1. Codigo presente no demuestra carga: consultar contexto.

Una comprobacion de salud previa a la compra no sustituye pruebas del ciclo
cancelacion/fills/salida. No llamar resuelto hasta verificar carga y conciliacion
actual. Evidencia privada2026-11-17_aapl; detalles individuales permanecen fuera
de la documentacion versionable.
