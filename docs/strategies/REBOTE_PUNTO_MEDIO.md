# Rebote en Punto Medio

Estado: `IMPLEMENTADO_EN_BETA` — detector objetivo con respaldo manual para archivos  
Categoría: `PUNTO_MEDIO`  
Prioridad: `ALTA`  
Fuente principal: `Estrategias/Rebote en punto medio a la alza y baja.txt`  
Fuente: Metodología Investep enviada por Joan

## Objetivo

Detectar el rechazo del precio en el Punto Medio de Bollinger Diario y confirmar
la continuación de la tendencia diaria mediante una vela cerrada de Hora.

## Rebote alcista

Sesgo esperado: `CALL_REBOTE`.

1. Punto Medio de Bollinger claramente alcista en Diario.
2. Punto Medio de Bollinger claramente bajista en Hora, reflejando el
   acercamiento hacia el soporte diario.
3. Precio descendiendo durante varios días hacia el Punto Medio Diario.
4. Al alcanzar la referencia del Punto Medio Diario, el precio debe respetarla:
   no debe cruzarla y debe comenzar a rebotar en 15 minutos.
5. Esperar una vela de Hora cerrada alcista por encima del Punto Medio Diario.

La observación del rebote en 15 minutos no confirma por sí sola la estrategia.
La confirmación de Hora es obligatoria antes de considerar el sesgo.

## Rebote bajista

Sesgo esperado: `PUT_REBOTE`.

1. Punto Medio de Bollinger claramente bajista en Diario.
2. Punto Medio de Bollinger claramente alcista en Hora, reflejando el
   acercamiento hacia la resistencia diaria.
3. Precio ascendiendo durante varios días hacia el Punto Medio Diario.
4. Al alcanzar la referencia del Punto Medio Diario, el precio debe respetarla:
   no debe cruzarla y debe comenzar a rebotar en 15 minutos.
5. Esperar una vela de Hora cerrada bajista por debajo del Punto Medio Diario.

La observación del rebote en 15 minutos no confirma por sí sola la estrategia.
La confirmación de Hora es obligatoria antes de considerar el sesgo.

## Invalidaciones y condiciones de descarte

- Punto Medio Diario lateral o contrario a la tendencia requerida.
- Precio cruzando el Punto Medio Diario en lugar de respetarlo.
- Ausencia de una tendencia contraria clara en Hora durante el acercamiento.
- Ausencia de vela cerrada de Hora en la dirección del rebote.
- Vela de Hora de indecisión en lugar de confirmación direccional.

## Temporalidades

- Diario: tendencia principal y nivel de Punto Medio.
- Hora: tendencia de acercamiento y vela de confirmación.
- 15 minutos: observación inicial del respeto o rechazo del nivel.

## Consideraciones de opciones y riesgo

La clase indica que el movimiento puede tardar desde una vela hasta varios
días. Si la fecha de expiración está demasiado próxima —especialmente jueves o
viernes— se plantea evaluar la expiración siguiente. Esta consideración debe
permanecer en la capa de riesgo y no dentro del detector.

## Contrato técnico implementado

`strategies/rebote_punto_medio.py` mide la dirección de los Puntos Medios
Diario y de Hora, comprueba que una vela de 15m alcance el nivel Diario y
puede inferir rechazo del nivel cuando la vela de 15m contiene apertura y
cierre: alcista exige cierre sobre el Punto Medio Diario y bajista exige cierre
debajo. También valida la dirección de la vela de Hora. Alcanzar el nivel solo
genera un candidato; si faltan open/close de 15m, no demuestra que el precio lo
respetó.

La aproximación durante varios días se confirma objetivamente cuando los tres
últimos cierres diarios permanecen del lado correcto del Punto Medio y reducen
su distancia al nivel de forma consecutiva. El feed en vivo elimina barras en
formación, por lo que su última vela de Hora se considera cerrada. En archivos
manuales se conserva la confirmación explícita del cierre.

El respeto observado en 15m se infiere con `open/high/low/close`; solo permanece
como revisión cuando esos datos no permiten demostrarlo. Se registran
`REBOTE_PUNTO_MEDIO_ALCISTA` y `REBOTE_PUNTO_MEDIO_BAJISTA`.

## Pendientes antes de completar la automatización

- Definir matemáticamente cuándo un Punto Medio está claramente inclinado.
- Definir tolerancia para “tocar”, “respetar” y “cruzar” el Punto Medio; la
  implementación actual usa cierre estricto sin tolerancia.
- Definir objetivamente una vela de confirmación y una vela de indecisión.
- Formalizar vigencia máxima de la detección.
- Validar esta interpretación con Joan.

## Notas

Los porcentajes de rentabilidad mencionados en la capacitación son ejemplos
educativos y no forman parte del detector ni constituyen una promesa.
