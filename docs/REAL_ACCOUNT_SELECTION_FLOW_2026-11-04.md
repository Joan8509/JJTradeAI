# Una selección de cuenta para todo el recorrido real

El usuario pide quitar «Preparar la conexión de cuentas» y eliminar la segunda
conexión exigida al pasar desde Cuenta a Cola real.

En Cuenta queda «Consultar conexión y cuentas». Primero obtiene la lista sin
seleccionar implícitamente la primera cuenta. Cuando el usuario elige una,
se consultan saldos, posiciones y órdenes, se comprueba su identidad y se registra
esa cuenta en el control cifrado que ya utiliza el ejecutor. El mismo botón
permite actualizar después la lista y los datos de la cuenta seleccionada.

La referencia permanente de selección se conserva al cambiar de vista, aunque
Streamlit retire temporalmente el widget del selector. La consulta histórica de
saldos se identifica por su hora; no se exige volver a elegir la cuenta porque
esa visualización tenga más de un minuto. El ejecutor conserva sus comprobaciones
independientes de conexión, fondos y autorización vigentes.

Cola real utiliza la cuenta ya registrada y elimina «Conectar cuenta real y
verificar». Activar preparación guarda y arma la selección en una sola acción explícita;
ver REAL_QUEUE_CONTROLS_2026-11-04.md. Seleccionar/consultar la cuenta no arma una cola,
no reanuda compras pausadas y no envía órdenes. Un cambio de cuenta continúa
bloqueado si la anterior tiene órdenes, posiciones propias o cola activa.

No se modifica el registro de cuentas ni los controles del ejecutor; la nueva
interfaz invoca el mecanismo existente solo por una acción explícita del usuario
y después de una lectura verificada reciente. Los mensajes de errores no exponen
respuestas privadas. Una autorización vencida necesita renovarse; conservar una
selección no sustituye ese requisito del broker.

Archivos: `real_account_panel.py`, `real_preparation_panel.py` y
`tests/test_real_account_panel.py`. Validación focal: 40 pruebas aprobadas,
incluidas selección explícita, navegación de ida/vuelta, consulta de 15 minutos
de antigüedad, actualización con el mismo botón, identidad incorrecta y rechazo
del registro. Ninguna prueba usó credenciales o envió órdenes reales.

El estado efectivo de carga se registra en CURRENT_CONTEXT y el diario. La
evidencia de validación/despliegue queda en el directorio privado de revisión.
