"""Run only in an interactive Administrator console. No secret CLI options."""
from datetime import datetime, timezone
import getpass
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import vps_private_runtime as runtime


def restricted_directory():
    runtime.PRIVATE.mkdir(parents=True, exist_ok=True)
    sid = runtime.current_sid()
    if not sid.endswith('-500'):
        raise ValueError('Administrator required')
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
                             '-File', str(ROOT / 'scripts/restrict_vps_private.ps1')],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if result.returncode:
        raise ValueError('Private directory ACL failed')
    return sid


def setup():
    if os.name != 'nt' or not sys.stdin.isatty():
        raise ValueError('Interactive Windows console required')
    sid = restricted_directory()
    print('JJTrade VPS: ninguna entrada privada se mostrara ni se enviara a la red.')
    print('Las tareas de colector/radar quedaran DESHABILITADAS. No se modifica la base.')
    if runtime.VAULT.exists():
        config = runtime.load_config()
        print('Configuracion cifrada existente legible; se reutilizara.')
    else:
        config = {'format': 1, 'owner_sid': sid, 'feed': 'iex'}
        config['ALPACA_API_KEY'] = getpass.getpass('Alpaca API key (oculta): ')
        config['ALPACA_API_SECRET'] = getpass.getpass('Alpaca API secret (oculta): ')
        config['TELEGRAM_BOT_TOKEN'] = getpass.getpass('Token Telegram del bot actual (oculto): ')
        chats = runtime.historical_chats()
        config['TELEGRAM_CHAT_ID'] = getpass.getpass('Chat ID Telegram (oculto; Enter reutiliza el chat historico): ')
        if not config['TELEGRAM_CHAT_ID'] and len(chats) == 1:
            config['TELEGRAM_CHAT_ID'] = next(iter(chats))
        runtime.validate_config(config, sid)
        if chats != {config['TELEGRAM_CHAT_ID']}:
            raise ValueError('Historical chat mismatch')
        # The current workload used IEX; verify against recorded notice sources.
        # No token validation over HTTP is performed by setup.
        from telegram_alerts import _protect
        ciphertext = _protect(json.dumps(config).encode('utf-8'))
        temporary = runtime.VAULT.with_suffix('.dpapi.tmp')
        temporary.write_bytes(ciphertext)
        temporary.replace(runtime.VAULT)
        runtime.load_config()  # Confirm CurrentUser round-trip, still offline.
        print('Configuracion guardada mediante DPAPI CurrentUser y ACL privada.')
    print('Se necesita la contrasena de Windows de Administrator para registrar')
    print('tareas con inicio sin sesion RDP; la conserva Windows Task Scheduler.')
    password = getpass.getpass('Contrasena WINDOWS de Administrator (oculta): ')
    if not password:
        raise ValueError('Windows password required')
    probe_id = uuid.uuid4().hex
    # Password travels only in an anonymous pipe to the registration API process.
    # It is never an argument, environment variable, file or console output.
    payload = json.dumps({'password': password, 'probe_id': probe_id})
    del password
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive',
                             '-ExecutionPolicy', 'Bypass', '-File',
                             str(ROOT / 'scripts/register_vps_private_tasks.ps1')],
                            input=payload, text=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    del payload
    if result.returncode:
        raise ValueError('Task registration/probe failed')
    receipts = []
    for role in ('collector', 'radar'):
        receipt = json.loads((runtime.PRIVATE / (role + '.probe.json')).read_text(encoding='utf-8'))
        if receipt.get('probe_id') != probe_id or receipt.get('status') != 'LOCAL_ACCESS_OK' or receipt.get('session_id') != 0:
            raise ValueError('Batch task identity probe failed')
        receipts.append({'role': role, 'status': receipt['status'], 'session_id': receipt['session_id']})
    runtime.write_receipt('setup_status.json', {
        'status': 'CONFIGURED_TASKS_DISABLED', 'checked_utc': datetime.now(timezone.utc).isoformat(),
        'probe_id': probe_id, 'probes': receipts, 'network_used': False,
        'collector_started': False, 'radar_started': False, 'activation_allowed': False})
    print('OK: acceso DPAPI verificado bajo tareas Password en sesion0, sin red.')
    print('Colector, radar y tareas de verificacion DESHABILITADOS. Corte aun pendiente.')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(setup())
    except Exception:
        # Do not print exception arguments, local variables or tracebacks.
        try:
            runtime.write_receipt('setup_status.json', {'status': 'SETUP_INCOMPLETE',
                'checked_utc': datetime.now(timezone.utc).isoformat(), 'activation_allowed': False})
        except Exception:
            pass
        print('Configuracion incompleta. No se activo ningun colector/radar.')
        print('Revisa las entradas y vuelve a ejecutar esta consola; no pegues claves en el chat.')
        raise SystemExit(1)
