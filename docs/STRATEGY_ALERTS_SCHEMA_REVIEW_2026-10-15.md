# Diagnostico strategy_alerts — 15/10/2026 08:15 ET

Comparadas mediante sqlite3 URI mode=ro y transacciones de lectura:
- PC: exports/backups/carpeta incoming_pc/backups/vps_stage_20261014_final_preliminary/market_data.db
- VPS: exports/market_data.db

La PC original no se consulto en vivo: PC significa el snapshot transferido.
No se instanciaron repositorios que ejecuten _initialize ni se escribio SQL.

## Resultado

Diferencia solo de orden de columnas y formato del CREATE TABLE registrado.
Las 14 definiciones por nombre (tipo, NOT NULL, DEFAULT, PK y hidden) coinciden
exactamente al excluir cid. Campos 0–9 coinciden; ultimos cuatro:

| Columna | Posicion PC (cid) | Posicion VPS (cid) | Definicion comun |
| --- | --- | --- | --- |
| payload_json | 10 | 13 | TEXT NOT NULL, sin DEFAULT |
| event_type | 11 | 10 | TEXT NOT NULL DEFAULT 'LEGACY' |
| event_priority | 12 | 11 | TEXT NOT NULL DEFAULT 'INFO' |
| requires_ack | 13 | 12 | INTEGER NOT NULL DEFAULT 1 |

Ambas: id INTEGER PRIMARY KEY AUTOINCREMENT; UNIQUE(provider,feed,symbol,
trigger_timestamp). Sin CHECK adicionales, COLLATE especiales ni triggers.
Ambas son tablas rowid, no STRICT y con 14 columnas. Unico indice de tabla:
sqlite_autoindex_strategy_alerts_1, UNIQUE no parcial, origen u; columnas
provider/feed/symbol/trigger_timestamp, ASC y BINARY, iguales en ambas.

strategy_alerts no declara claves foraneas en ninguna. Ambas reciben las
mismas referencias alert_id -> id desde alert_human_reviews,
alert_governance_reviews, alert_outcomes y alert_acknowledgements, con
NO ACTION en actualizacion/borrado y MATCH NONE. PC ademas recibe referencias
de alert_visual_evidence y paper_signal_evaluations, tablas ausentes en VPS.
Eso es diferencia de tablas presentes, no cambio de restricciones de
strategy_alerts. No se ejecuto auditoria global de referencias entrantes.

PC:6860 filas; VPS:0. En PC todas las filas tienen event_type/event_priority
almacenados como text y requires_ack como integer, sin NULL ni requires_ack
fuera de 0/1. VPS sin filas: no puede acreditar datos equivalentes, solo esquema.

## Codigo revisado

live_strategy_service.py:85 crea campos nuevos antes de payload_json.
Lineas177–184 agregan campos ausentes con ALTER TABLE y los mismos DEFAULT;
esto explica columnas nuevas despues de payload_json en PC. No se ejecuto.
Linea245: unica insercion de produccion localizada en strategy_alerts,
INSERT OR IGNORE con nombres explicitos para las 13 columnas distintas de id.
Linea74 configura sqlite3.Row; lecturas SELECT */a.* en273/317 convierten a
dict(row) y leen payload_json por nombre. Son compatibles con ambos ordenes.
Busquedas de strategy_alerts en Python incluyeron archivos ignorados y
excluyeron venv/exports. Inserciones sin lista de columnas solo encontradas en
fixtures de tests/test_worden_review.py y tests/test_strategy_research.py,
que crean sus propios esquemas simplificados.

## Implicacion

El hash de SQL textual difiere sin incompatibilidad semantica de esta tabla
para el codigo revisado. No hace falta reordenar columnas. Una futura copia
por INSERT INTO ... SELECT * entre estos esquemas SI seria posicional y podria
mezclar payload_json/event_type/event_priority/requires_ack: emplear nombres
explicitos en cualquier mezcla futura. No se implemento mezcla/restauracion.
Esto no valida toda la migracion: falta corte coordinado y snapshot final.

Validacion realizada: sqlite_master SQL, table_xinfo, table_list, index_list,
index_xinfo, foreign_key_list de todas las tablas para referencias entrantes,
triggers y consultas agregadas sin exponer filas privadas. Comparacion por
nombre devolvio True; foreign_key_check(strategy_alerts) vacio, que no prueba
integridad de referencias entrantes (la tabla no tiene FK salientes).
No suite: revision SQL/codigo solo lectura. Sin cambios de bases, colector,
servicios, avisos, ordenes, commit o publicacion.
