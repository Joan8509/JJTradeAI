# Requisitos de producto de JJTrade AI

## Propósito

JJTrade AI será una herramienta local de análisis y decisión asistida basada en
la metodología Investep. Debe ayudar a identificar qué condiciones se cumplen
en un activo y explicar si el panorama respalda `CALL`, `PUT` o `NO OPERAR`.

No ejecutará órdenes ni prometerá resultados. Toda decisión debe poder ser
revisada por el usuario antes de operar.

## Principios obligatorios

- Mostrar evidencia, no solo una conclusión.
- Separar detectores, confirmaciones, invalidaciones, panorama y riesgo.
- Permitir `NO OPERAR` cuando falte calidad o exista conflicto.
- No convertir una estrategia individual en una entrada directa.
- Conservar la fuente metodológica y versión de cada regla.
- No programar criterios ambiguos sin validación.
- Registrar resultados sin permitir que el aprendizaje reescriba las reglas
  oficiales de manera automática.

## Entradas iniciales

- Archivos TXT/CSV exportados desde TC2000.
- Datos de 15 minutos, 1 hora y Diario cuando la regla los requiera.
- Símbolo y fecha del análisis.
- Datos de opciones y riesgo cuando se formalice esa fase.

La aplicación no debe presentar una decisión direccional completa cuando solo
se haya cargado una temporalidad para una regla multitemporal.

## Resultado por activo

La aplicación debe mostrar:

- Estrategias detectadas.
- Porcentaje de cumplimiento por estrategia.
- Criterios cumplidos, pendientes y fallidos.
- Confirmaciones e invalidaciones.
- Panorama multitemporal.
- Sesgos detectados y conflictos entre ellos.
- Riesgo y calidad de la oportunidad.
- Decisión asistida: `CALL`, `PUT` o `NO OPERAR`.
- Confianza explícita; permanece `NO_CALIBRADA` hasta contar con protocolo y
  muestra fuera de mercado aprobados.
- Fuentes de las reglas aplicadas.

## Vistas principales

### Por activo

Seleccionar una compañía y revisar todas sus estrategias, criterios y niveles
de cumplimiento.

### Por estrategia

Seleccionar una estrategia y ordenar los activos por porcentaje de
cumplimiento.

### Alertas

Mostrar únicamente oportunidades que alcancen el umbral definido, siempre como
alertas sujetas a verificación humana.

### Diario

Registrar operaciones aprovechadas o descartadas, resultado, contexto y versión
de la metodología utilizada.

## Aprendizaje controlado

La capa de aprendizaje podrá calcular estadísticas y calibrar confianza según
casos históricos comparables. No podrá modificar detectores, confirmaciones o
invalidaciones oficiales sin una nueva versión aprobada.

La implementación inicial separa PAPER y REAL, documenta excepciones humanas y
calcula métricas descriptivas con intervalos de incertidumbre. La confianza
permanece `NO_CALIBRADA` hasta disponer de un protocolo fuera de muestra
aprobado. Ver `docs/LEARNING_MODEL.md`.

## Gobierno operativo

- La aplicación inicia en modo `PAPER`; nunca activa capital real por defecto.
- El radar educativo inicial admite hasta tres símbolos.
- El límite educativo inicial es de tres operaciones nuevas por semana.
- Toda operación requiere un plan escrito de entrada y salida.
- Los flujos `NUEVA_ENTRADA`, `GESTION_POSICION` y `REFUERZO` deben permanecer
  separados.
- La aplicación no ejecuta órdenes ni desbloquea automáticamente la operativa
  real por rentabilidad simulada.
- Las estadísticas de simulación y capital real deben mantenerse separadas.

Los criterios para pasar de simulación a capital real requieren validación y
decisión humana. Ver `docs/RISK_GOVERNANCE.md`.

## Fuentes iniciales de estos requisitos

- `Explicacion de su app.txt`.
- `Resumen.txt`.
- Reglas arquitectónicas aprobadas durante el desarrollo de JJTrade AI.
