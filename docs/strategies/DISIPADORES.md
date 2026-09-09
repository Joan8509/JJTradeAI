# Disipadores

Estado: `EN_PROCESO` — componente documentado; estrategia independiente por confirmar  
Categoría: `DISIPADORES`  
Prioridad: `ALTA`  
Fuentes principales: `Bollinguer 1.txt` y `Bollinguer2.txt`

## Definición

Los disipadores son las bandas superior e inferior de Bollinger. Representan
los límites dinámicos utilizados para evaluar exposición y estado de
volatilidad.

## Funciones dentro del motor

- Determinar si el precio está dentro o fuera de Bollinger.
- Medir apertura, cierre y expansión de volatilidad.
- Actuar como primer objetivo de retorno para un precio expuesto.
- Ayudar a identificar cuándo un movimiento pierde fuerza.

## Regla crítica

Un disipador no genera una entrada por sí solo. El precio puede regresar al
disipador o continuar expuesto si la volatilidad permanece abierta.

## Pendiente

El corpus revisado define claramente el componente técnico, pero todavía debe
confirmarse si “Disipadores” posee una estrategia independiente adicional o si
es únicamente una herramienta utilizada por otras estrategias.

