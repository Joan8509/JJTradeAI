# GitHub private publish checklist

Este proyecto debe subirse a GitHub como repositorio privado.

## Antes del primer commit

1. Confirmar identidad local de Git:

```powershell
git config user.name "TU NOMBRE"
git config user.email "TU EMAIL"
```

Puedes auditar todo el estado local con:

```powershell
.\venv\Scripts\python.exe github_readiness.py
```

Ese comando muestra los items pendientes y la accion sugerida para cada uno.
Usa `--json` o `--output exports\github_readiness.json` si necesitas conservar
la revision en formato estructurado.

Estados posibles:

- `OK`: identidad, rama, commit, remoto y candidatos estan listos.
- `PENDIENTE`: faltan pasos operativos como identidad Git, rama `main`, commit
  inicial o remoto privado.
- `BLOQUEADO`: hay candidatos inseguros para publicar, por ejemplo secretos,
  credenciales, bases locales o exports reales no permitidos.

2. Revisar archivos que entraran al commit:

```powershell
git status --short
git ls-files --others --exclude-standard
.\venv\Scripts\python.exe prepublish_check.py
.\venv\Scripts\python.exe prepublish_check.py --manifest exports\prepublish_manifest.csv
```

3. Confirmar que no entran artefactos operativos:

- `exports/jjtrade_journal.db`
- `exports/tc2000_cases/*.txt`
- `exports/tc2000_cases/case_intake*.csv`
- `exports/tc2000_cases/package_inventory.csv`
- `exports/validation_batch/`
- `exports/beta_*/`
- reportes reales `exports/validation_*.json`
- logs `.streamlit/*.log`
- credenciales, `.env`, llaves o tokens

`exports/sample.txt` puede quedar versionado porque se usa como fixture de
pruebas.

El manifiesto `exports\prepublish_manifest.csv` es solo evidencia local de
revision; no debe subirse al repositorio.
El guardia compara rutas sin depender de mayusculas/minusculas para evitar
variantes como `.ENV` o nombres con `TOKEN`.
Tambien bloquea `.env` y credenciales aunque aparezcan dentro de subcarpetas.

## Commit inicial

```powershell
git add .
git status --short
git commit -m "Initial JJTrade AI beta"
```

## Crear repo privado

Crear un repositorio privado en GitHub. Luego conectar el remoto:

```powershell
git remote add origin https://github.com/TU_USUARIO/NOMBRE_REPO.git
git branch -M main
git push -u origin main
```

`github_readiness.py` marca la rama como pendiente hasta que sea `main`.

## Regla de seguridad

No subir datos reales de trading, diario local, exports de TC2000, credenciales
ni artefactos de validacion con informacion privada. Los artefactos de salida
pueden regenerarse localmente con:

```powershell
.\venv\Scripts\python.exe validation_batch.py `
  --input-dir exports\tc2000_cases `
  --preflight-output-dir exports\tc2000_cases `
  --run-after-preflight `
  --output-dir exports\validation_batch `
  --standard-output-dir
```
