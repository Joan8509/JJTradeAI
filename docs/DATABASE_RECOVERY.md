# Recuperación de SQLite

## Reglas de seguridad

1. Detener el scanner y Streamlit antes de restaurar.
2. Conservar juntos el `.db` y su manifiesto `.json`.
3. Verificar primero la copia con `database_backup.py --verify`.
4. Restaurar preferentemente a un nombre nuevo y comprobar la aplicación.
5. Usar `--overwrite` únicamente después de esa comprobación.

La restauración valida `quick_check` y SHA-256 antes de copiar. Escribe a un
archivo parcial, vuelve a verificarlo y finalmente realiza un reemplazo
atómico. Si el destino existe, se rechaza por defecto. Con `--overwrite`, el
destino actual se respalda en `backups/pre_restore` antes de reemplazarlo.

No deben copiarse solamente archivos `-wal` o `-shm`. Las copias oficiales se
producen mediante la API online de SQLite y son bases autocontenidas.

## Evidencia visual

Cada arranque normal crea, junto al `.db`, un paquete `.visual.zip`. El paquete
se construye leyendo el snapshot SQLite, por lo que contiene exactamente las
capturas referidas por esa copia. Antes de cerrarlo verifica SHA-256 y tamano de
cada imagen.

Para verificarlo contra la huella del backup SQLite:

```powershell
$manifest = Get-Content exports\backups\market_data_FECHA.json | ConvertFrom-Json
.\venv\Scripts\python.exe visual_evidence_backup.py `
  --verify exports\backups\market_data_FECHA.visual.zip `
  --database-sha256 $manifest.sha256
```

Para restaurar las capturas en un directorio nuevo:

```powershell
.\venv\Scripts\python.exe visual_evidence_backup.py `
  --restore exports\backups\market_data_FECHA.visual.zip `
  --visual-directory exports\visual_evidence_restored `
  --database-sha256 $manifest.sha256
```

La restauracion no sobrescribe archivos diferentes. Si ya existe un archivo
con el mismo SHA-256, lo conserva de forma idempotente; cualquier conflicto
bloquea el proceso.

## Validación posterior

- ejecutar el preflight local;
- abrir Streamlit y revisar alertas, resultados y acuses;
- comprobar `PRAGMA quick_check` mediante `--verify`;
- iniciar el scanner en PAPER;
- confirmar calendario, heartbeat y reconciliación WebSocket–REST.
