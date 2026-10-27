# Reparación de selección y aplicación de objetivos

Usuario26/10 señala fallo de objetivo o «Aplicar a todas». Reproducidos antes
de corregir con3regresiones fallidas: objetivo solo exigía contratos comunes,
compañía nueva no heredaba lo aplicado, y cambiar modo borraba la selección.

Botones separados «Aplicar solo objetivo» y «Aplicar solo contratos» preservan
el otro campo por compañía. Botón conjunto conserva aplicación de ambos;
si contratos comunes0 solo se aplica el objetivo, y si objetivo vacío solo
la cantidad. No se introducen cantidades/objetivos predeterminados de compra.

Borrador independiente de las claves de widgets conserva selección, ajustes
por compañía, valores comunes y sesión oficial durante navegación. Nuevas
compañías heredan últimos valores efectivamente aplicados; reelección conserva
ajustes propios. «Seleccionar todas con rango» y «Quitar selección» solo editan
el formulario, no modifican entradas ya guardadas. Filas incompletas visibles.

Conservar no implica armar: consentimiento se retira tras cambios y no se
restaura al volver de otra vista. GET fresco Schwab y lote transaccional
todo-o-nada siguen iguales. Estado incierto/claims no se despejan ni rearman.
El borrador dura la sesión del navegador; no prometer supervivencia a reinicio
del servidor. No cambia detector, cola, stop, avisos, dedup o realesOFF.

Solo automatic_entry_panel.py y pruebas cambiados; no recargar mercado.
Validación, fuente base y estado de carga se registran en contexto/diario;
artefactos privados en2026-10-26_bulk_selection_repair.
