"""Offline SQLite staging only: no restore, credentials, network or process control."""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3


REQUIRED = {'minute_bars', 'bollinger_phone_notifications', 'bollinger_live_events'}


def digest(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def readonly(path):
    return sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True, timeout=10)


def quote(name):
    return '"' + name.replace('"', '""') + '"'


def inventory(path):
    with closing(readonly(path)) as db:
        db.execute('BEGIN')
        if db.execute('PRAGMA quick_check').fetchall() != [('ok',)]:
            raise ValueError('SQLite integrity failed')
        result = {}
        for name, schema in db.execute("SELECT name,sql FROM sqlite_master WHERE type='table' ORDER BY name").fetchall():
            columns = [r[1] for r in db.execute('PRAGMA table_info(' + quote(name) + ')')]
            if any(re.search(r'token|secret|credential|password|api_key', c, re.I) for c in columns):
                raise ValueError('Credential-like column detected; private review required')
            result[name] = {
                'rows': db.execute('SELECT COUNT(*) FROM ' + quote(name)).fetchone()[0],
                'schema_sha256': hashlib.sha256((schema or '').encode()).hexdigest(),
            }
        if 'bollinger_phone_notifications' in result:
            # Aggregate only: never export event keys, chat IDs, errors or payloads.
            result['bollinger_phone_notifications']['states'] = dict(db.execute(
                'SELECT state,COUNT(*) FROM bollinger_phone_notifications GROUP BY state'))
        return result


def prepare(source, destination):
    source = Path(source).resolve()
    destination = Path(destination).resolve()
    if not source.is_file():
        raise ValueError('Source database missing')
    destination.mkdir(parents=True, exist_ok=False)
    backup = destination / 'market_data.db'
    with closing(readonly(source)) as original, closing(sqlite3.connect(backup)) as copy:
        original.backup(copy, pages=-1, sleep=0.05)
    tables = inventory(backup)
    if REQUIRED - tables.keys():
        raise ValueError('History/dedup tables missing; package is NOT ready')
    manifest = {
        'format': 1, 'created_utc': datetime.now(timezone.utc).isoformat(),
        'sha256': digest(backup), 'bytes': backup.stat().st_size, 'tables': tables,
        'activation_allowed': False,
        'cutover': 'Preliminary snapshot; final snapshot required after coordinated PC writer stop',
    }
    (destination / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    return {'status': 'STAGED_NOT_ACTIVE', 'directory': str(destination), 'sha256': manifest['sha256']}


def review(package, remote):
    package = Path(package).resolve()
    manifest = json.loads((package / 'manifest.json').read_text(encoding='utf-8'))
    backup = package / 'market_data.db'
    if manifest.get('format') != 1 or digest(backup) != manifest['sha256'] or backup.stat().st_size != manifest['bytes']:
        raise ValueError('Package hash/format/size mismatch')
    incoming = inventory(backup)
    if incoming != manifest['tables'] or REQUIRED - incoming.keys():
        raise ValueError('Inventory or required dedup/history tables mismatch')
    existing = inventory(remote)
    return {'status': 'REVIEW_ONLY_NO_RESTORE', 'incoming': incoming, 'remote': existing,
            'activation_allowed': False, 'final_cutover_snapshot_required': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest='action', required=True)
    create = actions.add_parser('prepare')
    create.add_argument('--source', required=True)
    create.add_argument('--destination', required=True)
    check = actions.add_parser('review')
    check.add_argument('--package', required=True)
    check.add_argument('--remote', required=True)
    args = parser.parse_args()
    try:
        result = prepare(args.source, args.destination) if args.action == 'prepare' else review(args.package, args.remote)
    except (OSError, ValueError, KeyError, sqlite3.Error):
        print('BLOCKED: package incomplete or verification failed; no database restored.')
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
