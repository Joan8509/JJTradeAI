"""Allowlisted public sources; verified local baseline, isolated apply/recovery."""
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import zipfile

ROOT=Path(__file__).resolve().parents[1]
GIT=Path('C:/Users/Administrator/AppData/Local/GitHubDesktop/app-3.6.7/resources/app/git/cmd/git.exe')
EXISTING=('schwab_simulation.py','option_exit_plan.py','manual_execution.py','position_monitor.py',
    'trade_close_reporting.py','telegram_manual.py','web/telegram_manual/app.js',
    'manual_execution_panel.py','manual_trade_panel.py','scripts/check_telegram_manual_readiness.py',
    'tests/test_manual_quantity_panel.py','scripts/test_telegram_manual_browser.py',
    'tests/telegram_manual_browser_harness.js')
NEW=('manual_practice_report.py','tests/test_manual_practice.py',
    'scripts/enable_connected_manual_practice.py','scripts/publish_connected_manual.ps1',
    'scripts/reload_connected_manual.ps1','scripts/audit_connected_manual.py',
    'scripts/package_connected_manual.py','docs/CONNECTED_MANUAL_TRIAL_2026-10-18.md')
DEPENDENCIES=('manual_trade_service.py','option_position_sizing.py','schwab_contracts.py','schwab_connection.py',
    'option_contract_selection.py','telegram_manual_runtime.py','telegram_manual_http.py',
    'telegram_manual_bot.py','telegram_manual_controls.py','trade_close_notifications.py',
    'vps_private_runtime.py','bollinger_phone_worker.py','bollinger_tick_stream.py',
    'config/option_exit_policy.json','tests/test_manual_execution.py','tests/test_manual_trade_service.py',
    'tests/test_schwab_simulation.py','tests/test_telegram_manual.py')


def sha(data):return hashlib.sha256(data).hexdigest()


def main():
    pointer=ROOT/'exports/backups/connected_manual_current.json'
    stage=Path(json.loads(pointer.read_text())['directory']);baseline={}
    for archive in ('before.zip','additional_before.zip','browser.before.zip',
                    'recovered_before.zip','readiness_original_before.zip'):
        with zipfile.ZipFile(stage/archive) as z:
            if z.testzip() is not None:raise ValueError('BASELINE_CRC_FAILURE')
            baseline.update({n:z.read(n) for n in z.namelist()})
    patch=b''
    with tempfile.TemporaryDirectory(prefix='jjtrade_connected_patch_') as directory:
        folder=Path(directory)
        for name in EXISTING:
            for side,data in (('before',baseline[name]),('after',(ROOT/name).read_bytes())):
                p=folder/side/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
            r=subprocess.run([str(GIT),'-c','core.autocrlf=false','diff','--no-index','--binary','--',
                'before/'+name,'after/'+name],cwd=folder,capture_output=True)
            if r.returncode not in (0,1):raise ValueError('DIFF_FAILURE')
            patch+=r.stdout.replace(b'a/before/',b'a/').replace(b'b/after/',b'b/')
        patch_path=stage/'connected_manual.patch';patch_path.write_bytes(patch)
        target=folder/'verify';target.mkdir()
        for name in EXISTING:
            p=target/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(baseline[name])
        for flags in (['--check'],[]):
            subprocess.run([str(GIT),'-c','core.autocrlf=false','apply',*flags,str(patch_path)],
                cwd=target,check=True,capture_output=True)
        if any((target/n).read_bytes()!=(ROOT/n).read_bytes() for n in EXISTING):raise ValueError('FORWARD_MISMATCH')
        subprocess.run([str(GIT),'-c','core.autocrlf=false','apply','--reverse',str(patch_path)],
            cwd=target,check=True,capture_output=True)
        if any((target/n).read_bytes()!=baseline[n] for n in EXISTING):raise ValueError('RECOVERY_MISMATCH')
    readme='''# Ensayo manual conectado — paquete incremental PC

Baseline: fuentes LOCAL VPS anteriores a este bloque, NO HEAD Git ni la PC.
Conservar diferencias PC y sus escritores detenidos. No sobrescribir el proyecto.
No ejecutar scripts de activación/publicación/recarga en PC por recibir este ZIP.

1. Verificar manifest.json y sus hashes de archivos/dependencias. Usar los paquetes
   anteriores para conciliar dependencias; este ZIP no sustituye toda la instalación.
2. Comparar existing_before_sha256 con archivos PC. Si difieren, conciliar sobre
   copia aislada; no forzar el parche. Ticket y readiness recuperan bytes de
   paquetes anteriores con SHA conocidos y comparación exacta de texto al revertir
   únicamente este cambio. Resto: respaldos previos locales del bloque.
3. En copia compatible: git -c core.autocrlf=false apply --check connected_manual.patch.
   Revisar y aplicar el parche; incorporar solo NUEVOS archivos desde sources/
   cuando aún no existan, conservando cualquier trabajo local.
4. Probar tests.test_manual_practice, tests.test_schwab_simulation,
   tests.test_manual_execution, tests.test_option_exit_plan,
   tests.test_trade_close_notifications, tests.test_telegram_manual,
   tests.test_telegram_manual_runtime y tests.test_manual_quantity_panel.
   Los demás módulos de validación están en el documento de continuidad.
5. Recuperación del parche: git -c core.autocrlf=false apply --reverse
   connected_manual.patch, SOLO en copia compatible sin cambios posteriores.
   Nuevos archivos se revisan aparte. Forward/reverse byte exacto se probó en TEMP.

No incluye secretos, vault DPAPI, certificados, bases, cotizaciones, operaciones,
URLs privadas ni recibos. Fuentes y pruebas no activan la PC. La VPS mantiene
el ensayo local, con compra exclusivamente manual y órdenes reales bloqueadas.
No es paperMoney ni un circuito real de envío de órdenes Schwab.
'''
    files={'sources/'+n:(ROOT/n).read_bytes() for n in (*EXISTING,*NEW)}
    files.update({'connected_manual.patch':patch,'README_PC.md':readme.encode('utf-8')})
    manifest=dict(format=1,baseline='LOCAL_VPS_BEFORE_CONNECTED_MANUAL_BLOCK',
        existing_before_sha256={n:sha(baseline[n]) for n in EXISTING},new=list(NEW),
        dependency_sha256={n:sha((ROOT/n).read_bytes()) for n in DEPENDENCIES},
        files={n:dict(sha256=sha(v),bytes=len(v)) for n,v in files.items()},
        forward_recovery_byte_exact=True,contains_private_data=False)
    files['manifest.json']=json.dumps(manifest,indent=2).encode()
    output=stage/'connected_manual_sources.zip'
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as z:
        for n,v in files.items():z.writestr(n,v)
    with zipfile.ZipFile(output) as z:
        if z.testzip() is not None:raise ValueError('PACKAGE_CRC_FAILURE')
        for n,entry in manifest['files'].items():
            if sha(z.read(n))!=entry['sha256']:raise ValueError('PACKAGE_SHA_FAILURE')
    result=dict(directory=str(stage),zip=str(output),sha256=sha(output.read_bytes()),
        bytes=output.stat().st_size,entries=len(files),existing=len(EXISTING),new=len(NEW),
        crc_sha_verified=True,forward_recovery_byte_exact=True)
    pointer.write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result))


if __name__=='__main__':main()
