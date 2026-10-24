"""Passive scheduled evidence: read-only SQLite, no secrets, APIs or activation.

Run once per minute as SYSTEM. A successful task records an observation, not
permission to enable radar. Quiet IEX symbols remain individually unverified.
"""
from collections import Counter
from contextlib import closing
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / 'exports/market_data.db'
DESTINATION = ROOT / 'exports/backups/regular_session_observation'
GATE = ROOT / 'exports/private_runtime/cutover_authorized.json'
NOTICE_BASELINE = ROOT / 'exports/private_runtime/notice_originals.json'
UTC = timezone.utc
NY = ZoneInfo('America/New_York')
ORIGINAL_DIGEST = '5ab9b1b9ece6304609681d14f724f465c4908a3d95b769e5a2b25616a01bb206'
ACCEPTED = {'READY_NO_EXIT', 'EXIT', 'WAITING_FOR_OPEN_OR_HISTORY'}


def parse(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(UTC)


def original_notice_evidence(rows, baseline=NOTICE_BASELINE):
    """New notices may accumulate; the original 154 must remain byte-equivalent."""
    originals = rows
    try:
        reference = json.loads(Path(baseline).read_text(encoding='utf-8'))
        hashes = set(reference['row_hashes'])
        if reference.get('format') != 1 or len(hashes) != 154:
            raise ValueError('Invalid original notice baseline')
        originals = [row for row in rows if hashlib.sha256(
            json.dumps(row, sort_keys=True).encode()).hexdigest() in hashes]
    except FileNotFoundError:
        # Preserve the old exact check before a private baseline is prepared.
        pass
    except (OSError, ValueError, KeyError, TypeError):
        originals = []
    digest = hashlib.sha256(json.dumps(originals, sort_keys=True).encode()).hexdigest()
    return {'count': len(originals), 'digest': digest,
            'unchanged': len(originals) == 154 and digest == ORIGINAL_DIGEST}


def observation_gate_valid(gate):
    roles = gate.get('enabled_roles')
    return (isinstance(roles, list) and len(roles) == len(set(roles)) and
            set(roles) in ({'collector'}, {'collector', 'radar'}) and
            gate.get('orders_enabled') is False)


def observe(database, now, *, clock=None):
    """One consistent snapshot, indexed reads and a two-second SQL budget."""
    day = now.astimezone(NY).date()
    started = time.monotonic()
    with closing(sqlite3.connect(Path(database).resolve().as_uri() + '?mode=ro',
                                uri=True, timeout=2)) as db:
        db.set_progress_handler(lambda: time.monotonic() - started > 2, 1000)
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')
        sessions = db.execute('SELECT opens_at,closes_at FROM market_sessions '
                              'WHERE session_date>=? AND session_date<=? ORDER BY session_date',
                              ((day-timedelta(days=7)).isoformat(), day.isoformat())).fetchall()
        today = db.execute('SELECT opens_at,closes_at FROM market_sessions WHERE session_date=?',
                           (day.isoformat(),)).fetchone()
        state, heartbeat, feed, symbol_json = db.execute(
            'SELECT state,heartbeat,feed,symbols_json FROM bollinger_tick_runtime WHERE id=1').fetchone()
        rows = db.execute('SELECT * FROM bollinger_phone_notifications ORDER BY event_key').fetchall()
        # Production time advances while acquiring the read snapshot. Compare
        # its heartbeat with the post-read clock, without a future tolerance.
        if clock is not None:
            now = clock()
        result = {'utc': now.isoformat(), 'session_date': day.isoformat(),
                  'runtime': {'state': state, 'feed': feed, 'heartbeat': heartbeat,
                              'heartbeat_age_seconds': (now-parse(heartbeat)).total_seconds()},
                  'dedup': {'count': len(rows), 'digest': hashlib.sha256(
                      json.dumps(rows, sort_keys=True).encode()).hexdigest()},
                  'market_open': False, 'symbols': {}}
        originals = original_notice_evidence(rows)
        result['dedup']['original_count'] = originals['count']
        result['dedup']['original_digest'] = originals['digest']
        result['dedup_originals_unchanged'] = originals['unchanged']
        if not today:
            result['status'] = 'NO_OFFICIAL_SESSION'
            return result
        opens, closes = map(parse, today)
        result.update(session_opens=opens.isoformat(), session_closes=closes.isoformat(),
                      market_open=opens <= now < closes)
        if now < opens:
            result['status'] = 'BEFORE_REGULAR_SESSION'
            return result
        candle = min(closes, opens + timedelta(minutes=15*int((now-opens).total_seconds()//900)))
        expected = []
        for start, end in sessions:
            point, end = parse(start), min(parse(end), candle)
            while point < end:
                expected.append(point)
                point += timedelta(minutes=15)
        expected = expected[-20:]
        if not expected:
            result['status'] = 'INSUFFICIENT_OFFICIAL_CALENDAR'
            return result
        previous_close = expected[-1]+timedelta(minutes=14)
        since = now-timedelta(seconds=60)
        audit = db.execute('SELECT symbol,source_timestamp,received_at,reason,message_json '
                           'FROM bollinger_tick_audit WHERE received_at>=? AND received_at<=? '
                           'ORDER BY received_at LIMIT 20001', (since.isoformat(), now.isoformat())).fetchall()
        result['audit_truncated'] = len(audit) > 20000
        latest = {s: json.loads(p) for s, p in db.execute(
            'SELECT symbol,payload_json FROM bollinger_tick_latest')}
        for symbol in json.loads(symbol_json):
            bars = db.execute("SELECT timestamp,received_at FROM minute_bars WHERE provider='ALPACA' "
                              "AND feed='iex' AND symbol=? AND timestamp>=? AND timestamp<? ORDER BY timestamp",
                              (symbol, expected[0].isoformat(), min(closes, now.replace(second=0, microsecond=0)).isoformat())).fetchall()
            minutes = {parse(t) for t, _ in bars}
            absent = [p.isoformat() for p in expected
                      if not any(p <= t < p+timedelta(minutes=15) for t in minutes)]
            events = [r for r in audit if r[0] == symbol and json.loads(r[4]).get('T') == 't']
            latencies = [(parse(r[2])-parse(r[1])).total_seconds()*1000 for r in events if r[1]]
            fresh = [r for r in events if r[1] and r[3] in ACCEPTED
                     and opens <= parse(r[1]) < closes and parse(r[1]) <= now
                     and 0 <= (parse(r[2])-parse(r[1])).total_seconds() <= 3]
            payload = latest.get(symbol, {})
            source, received, checked = (payload.get(k) for k in ('source_timestamp', 'received_at', 'checked_at'))
            processing = (parse(checked)-parse(received)).total_seconds()*1000 if checked and received else None
            fresh_geometry = bool(source and received and checked and
                0 <= (now-parse(source)).total_seconds() <= 3 and
                0 <= (parse(checked)-parse(source)).total_seconds() <= 3 and
                0 <= (parse(received)-parse(source)).total_seconds() <= 3 and
                candle <= parse(source) < min(candle+timedelta(minutes=15), closes) and
                payload.get('reason') in {'READY_NO_EXIT', 'EXIT'})
            missing_minutes = []
            for start, end in sessions:
                point = max(parse(start), expected[0])
                end = min(parse(end), now.replace(second=0, microsecond=0))
                while point < end:
                    if point not in minutes:
                        missing_minutes.append(point.isoformat())
                    point += timedelta(minutes=1)
            last = max(events, key=lambda r: parse(r[2])) if events else None
            result['symbols'][symbol] = {
                'trades_60s': len(events), 'fresh_eligible_trades_60s': len(fresh),
                'reasons_60s': dict(Counter(r[3] for r in events)),
                'latency_ms': {'min': min(latencies) if latencies else None,
                               'max': max(latencies) if latencies else None,
                               'over_3000': sum(x > 3000 for x in latencies),
                               'negative': sum(x < 0 for x in latencies)},
                'last_trade_source': last[1] if last else None,
                'last_trade_received': last[2] if last else None,
                'last_trade_persisted_by': now.isoformat() if last else None,
                'latest_processing_delay_ms': processing, 'geometry_reason': payload.get('reason'),
                'current_candle': candle.isoformat(), 'missing_15m_periods': absent,
                'history_references_present': len(expected) == 20 and not absent and previous_close in minutes,
                'previous_closing_minute_present': previous_close in minutes,
                'opening_minute_present': candle in minutes,
                'missing_official_minute_rows': missing_minutes,
                'last_minute_bar': {'source': bars[-1][0], 'received': bars[-1][1]} if bars else None,
                'fresh_geometry_now': fresh_geometry}
        result['status'] = 'REGULAR_SESSION' if result['market_open'] else 'AFTER_REGULAR_SESSION'
        return result


def add_stability(current, previous):
    """Evidence only; 120s of uninterrupted observed reception is no signal."""
    now = parse(current['utc'])
    healthy = (current.get('market_open') and current.get('dedup_originals_unchanged') and
               current.get('runtime', {}).get('state') == 'CONECTADO' and
               current.get('runtime', {}).get('feed') == 'iex' and
               0 <= current.get('runtime', {}).get('heartbeat_age_seconds', 999) <= 3 and
               current.get('observation_available') and not current.get('audit_truncated'))
    contiguous = (previous.get('session_date') == current.get('session_date') and
                  previous.get('observation_available') and
                  0 < (now-parse(previous['utc'])).total_seconds() <= 90) if previous else False
    for symbol, info in current.get('symbols', {}).items():
        before = previous.get('symbols', {}).get(symbol, {}) if contiguous else {}
        good = healthy and info['fresh_eligible_trades_60s'] > 0
        since = (before.get('reception_observed_since') or current['utc']) if good else None
        seconds = (now-parse(since)).total_seconds() if since else 0
        info.update(reception_observed_since=since, reception_observed_seconds=seconds,
                    reception_stable_120s=seconds >= 120,
                    review_candidate_now=bool(seconds >= 120 and info['history_references_present']
                                               and info['fresh_geometry_now']))
    current['radar_activation_supported'] = False
    current['messages_sent'] = 0
    current['orders_supported'] = False
    return current


def windows_evidence():
    """Local OS metadata only; no usernames, addresses, credentials or network."""
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.windll.kernel32
    kernel.GetTickCount64.restype = ctypes.c_ulonglong
    uptime = kernel.GetTickCount64()/1000
    value = {'system_uptime_seconds': uptime, 'interactive_sessions': []}
    session = wintypes.DWORD()
    if kernel.ProcessIdToSessionId(os.getpid(), ctypes.byref(session)):
        value['windows_session_id'] = session.value

    class Session(ctypes.Structure):
        _fields_ = [('id', wintypes.DWORD), ('name', wintypes.LPWSTR), ('state', ctypes.c_int)]

    wts = ctypes.windll.wtsapi32
    sessions = ctypes.POINTER(Session)()
    count = wintypes.DWORD()
    if wts.WTSEnumerateSessionsW(None, 0, 1, ctypes.byref(sessions), ctypes.byref(count)):
        try:
            for i in range(count.value):
                item = sessions[i]
                if item.id == 0 or item.state not in (0, 4):
                    continue
                buffer = ctypes.c_void_p()
                size = wintypes.DWORD()
                protocol = None
                if wts.WTSQuerySessionInformationW(None, item.id, 16, ctypes.byref(buffer), ctypes.byref(size)):
                    try:
                        if size.value >= 2:
                            protocol = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ushort)).contents.value
                    finally:
                        wts.WTSFreeMemory(buffer)
                value['interactive_sessions'].append({'session_id': item.id,
                    'state': 'Active' if item.state == 0 else 'Disconnected',
                    'protocol': {0: 'Console', 2: 'RDP'}.get(protocol, 'Unknown')})
        finally:
            wts.WTSFreeMemory(sessions)
    return value


def run_once():
    DESTINATION.mkdir(parents=True, exist_ok=True)
    import msvcrt
    with (DESTINATION/'observer.lock').open('a+b') as lock:
        lock.seek(0); lock.write(b'0'); lock.flush(); lock.seek(0)
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        previous = {}
        path = DESTINATION/'latest.json'
        try:
            previous = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            pass
        now = datetime.now(UTC)
        try:
            result = observe(DATABASE, now, clock=lambda: datetime.now(UTC))
            gate = json.loads(GATE.read_text(encoding='utf-8'))
            result['collector_only_gate'] = (gate.get('enabled_roles') == ['collector'] and
                                             gate.get('orders_enabled') is False)
            result['operational_gate_valid'] = observation_gate_valid(gate)
            result['observed_orders_enabled'] = gate.get('orders_enabled')
            result['observation_available'] = True
            if not result['operational_gate_valid']:
                result.update(status='CONTROL_GATE_CHANGED', observation_available=False)
        except Exception as error:
            result = {'utc': now.isoformat(), 'session_date': now.astimezone(NY).date().isoformat(),
                      'status': 'OBSERVATION_UNAVAILABLE', 'observation_available': False,
                      'error_type': type(error).__name__, 'symbols': {}}
        result = add_stability(result, previous)
        result.update(pid=os.getpid())
        if os.name == 'nt':
            result.update(windows_evidence())
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps(result, indent=2), encoding='utf-8')
        temporary.replace(path)
        with (DESTINATION/(result['session_date']+'.jsonl')).open('a', encoding='utf-8') as log:
            log.write(json.dumps(result)+'\n')
        return result


if __name__ == '__main__':
    try:
        value = run_once()
        print(json.dumps({'status': value['status'], 'observation_available': value['observation_available']}))
        raise SystemExit(0 if value['observation_available'] else 2)
    except Exception:
        # Never print database rows, private paths, tokens or raw exceptions.
        raise SystemExit(2)
