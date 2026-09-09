# Confirmaciones

Estado: IMPLEMENTADA COMO CONTRATO DEL PIPELINE  
Categoría: CONFIRMACION  
Prioridad: ALTA  
Fuente: Metodología Investep enviada por Joan  

Cada detector devuelve criterios obligatorios y adicionales con estado
`CUMPLE`, `NO_CUMPLE`, `NO_DISPONIBLE` o `REQUIERE_REVISION`.

Una estrategia solo se confirma cuando fue detectada y todos sus requisitos
obligatorios están en `CUMPLE`. Los criterios externos se solicitan como `SÍ`,
`NO` o `PENDIENTE`; pendiente nunca equivale a confirmación.

Varias confirmaciones no compensan un requisito obligatorio fallido. El motor
no usa votación ni suma de puntos para ocultar una invalidación.
