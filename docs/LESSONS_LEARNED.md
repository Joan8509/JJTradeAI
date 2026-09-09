# Lecciones aprendidas

Este documento registra errores, correcciones y aprendizajes descubiertos
durante el desarrollo de JJTrade AI.

## Lección 001

**Título:** Expuesto en Bollinger no es una señal final

**Problema detectado:**

El sistema inicialmente interpretó que un precio expuesto fuera de Bollinger
implicaba automáticamente `CALL` o `PUT`.

**Corrección:**

Expuesto en Bollinger solamente detecta una posible oportunidad. Debe pasar
por:

- Confirmaciones
- Invalidaciones
- Panorama
- Riesgo

antes de emitir una decisión.

**Caso real:** SPY

**Resultado:**

Se modificó la arquitectura para separar:

```text
Detector
→ Confirmación
→ Motor de decisión
```

**Importancia:** Crítica

**Fecha:** 24 de junio de 2026
