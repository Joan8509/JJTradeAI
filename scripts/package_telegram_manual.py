"""Allowlisted source-only patch against this block's preserved local baseline."""
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import zipfile

ROOT=Path(__file__).resolve().parents[1]
GIT=Path('C:/Users/Administrator/AppData/Local/GitHubDesktop/app-3.6.7/resources/app/git/cmd/git.exe')
EXISTING=('bollinger_phone_worker.py','telegram_alerts.py','vps_private_runtime.py',
          'manual_execution_panel.py','tests/test_telegram_alerts.py')
NEW=('telegram_manual.py','telegram_manual_bot.py','telegram_manual_controls.py',
     'telegram_manual_http.py','telegram_manual_runtime.py','web/telegram_manual/index.html',
     'web/telegram_manual/style.css','web/telegram_manual/app.js',
     'scripts/check_telegram_manual_readiness.py','scripts/test_telegram_manual_browser.py',
     'scripts/package_telegram_manual.py','tests/test_telegram_manual.py',
     'tests/test_telegram_manual_runtime.py','tests/telegram_manual_browser_harness.js',
     'docs/TELEGRAM_EXECUTE_2026-10-18.md')
DEPENDENCIES=('manual_execution.py','manual_trade_service.py','schwab_simulation.py',
              'schwab_connection.py','option_contract_selection.py','option_position_sizing.py',
              'option_exit_plan.py','position_monitor.py','manual_trade_links.py')


def sha(data):return hashlib.sha256(data).hexdigest()


def main():
    stage=ROOT/json.loads((ROOT/'exports/backups/telegram_execute_current.json').read_text())['directory']
    baseline={}
    for archive in ('before.zip','additional_before.zip'):
        with zipfile.ZipFile(stage/archive) as z:
            for name in z.namelist():baseline[name]=z.read(name)
    patch=b''
    with tempfile.TemporaryDirectory(prefix='jjtrade_telegram_patch_') as directory:
        folder=Path(directory)
        for name in EXISTING:
            for side,data in (('before',baseline[name]),('after',(ROOT/name).read_bytes())):
                file=folder/side/name;file.parent.mkdir(parents=True,exist_ok=True);file.write_bytes(data)
            diff=subprocess.run([str(GIT),'-c','core.autocrlf=false','diff','--no-index','--binary','--',
                'before/'+name,'after/'+name],cwd=folder,capture_output=True)
            if diff.returncode not in (0,1):raise RuntimeError('DIFF_FAILED')
            patch+=diff.stdout.replace(b'a/before/',b'a/').replace(b'b/after/',b'b/')
        (stage/'telegram_manual.patch').write_bytes(patch)
        target=folder/'verify';target.mkdir()
        for name in EXISTING:
            file=target/name;file.parent.mkdir(parents=True,exist_ok=True);file.write_bytes(baseline[name])
        for flags in (['--check'],[]):
            subprocess.run([str(GIT),'-c','core.autocrlf=false','apply',*flags,str(stage/'telegram_manual.patch')],
                cwd=target,check=True,capture_output=True)
        if any((target/n).read_bytes()!=(ROOT/n).read_bytes() for n in EXISTING):raise RuntimeError('FORWARD_BYTES_MISMATCH')
        subprocess.run([str(GIT),'-c','core.autocrlf=false','apply','--reverse',str(stage/'telegram_manual.patch')],
            cwd=target,check=True,capture_output=True)
        if any((target/n).read_bytes()!=baseline[n] for n in EXISTING):raise RuntimeError('RECOVERY_BYTES_MISMATCH')
    readme='''# Fuentes Telegram/Mini App — simulación, no activación

Baseline: árbol LOCAL VPS al comenzar este bloque el18/10, incluye cambios
anteriores no confirmados. NO es HEAD Git ni la copia PC. No aplicar a ciegas.
Conservar la instalación PC, mantener sus escritores detenidos y revisar AGENTS.

1. Revisar manifiesto SHA y dependencias. Se necesitan las ampliaciones manuales
   y visuales anteriores; no se incluyen aquí como sustitución completa del repo.
2. Comparar cinco archivos existentes con existing.before_sha256. Si no coinciden,
   conciliar manualmente conservando ambos cambios; no forzar el parche.
3. Sobre copia aislada, git -c core.autocrlf=false apply --check telegram_manual.patch.
   Revisar y aplicar solo sobre baseline compatible. Fuentes en sources/ son para
   comparar y copiar únicamente los NUEVOS archivos cuando no existan en PC.
4. Pruebas: venv\\Scripts\\python.exe -m unittest tests.test_telegram_manual
   tests.test_telegram_manual_runtime tests.test_manual_execution -v (una línea).
   El ensayo Edge opcional usa solo fetch/SDK ficticios y perfil temporal.
5. No copiar configuración DPAPI, bases ni recibos; no habilitar el opt-in,
   colectores, radar, tareas, mensajes ni órdenes reales en la PC.

La VPS sigue siendo la instalación operativa. El nuevo acompañante está
DESHABILITADO: faltan política de simulación aprobada, costos, ticks y prueba
HTTPS/Telegram/iPhone en sesión regular. Leer el documento de implementación.
La comprobación del parche se hizo forward y reverse en TEMP y byte a byte;
el paquete no se aplicó a la PC ni demuestra ejecución real o paperMoney API.
'''
    (stage/'README_PC.md').write_text(readme,encoding='utf-8')
    files={}
    for name in (*EXISTING,*NEW):
        data=(ROOT/name).read_bytes();files['sources/'+name]=data
    for name in ('telegram_manual.patch','README_PC.md','validation.txt','final_validation.json'):
        files[name]=(stage/name).read_bytes()
    manifest=dict(created_utc=datetime.now(timezone.utc).isoformat(),
        baseline='LOCAL_VPS_BEFORE_THIS_BLOCK_NOT_GIT_HEAD_OR_PC',real_orders_enabled=False,
        forward_byte_exact=True,recovery_byte_exact=True,
        existing={n:dict(before_sha256=sha(baseline[n]),after_sha256=sha((ROOT/n).read_bytes())) for n in EXISTING},
        new=list(NEW),dependencies={n:sha((ROOT/n).read_bytes()) for n in DEPENDENCIES},
        files={n:dict(sha256=sha(data),bytes=len(data)) for n,data in files.items()})
    archive=stage/'telegram_manual_sources.zip'
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
        for name,data in files.items():z.writestr(name,data)
        z.writestr('manifest.json',json.dumps(manifest,indent=2))
    with zipfile.ZipFile(archive) as z:
        if z.testzip() is not None:raise RuntimeError('ZIP_CRC_FAILED')
        for name,meta in manifest['files'].items():
            if sha(z.read(name))!=meta['sha256']:raise RuntimeError('ZIP_SHA_FAILED')
    receipt=dict(archive=str(archive.relative_to(ROOT)),bytes=archive.stat().st_size,sha256=sha(archive.read_bytes()),
        files=len(files),zip_crc=True,manifest_sha=True,forward_byte_exact=True,recovery_byte_exact=True)
    (stage/'package_result.json').write_text(json.dumps(receipt,indent=2))
    print(json.dumps(receipt))


if __name__=='__main__':main()
