# Contrato estricto de deteccion de estrategias

## Regla principal

JJTrade AI solo publica una estrategia con `detected=true` cuando todos sus
criterios marcados como obligatorios tienen estado `CUMPLE`.

Una semejanza parcial conserva sus criterios y su direccion para auditoria,
pero no puede presentarse como una estrategia valida, generar una alerta de
setup ni avanzar hacia una decision operativa.

Los estados `NO_CUMPLE`, `NO_DISPONIBLE` y `REQUIERE_REVISION` bloquean la
deteccion cuando pertenecen a un criterio obligatorio. Las confirmaciones
marcadas expresamente como adicionales permanecen separadas.

## Detectores cubiertos

- Cambio de Tendencia en 15 minutos.
- Primer Salto Respetado.
- Salto de Lateralidad en Hora.
- Cambio de Tendencia en Hora.
- Momentum.
- Retorno a Bollinger desde Lateralidad.
- Rebote en Punto Medio Diario.
- Efecto Iman.

`Expuesto en Bollinger` es una condicion elemental de precio, no una entrada:
puede reconocer objetivamente la exposicion, pero conserva una confirmacion
posterior obligatoria y nunca autoriza por si sola una operacion.

## Trazabilidad

Los registros historicos no se reescriben. Cada alerta conserva la version de
metodologia, los criterios y los valores utilizados al emitirse. Los cambios de
este contrato se aplican a evaluaciones nuevas.

