"""Windows task entry point. DPAPI secrets stay in memory; activation is gated."""
from contextlib import closing, redirect_stderr, redirect_stdout
from datetime import datetime, timezone
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import re
import runpy
import sqlite3
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
PRIVATE = ROOT / 'exports' / 'private_runtime'
VAULT = PRIVATE / 'runtime.dpapi'
GATE = PRIVATE / 'cutover_authorized.json'
DATABASE = ROOT / 'exports' / 'market_data.db'
PC_SNAPSHOT = ROOT / 'exports/backups/carpeta incoming_pc/backups/vps_stage_20261014_final_preliminary/market_data.db'
FIELDS = ('ALPACA_API_KEY', 'ALPACA_API_SECRET', 'TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHAT_ID')


def current_sid():
    result = subprocess.check_output(['whoami.exe', '/user', '/fo', 'csv', '/nh'],
                                     creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    for row in csv.reader(io.StringIO(result.decode(errors='replace'))):
        if len(row) == 2 and re.fullmatch(r'S-1-[0-9-]+', row[1]):
            return row[1]
    raise ValueError('Identity unavailable')


def session_id():
    import ctypes
    value = ctypes.c_ulong()
    if not ctypes.windll.kernel32.ProcessIdToSessionId(os.getpid(), ctypes.byref(value)):
        raise ValueError('Session unavailable')
    return value.value


def historical_chats(database=PC_SNAPSHOT):
    # Never print or persist the private identifiers.
    with closing(sqlite3.connect(Path(database).resolve().as_uri() + '?mode=ro', uri=True)) as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='bollinger_phone_notifications'").fetchone():
            return set()
        chats = set()
        for (key,) in db.execute('SELECT event_key FROM bollinger_phone_notifications'):
            parts = key.split('|')
            if len(parts) != 7 or parts[0] != 'v1':
                raise ValueError('Historical notification key unsupported')
            chats.add(parts[1])
        return chats


def validate_config(config, sid):
    if config.get('format') != 1 or config.get('owner_sid') != sid or not sid.endswith('-500'):
        raise ValueError('Administrator identity mismatch')
    for name in FIELDS:
        value = config.get(name)
        if not isinstance(value, str) or not value or value.strip() != value or any(c in value for c in '\r\n\x00'):
            raise ValueError('Private configuration incomplete')
    if not re.fullmatch(r'\d+:[A-Za-z0-9_-]+', config['TELEGRAM_BOT_TOKEN']):
        raise ValueError('Private configuration invalid')
    if not re.fullmatch(r'-?\d+', config['TELEGRAM_CHAT_ID']):
        raise ValueError('Private configuration invalid')
    if config.get('feed') not in ('iex', 'sip'):
        raise ValueError('Feed invalid')
    return config


def load_config():
    from telegram_alerts import _protect
    config = json.loads(_protect(VAULT.read_bytes(), decrypt=True).decode('utf-8'))
    return validate_config(config, current_sid())


def write_receipt(name, data):
    path = PRIVATE / name
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, indent=2), encoding='utf-8')
    tmp.replace(path)


def check(role, probe_id):
    # This branch has no worker imports, environment injection or network API.
    result = {'role': role, 'probe_id': probe_id, 'checked_utc': datetime.now(timezone.utc).isoformat(),
              'status': 'BLOCKED', 'network_used': False, 'worker_started': False,
              'activation_authorized': False}
    try:
        config = load_config()
        chats = historical_chats()
        if not chats or chats != {config['TELEGRAM_CHAT_ID']}:
            raise ValueError('Historical chat mismatch')
        result.update(status='LOCAL_ACCESS_OK', identity_matches=True, dpapi_readable=True,
                      historical_chat_matches=True, session_id=session_id(),
                      vault_sha256=hashlib.sha256(VAULT.read_bytes()).hexdigest())
    except Exception:
        # Never expose decrypt errors, JSON content, identities or API values.
        result['status'] = 'LOCAL_ACCESS_BLOCKED'
    write_receipt(role + '.probe.json', result)
    return 0 if result['status'] == 'LOCAL_ACCESS_OK' else 2


