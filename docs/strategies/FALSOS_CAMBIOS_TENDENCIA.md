# Falsos Cambios de Tendencia

Estado: EN_PROCESO  
Categoría: INVALIDACION / CAMBIO_TENDENCIA  
Prioridad: ALTA  
Fuente: Metodología Investep enviada por Joan  

## Casos documentados

- CT15 con salto pero sin apertura de volatilidad.
- CT15 cuyo cierre anterior quedó al lado incorrecto del Punto Medio.
- CT15 alcista que amanece expuesto.
- Cambio en Hora cuya vela cruza y vuelve a cerrar sin confirmar.
- Salto en Hora que no rompe simultáneamente línea y Punto Medio y tampoco
  recibe confirmación cerrada posterior.
- Cambio aparente sin alineación de 15m o sin espacio en el panorama.

Estos casos producen criterios fallidos o invalidaciones; no crean una
estrategia contraria. No se agregarán falsos CT15 bajistas por simetría mientras
la fuente oficial no los defina.
