# Matriz de validación metodológica

Este documento registra ambigüedades, excepciones y decisiones necesarias antes
de activar reglas automáticas.

| ID | Tema | Hallazgo | Tratamiento actual | Estado |
| --- | --- | --- | --- | --- |
| M-001 | Expuesto en 15m | Puede retroceder al disipador o continuar si Hora/Diario mantienen dirección, volatilidad y espacio. | Detector sin señal final; exigir panorama superior. | Resuelto arquitectónicamente |
| M-002 | Saliendo de Bollinger | Puede comenzar en Punto Medio, cerca del disipador o continuar expuesto con respaldo superior. | La variante documentada de lateralidad se registra como `RETORNO_BOLLINGER_LATERAL`; las variantes de continuidad permanecen separadas. | Resuelto para variante lateral |
| M-003 | Bollinger frente a medias | Bollinger puede anticipar un cambio antes del cruce de medias y tiene mayor peso metodológico. | Mostrar ambos; usar Bollinger como anticipación y medias como contexto. | Pendiente de pesos cuantitativos |
| M-004 | Lateralidad | Generalmente obliga a esperar, salvo estrategias específicas de salto fuera de Bollinger lateral. | `NO_OPERAR` por defecto; excepciones explícitas por estrategia. | Resuelto arquitectónicamente |
| M-005 | Rango óptimo de opciones | La academia usa tablas dinámicas y una fórmula no incluida en el corpus recibido. | Riesgo `NO_DISPONIBLE` sin configuración aprobada. | Falta fuente |
| M-006 | Tendencia y volatilidad | La metodología usa términos visuales como “claramente”, “muy abierto” o “muy alejado”. | Medir datos objetivos sin clasificar hasta fijar umbrales. | Pendiente de calibración |
| M-007 | Líneas de tendencia | Varias estrategias requieren trazado visual bordeando puntos. | Permitir entrada manual inicialmente; automatización posterior. | Pendiente de diseño |
| M-008 | Momentum | Las duraciones de corto, medio y largo plazo se expresan con rangos parcialmente superpuestos. | No activar duración automática hasta validar límites. | Pendiente de validación |
| M-009 | Noticias | “Noticia mata estrategia”, pero no se define universo ni ventana uniforme. | Compuerta `NO_DISPONIBLE` hasta integrar calendario y reglas. | Falta definición |
| M-010 | Confianza | Porcentajes educativos de las clases no equivalen a probabilidades calibradas. | Confianza `NO_CALIBRADA` hasta contar con historial propio. | Resuelto arquitectónicamente |
| M-011 | Paso de PAPER a real | La clase propone duplicar la cuenta simulada, pero no define muestra mínima, pérdida máxima ni consistencia estadística. | Nunca desbloquear automáticamente; exigir decisión humana y criterios aprobados. | Pendiente de validación |
| M-012 | Primer salto | La conducta cambia si se busca una entrada nueva o si ya existe una posición. Para entrada nueva se solicita confirmación de una vela de Hora cerrada. | Separar `NUEVA_ENTRADA` de `GESTION_POSICION`; no reutilizar una regla entre ambos flujos. | Resuelto arquitectónicamente |
| M-013 | Salto de lateralidad en Hora | La clase define 5 registros de tendencia, 10 de lateralidad, ruptura por salto o vela de Hora, cercanía a MA20, volatilidad y ausencia de noticias; no define ancho matemático del canal ni distancia máxima a MA20. | Detector parcial: mide tendencia y relación precio/MA20/MA40; lateralidad, ruptura, cercanía a MA20, volatilidad, noticias y camino libre quedan como revisiones manuales obligatorias. | Implementación parcial |
| M-014 | Cambio de tendencia por salto | Las imágenes permiten ruptura de línea mediante salto, pero también exigen una vela horaria direccional de confirmación. No establecen que el salto sustituya esa vela. | Mantener documentada la discrepancia; no ampliar autoridad del salto hasta validación de Joan. | Pendiente de validación |
| M-015 | Rebote y cruce de MA20 Diario | Las imágenes dicen que el precio debe tocar y no cruzar el Punto Medio. No aclaran si una mecha que atraviesa y cierra del lado correcto invalida el caso. | Mantener cierre del lado correcto y confirmación horaria; no imponer tolerancia ni prohibición de mecha sin decisión explícita. | Pendiente de validación |
| M-016 | Efecto Imán y Worden | Las imágenes confirman que la exposición inicial requiere una reacción posterior y cruce de la línea roja de Worden. Alpaca no entrega esa línea. | Conservar Worden como compuerta obligatoria `NO_DISPONIBLE`; nunca sustituirlo por volumen estándar. | Falta fuente de datos |
| M-017 | Lateral fuera de Bollinger | Las variantes CALL/PUT solo son vigentes durante los primeros cinco minutos y requieren preparación premarket. | El radar intravela oculta la estrategia después de 09:34 ET. Datos y umbrales premarket siguen pendientes. | Ventana resuelta; premarket pendiente |

## Regla de implementación

Una ambigüedad nunca se resuelve inventando un valor. Debe convertirse en
configuración aprobada, revisión manual o `NO_OPERAR`.