def authorized(role, gate=GATE):
    try:
        data = json.loads(gate.read_text(encoding='utf-8'))
        return (data.get('pc_writers_stopped') is True and data.get('orders_enabled') is False
                and role in data.get('enabled_roles', [])
                and Path(data['database']).resolve() == DATABASE.resolve()
                and re.fullmatch(r'[a-f0-9]{64}', data.get('final_snapshot_sha256', '')) is not None)
    except (OSError, ValueError, KeyError, TypeError):
        return False


def worker_arguments(role):
    if role == 'collector':
        return [str(ROOT / 'live_strategy_service.py'), '--data-only', '--days', '30',
                '--database', str(DATABASE), '--lock-file', str(ROOT / 'exports/live_scanner.lock'),
                '--stop-file', str(ROOT / 'exports/live_scanner.stop')]
    return [str(ROOT / 'bollinger_phone_worker.py')]


def worker_environment(role, config, inherited=None):
    env = dict(os.environ if inherited is None else inherited)
    for key in tuple(env):
        if key.startswith(('ALPACA_', 'TELEGRAM_')):
            env.pop(key)
    names = FIELDS[:2] if role == 'collector' else FIELDS[2:]
    env.update({name: config[name] for name in names})
    env['ALPACA_DATA_FEED'] = config['feed']
    # The runtime gate is required before this environment is ever installed.
    if role == 'radar':
        env['TELEGRAM_ALERTS_ENABLED'] = 'true'
    return env


class DiscardedWorkerOutput:
    """Raw third-party output is never persisted; health is recorded separately."""
    encoding = 'utf-8'

    def isatty(self):
        return False

    def write(self, value):
        return len(value)

    def flush(self):
        pass


def run_worker(role):
    # Check activation BEFORE touching SQLite, loading secrets or any worker code.
    if not authorized(role):
        return 5
    from process_scheduling import normalize_service_priority
    scheduling = normalize_service_priority()
    write_receipt(role + '.scheduling.json', scheduling)
    config = load_config()
    # The task is IgnoreNew; also exclude simultaneous manual invocation.
    import msvcrt
    with (PRIVATE / (role + '.supervisor.lock')).open('a+b') as lock:
        lock.seek(0)
        lock.write(b'0')
        lock.flush()
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            return 6
        os.chdir(ROOT)
        os.environ.clear()
        os.environ.update(worker_environment(role, config, inherited=_BASE_ENVIRONMENT))
        sys.argv = worker_arguments(role)
        stream = DiscardedWorkerOutput()
        write_receipt(role + '.runtime.json', {'state': 'STARTING', 'pid': os.getpid(),
                      'updated_utc': datetime.now(timezone.utc).isoformat()})
        code = 0
        with redirect_stdout(stream), redirect_stderr(stream):
            companion=None
            data_probe=None
            try:
                if role=='radar':
                    from schwab_data_probe import start_optional as start_data_probe
                    data_probe=start_data_probe()
                    from telegram_manual_runtime import start_optional
                    companion=start_optional()
                # Same process, so stopping the task cannot orphan a child collector.
                runpy.run_path(sys.argv[0], run_name='__main__')
            except SystemExit as exc:
                code = exc.code if isinstance(exc.code, int) else 1
            except BaseException:
                code = 1
            finally:
                if data_probe is not None:
                    data_probe.close()
                if companion is not None:
                    companion.close()
                write_receipt(role + '.runtime.json', {'state': 'EXITED', 'pid': os.getpid(), 'exit_code': code,
                              'updated_utc': datetime.now(timezone.utc).isoformat()})
    return code


_BASE_ENVIRONMENT = dict(os.environ)


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--role', choices=('collector', 'radar'), required=True)
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--probe-id', default='manual')
    args = parser.parse_args()
    try:
        from sqlite_runtime_guard import require_safe_wal_runtime
        require_safe_wal_runtime(DATABASE)
        return check(args.role, args.probe_id) if args.check else run_worker(args.role)
    except BaseException:
        # In particular, never serialize exceptions containing private configuration.
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
