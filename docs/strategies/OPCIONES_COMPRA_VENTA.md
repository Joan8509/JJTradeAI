# Opciones: Compra, Venta y Riesgo de Ejecución

Estado: `EN_PROCESO` — faltan tablas de rangos y límites oficiales  
Categoría: `RIESGO`  
Prioridad: `ALTA`  
Fuentes principales: clase de CT15, Saltos, Rebote en Punto Medio y tips

## Objetivo

Impedir que una estrategia técnicamente válida se convierta en operación cuando
el contrato presenta mala liquidez, precio inadecuado, vencimiento insuficiente
o distancia excesiva respecto del activo.

## Datos obligatorios

- Símbolo del activo y precio spot.
- Tipo de contrato: `CALL` o `PUT`.
- Strike.
- Fecha de expiración.
- Bid y ask actualizados.
- Número de contratos.
- Capital y riesgo máximo permitido.
- Rango de precio admitido para el activo.
- Distancia spot/strike habitual o máxima admitida.

## Bid / Ask Spread

- Ask representa el precio de compra.
- Bid representa el precio disponible para vender.
- Un spread excesivo produce una pérdida inmediata y cancela la operación.
- Después de la apertura pueden aparecer cotizaciones temporalmente anormales;
  deben esperarse precios actualizados antes de evaluar.

La clase de CT15 menciona como referencia una diferencia máxima de 5 a 10 en
contratos cuyo costo supera 100, pero la unidad de cotización de la transcripción
es ambigua. Este valor no debe codificarse hasta validarlo con Joan.

## Distancia Spot / Strike

La distancia debe encontrarse dentro del rango normal del activo. Una distancia
anormal reduce la probabilidad de valorización aunque el movimiento del
subyacente sea correcto.

El material menciona un documento externo con rangos por compañía que todavía
no forma parte del corpus. Hasta recibirlo, esta compuerta será
`NO_DISPONIBLE`.

## Vencimiento

- Un contrato ya expirado se rechaza siempre, aun si faltan otros límites
  configurados.
- Estrategias que pueden tardar varios días requieren tiempo suficiente.
- Rebote en Punto Medio cerca de jueves o viernes puede requerir la expiración
  siguiente.
- Saltos confirmados jueves o viernes deben evaluar la semana siguiente debido
  al riesgo nocturno.
- La selección final depende de la estrategia y plan aprobado.

## Resultado de la compuerta

- `APROBADO`: todos los límites configurados se cumplen.
- `RECHAZADO`: spread, distancia, precio o vencimiento incumplen límites.
- `NO_DISPONIBLE`: falta una cotización o tabla obligatoria.
- `REQUIERE_REVISION`: existe información, pero el caso no es concluyente.

Los límites configurados deben ser cero o positivos; valores negativos se
tratan como configuración inválida, no como regla metodológica.

Cualquier resultado distinto de `APROBADO` obliga a `NO_OPERAR`.

## Pendientes antes de programar decisiones reales

- Tabla oficial de rangos de precio por activo.
- Límites de distancia spot/strike por activo.
- Unidad y máximo exacto del spread.
- Reglas de strike ITM, ATM y OTM por estrategia.
- Días mínimos al vencimiento por estrategia.
- Riesgo máximo por operación y exposición total.
- Reglas objetivas del plan de salida.
