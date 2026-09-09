# # JJTrade AI
## Investep Trading Engine

### Objetivo

Analizar oportunidades de opciones utilizando la metodología Investep.

### Resultado posible

- CALL
- PUT
- NO OPERAR

### Temporalidades obligatorias

- 15m
- 1H
- Diario

### Principio fundamental

La aplicación nunca debe tomar una decisión usando una sola estrategia.

Toda decisión debe considerar:

- Contexto general
- Temporalidades
- Volatilidad
- Confirmaciones
- Invalidaciones

### Estrategias registradas

1. Expuesto en Bollinger
2. Disipadores
3. Punto Medio
4. Volatilidad
5. Panorama General
6. Confirmaciones
7. Invalidaciones

### Aprendizaje

Cada operación debe almacenarse para generar estadísticas de efectividad.Motor Investep

<!--
Este documento describe el propósito y los límites arquitectónicos del motor
Investep. La implementación actual se limita al análisis Expuesto en Bollinger.
-->

## Propósito

El motor Investep será el componente central de análisis de JJTrade AI. Su
responsabilidad será coordinar datos e indicadores conforme se formalice la
metodología.

## Responsabilidades previstas

- Recibir información previamente cargada y validada.
- Coordinar los componentes analíticos de la metodología Investep.
- Producir resultados estructurados para la aplicación y el diario.
- Mantener una separación clara entre análisis, presentación y persistencia.

## Arquitectura del motor

El motor Investep se divide en 3 niveles:

### 1. Detectores

Los detectores solo identifican estrategias o condiciones. No emiten `CALL` ni
`PUT` final.

Ejemplo:

- `EXPUESTO_BOLLINGER_INFERIOR`
- `EXPUESTO_BOLLINGER_SUPERIOR`

### 2. Registro de estrategias

Todas las estrategias deben existir en `strategy_registry.py`. Ninguna
estrategia puede usarse si no está registrada.

### 3. Agregador

`detect_strategies()` acumula:

- `estrategias_detectadas`
- `sesgos_detectados`
- `pendientes_confirmacion`
- `analisis`

La decisión final se construirá después, usando confirmaciones, invalidaciones,
panorama y riesgo.

Regla crítica: el motor nunca debe convertir una estrategia detectada en una
entrada directa.

## Alcance implementado

- Carga y normalización de archivos TXT/CSV exportados desde TC2000.
- Cálculo de las bandas media, superior e inferior de Bollinger.
- Detección de exposición inferior o superior en la última vela.
- Generación de un sesgo inicial sujeto a confirmación, sin emitir una señal
  final automática.

## Regla crítica: Expuesto en Bollinger

Expuesto en Bollinger es una estrategia detectora, no una señal final
automática.

Si el precio cierra por debajo de la banda inferior:

- Detectar `EXPUESTO_BOLLINGER_INFERIOR`.
- Sesgo inicial: `CALL_REBOTE`.
- Señal: `PENDIENTE_CONFIRMACION`.

Si el precio cierra por encima de la banda superior:

- Detectar `EXPUESTO_BOLLINGER_SUPERIOR`.
- Sesgo inicial: `PUT_RETROCESO`.
- Señal: `PENDIENTE_CONFIRMACION`.

Importante: la app nunca debe convertir Expuesto en Bollinger directamente en
un `CALL` o `PUT` final sin revisar confirmaciones, invalidaciones, panorama y
riesgo.

Una exposición en 15 minutos tampoco implica necesariamente retroceso. Si Hora
o Diario mantienen volatilidad, dirección y espacio, el precio puede continuar
en la misma dirección. La evaluación multitemporal es obligatoria.

## Fuera del alcance actual

No se implementan otras señales, reglas de entrada o salida, gestión de
posiciones ni estrategias de trading.

## Módulos relacionados

- `data_loader.py`: acceso y preparación de datos.
- `indicators.py`: cálculos de indicadores.
- `investep_engine.py`: coordinación del análisis Investep.
- `journal.py`: registro y seguimiento.
- `app.py`: punto de entrada de la aplicación.
