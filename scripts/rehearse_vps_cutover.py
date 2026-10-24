"""Rehearse SQLite migration in a NEW isolated directory. Never activates services."""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.prepare_vps_migration import digest, inventory, quote, readonly, review
from database_backup import restore_sqlite_backup


def snapshot(source, target):
    with closing(readonly(source)) as original, closing(sqlite3.connect(target)) as copy:
        original.backup(copy, pages=2048, sleep=0.05)
    result = {'created_at': datetime.now(timezone.utc).isoformat(),
              'backup_name': target.name, 'source_name': Path(source).name,
              'sha256': digest(target), 'size_bytes': target.stat().st_size}
    target.with_suffix('.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    return result


def exclusive_rows(remote, incoming):
    """Compare named columns, not physical position. No private row values exported."""
    result = {}
    with closing(readonly(remote)) as db:
        db.execute('ATTACH DATABASE ? AS pc', (Path(incoming).resolve().as_uri() + '?mode=ro',))
        db.execute('BEGIN')
        for (table,) in db.execute("SELECT name FROM main.sqlite_master WHERE type='table'").fetchall():
            if table.startswith('sqlite_'):
                continue  # AUTOINCREMENT metadata is audited separately.
            q = quote(table)
            count = db.execute('SELECT count(*) FROM main.' + q).fetchone()[0]
            if not count:
                result[table] = {'rows': 0, 'exclusive_rows': 0}
                continue
            exists = db.execute("SELECT 1 FROM pc.sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
            columns = [r[1] for r in db.execute('PRAGMA main.table_xinfo(' + q + ')') if r[6] == 0]
            pc_columns = {r[1] for r in db.execute('PRAGMA pc.table_xinfo(' + q + ')')} if exists else set()
            if not exists or not set(columns) <= pc_columns:
                result[table] = {'rows': count, 'exclusive_rows': None, 'manual_preservation_required': True}
                continue
            names = ','.join(quote(c) for c in columns)
            # DISTINCT row comparison, plus key differences when schemas cannot compare.
            differences = db.execute('SELECT count(*) FROM (SELECT ' + names + ' FROM main.' + q +
                                     ' EXCEPT SELECT ' + names + ' FROM pc.' + q + ')').fetchone()[0]
            result[table] = {'rows': count, 'exclusive_distinct_rows': differences}
        result['_sqlite_sequence'] = dict(db.execute('SELECT name,seq FROM main.sqlite_sequence'))
    return result


def relation_checks(path):
    with closing(readonly(path)) as db:
        integrity = db.execute('PRAGMA integrity_check').fetchall()
        counts = {}
        for table, _, _, _ in db.execute('PRAGMA foreign_key_check'):
            counts[table] = counts.get(table, 0) + 1
        return {'integrity_ok': integrity == [('ok',)], 'foreign_key_violations_by_table': counts}


def protected_hashes(path):
    tables = ('strategy_alerts', 'minute_bars', 'bollinger_live_events',
              'bollinger_phone_notifications', 'bollinger_notice_timing')
    result = {}
    with closing(readonly(path)) as db:
        for table in tables:
            # History bars are proven byte-identical by restore hash and checked
            # by count/range after schema initialization; avoid hashing 4M JSON rows.
            if table == 'minute_bars':
                result[table] = db.execute('SELECT count(*),min(timestamp),max(timestamp) FROM minute_bars').fetchone()
                continue
            q = quote(table)
            columns = sorted(r[1] for r in db.execute('PRAGMA table_info(' + q + ')'))
            h = hashlib.sha256()
            for row in db.execute('SELECT ' + ','.join(quote(c) for c in columns) + ' FROM ' + q + ' ORDER BY rowid'):
                h.update(json.dumps(row, ensure_ascii=True, default=str).encode())
                h.update(b'\n')
            result[table] = h.hexdigest()
    return result


def exercise_claims(path):
    from bollinger_phone_worker import candle_keys, claim_notice
    counts = {}
    with closing(sqlite3.connect(path)) as db:
        rows = db.execute('SELECT event_key,state FROM bollinger_phone_notifications').fetchall()
        for key, state in rows:
            prefix, candle, side = key.rsplit('|', 2)
            keys = candle_keys(prefix, candle, side)
            try:
                if claim_notice(db, keys, datetime.now(timezone.utc).isoformat()):
                    raise ValueError('Existing notification could be claimed again')
                counts[state] = counts.get(state, 0) + 1
            finally:
                db.rollback()
    return {'existing_claims_blocked_by_state': counts, 'committed_writes': 0}


def rehearse(package, active, output):
    package, active, output = (Path(p).resolve() for p in (package, active, output))
    backup_root = (ROOT / 'exports' / 'backups').resolve()
    if not output.is_relative_to(backup_root) or output == backup_root:
        raise ValueError('Output must be a NEW subdirectory of exports/backups')
    if active.is_relative_to(output) or package.is_relative_to(output) or output.is_relative_to(package):
        raise ValueError('Rehearsal must be separate from source and active database')
    output.mkdir(parents=True, exist_ok=False)
    report = {'created_utc': datetime.now(timezone.utc).isoformat(), 'activation_allowed': False,
              'directory': str(output), 'final_snapshot_required': True}
    safety = output / 'vps_before.db'
    report['vps_backup'] = snapshot(active, safety)
    report['vps_integrity'] = relation_checks(safety)
    print('VPS snapshot created; reviewing PC package', flush=True)
    report['package_review'] = review(package, safety)
    incoming = package / 'market_data.db'
    expected = json.loads((package / 'manifest.json').read_text(encoding='utf-8'))['sha256']
    report['vps_exclusivity'] = exclusive_rows(safety, incoming)
    trial = output / 'pc_trial.db'
    restore_sqlite_backup(incoming, trial, expected_sha256=expected)
    report['initial_restore_byte_identical'] = digest(trial) == expected
    report['trial_relations_before'] = relation_checks(trial)
    before = inventory(trial)
    print('Isolated restore verified; checking offline repository compatibility', flush=True)
    protected_before = protected_hashes(trial)
    # No app, scanner main, radar tick, data provider or Telegram method runs.
    # The socket guard also blocks accidental network use during this process.
    from live_strategy_service import AlertRepository
    from market_store import MarketBarStore
    AlertRepository(trial)
    MarketBarStore(trial)
    report['repository_initialization_passed'] = True
    report['protected_history_preserved'] = protected_before == protected_hashes(trial)
    report['dedup_claim_rehearsal'] = exercise_claims(trial)
    report['trial_relations_after'] = relation_checks(trial)
    report['tables_before'] = before
    report['tables_after'] = inventory(trial)
    # Rehearse recovery onto a second isolated target; never overwrite trial or active.
    recovery = output / 'rollback_trial.db'
    with closing(sqlite3.connect(recovery)) as db:
        db.execute('CREATE TABLE rehearsal_marker (id INTEGER)')
        db.commit()
    restore_sqlite_backup(safety, recovery, expected_sha256=report['vps_backup']['sha256'],
                          overwrite=True, safety_backup_directory=output / 'rollback_safety')
    report['rollback_byte_identical'] = digest(recovery) == report['vps_backup']['sha256']
    report['rollback_integrity'] = relation_checks(recovery)
    checks = [report['initial_restore_byte_identical'], report['protected_history_preserved'],
              report['rollback_byte_identical']]
    checks.extend(report[k]['integrity_ok'] and not report[k]['foreign_key_violations_by_table']
                  for k in ('vps_integrity', 'trial_relations_before', 'trial_relations_after', 'rollback_integrity'))
    report['status'] = 'REHEARSED_NOT_ACTIVE' if all(checks) else 'REHEARSAL_REQUIRES_REVIEW'
    (output / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    summary = {k: report[k] for k in ('status', 'directory', 'activation_allowed',
               'initial_restore_byte_identical', 'repository_initialization_passed',
               'protected_history_preserved', 'rollback_byte_identical',
               'trial_relations_before', 'trial_relations_after', 'dedup_claim_rehearsal', 'vps_exclusivity')}
    print(json.dumps(summary, indent=2))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package', required=True)
    parser.add_argument('--active', default=str(ROOT / 'exports' / 'market_data.db'))
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    with patch('socket.socket.connect', side_effect=RuntimeError('Network disabled for rehearsal')), \
         patch('socket.create_connection', side_effect=RuntimeError('Network disabled for rehearsal')):
        rehearse(args.package, args.active, args.output)


if __name__ == '__main__':
    main()
