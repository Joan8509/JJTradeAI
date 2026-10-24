"""Observe the existing collector and optionally insert only missing IEX bars.

No WebSocket, alerts, radar/task activation, broker orders or threshold changes.
Private configuration is decrypted only in memory under its owner identity.
"""
from collections import Counter
from contextlib import closing
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import sys
import time
from urllib.error import HTTPError
from urllib.request import urlopen
from email.utils import parsedate_to_datetime

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import vps_private_runtime as runtime
from alpaca_market_data import AlpacaMarketConfig, AlpacaMarketDataProvider
from live_market import NoMarketDataError
from market_store import MarketBarStore
from scripts.diagnose_vps_reception import rest

UTC = timezone.utc


def parse(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(UTC)


def connect():
    db = sqlite3.connect(runtime.DATABASE.as_uri() + '?mode=ro', uri=True, timeout=2)
    started = time.monotonic()
    db.set_progress_handler(lambda: time.monotonic()-started > 2, 10000)
    return db


def dedup():
    with closing(connect()) as db:
        rows = db.execute('SELECT * FROM bollinger_phone_notifications ORDER BY event_key').fetchall()
        return {'count': len(rows), 'digest': hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest(),
                'states': db.execute('SELECT state,COUNT(*) FROM bollinger_phone_notifications GROUP BY state').fetchall()}


def snapshot(symbols, since):
    with closing(connect()) as db:
        db.execute('BEGIN')
        heartbeat = db.execute('SELECT state,heartbeat,feed FROM bollinger_tick_runtime WHERE id=1').fetchone()
        rows = db.execute('SELECT symbol,source_timestamp,received_at,reason FROM bollinger_tick_audit '
                          'WHERE received_at>=? ORDER BY received_at LIMIT 100001', (since,)).fetchall()
        latest = {s: json.loads(p) for s, p in db.execute('SELECT symbol,payload_json FROM bollinger_tick_latest')}
        bars = {s: db.execute("SELECT timestamp,received_at FROM minute_bars WHERE provider='ALPACA' "
                              "AND feed='iex' AND symbol=? ORDER BY timestamp DESC LIMIT 1", (s,)).fetchone() for s in symbols}
    now = datetime.now(UTC)
    per_symbol = {}
    for symbol in symbols:
        events = [r for r in rows if r[0] == symbol]
        latencies = sorted((parse(r[2])-parse(r[1])).total_seconds()*1000 for r in events if r[1])
        reasons = Counter(r[3] for r in events)
        payload = latest.get(symbol, {})
        per_symbol[symbol] = {
            'events': len(events), 'reasons': dict(reasons),
            'latency_ms': {name: round(latencies[min(len(latencies)-1, max(0, math.ceil(q*len(latencies))-1))], 3)
                           if latencies else None for name, q in [('min', 0), ('p50', .5), ('p95', .95), ('max', 1)]},
            'negative_latency_count': sum(x < 0 for x in latencies),
            'over_3s_count': sum(x > 3000 for x in latencies),
            'latest_source': events[-1][1] if events else None,
            'latest_received': events[-1][2] if events else None,
            'latest_geometry_reason': payload.get('reason'),
            'latest_geometry_source': payload.get('source_timestamp'),
            'latest_processing_delay_ms': round((parse(payload['checked_at'])-parse(payload['received_at'])).total_seconds()*1000, 3)
            if payload.get('checked_at') and payload.get('received_at') and payload['checked_at'] >= since else None,
            'bar': bars[symbol],
            'bar_age_seconds': round((now-parse(bars[symbol][0])).total_seconds(), 3) if bars[symbol] else None,
        }
    return {'utc': now.isoformat(), 'since': since, 'runtime': heartbeat,
            'heartbeat_age_seconds': round((now-parse(heartbeat[1])).total_seconds(), 3),
            'audit_limit_exceeded': len(rows) > 100000, 'symbols': per_symbol}


def bar_times(symbol, start, end):
    with closing(connect()) as db:
        return {parse(r[0]) for r in db.execute("SELECT timestamp FROM minute_bars WHERE provider='ALPACA' "
                  "AND feed='iex' AND symbol=? AND timestamp>=? AND timestamp<=?", (symbol, start.isoformat(), end.isoformat()))}


def ranges(values):
    result = []
    for value in sorted(values):
        if result and parse(result[-1]['end']) + timedelta(minutes=1) == value:
            result[-1]['end'] = value.isoformat()
            result[-1]['minutes'] += 1
        else:
            result.append({'start': value.isoformat(), 'end': value.isoformat(), 'minutes': 1})
    return result


def recover(config, symbols, *, request_interval=1.0, as_of=None):
    now = as_of or datetime.now(UTC)
    if now.astimezone(__import__('zoneinfo').ZoneInfo('America/New_York')).date().isoformat() != '2026-10-15':
        raise ValueError('Date-specific recovery requires review')
    with closing(connect()) as db:
        session = db.execute('SELECT opens_at,closes_at FROM market_sessions WHERE session_date=?',
                             ('2026-10-15',)).fetchone()
    start = parse(session[0])
    end = min(now.replace(second=0, microsecond=0)-timedelta(minutes=1),
              parse(session[1])-timedelta(minutes=1))
    expected = {start+timedelta(minutes=n) for n in range(int((end-start).total_seconds()/60)+1)}
    last_request = float('-inf')
    def transport(request):
        nonlocal last_request
        time.sleep(max(0, request_interval-(time.monotonic()-last_request)))
        last_request = time.monotonic()
        with urlopen(request, timeout=15) as response:
            return json.load(response)
    provider = AlpacaMarketDataProvider(config, transport=transport)
    report = {'start': start.isoformat(), 'end': end.isoformat(), 'only_missing': True,
              'signals_evaluated': False, 'symbols': {}}
    for symbol in symbols:
        before = bar_times(symbol, start, end)
        fetched = set()
        inserted = 0
        status = 'OK'
        try:
            frame = provider.fetch_minute_bars(symbol, start=start, end=end)
            frame = frame.loc[(frame.date >= start) & (frame.date <= end)]
            fetched = {d.to_pydatetime() for d in frame.date}
            missing_frame = frame.loc[~frame.date.isin(before)]
            if not missing_frame.empty:
                # Avoid taking a write lock for thousands of known rows on
                # every sweep. only_missing still protects against a live
                # collector inserting the same minute after our read snapshot.
                inserted = MarketBarStore(runtime.DATABASE).upsert_frame(
                    missing_frame, symbol=symbol, provider='ALPACA', feed='iex', only_missing=True)
        except NoMarketDataError:
            status = 'NO_BARS_AVAILABLE'
        except HTTPError as error:
            status = 'HTTP_' + str(error.code)
            if error.code == 429:
                raw_retry = error.headers.get('Retry-After', '')
                try:
                    delay = int(raw_retry)
                except ValueError:
                    try:
                        delay = math.ceil((parsedate_to_datetime(raw_retry)-datetime.now(UTC)).total_seconds())
                    except (TypeError, ValueError, OverflowError):
                        delay = 300
                report.update(rate_limited=True, retry_after_seconds=max(300, delay))
        except Exception as error:
            status = 'REQUEST_FAILED_' + type(error).__name__
        after = bar_times(symbol, start, end)
        report['symbols'][symbol] = {'status': status, 'local_before': len(before), 'provider_rows': len(fetched),
            'inserted': inserted, 'local_after': len(after), 'provider_rows_missing_locally': len(fetched-after),
            'unavailable_minutes': ranges(expected-after)}
        if report.get('rate_limited'):
            break  # No more calls in this sweep; the caller honors backoff.
    return report


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds', type=int, default=240)
    parser.add_argument('--recover-gaps', action='store_true')
    args = parser.parse_args()
    if not 60 <= args.seconds <= 900:
        raise ValueError('Use bounded observation of 60-900 seconds')
    private = runtime.load_config()
    if private['feed'] != 'iex' or runtime.authorized('radar'):
        raise ValueError('Radar must remain gated during observation')
    config = AlpacaMarketConfig(private['ALPACA_API_KEY'], private['ALPACA_API_SECRET'], 'iex')
    with closing(connect()) as db:
        symbols = json.loads(db.execute('SELECT symbols_json FROM bollinger_tick_runtime WHERE id=1').fetchone()[0])
    started = datetime.now(UTC)
    destination = ROOT / 'exports/backups' / ('recovery_' + started.strftime('%Y%m%dT%H%M%SZ'))
    destination.mkdir()
    result = {'started_utc': started.isoformat(), 'feed': 'iex', 'symbols': symbols,
              'dedup_before': dedup(), 'rest_before': rest(config), 'samples': []}
    def save():
        temporary = destination / 'report.tmp'
        temporary.write_text(json.dumps(result, indent=2), encoding='utf-8')
        temporary.replace(destination / 'report.json')
    save()
    print(json.dumps({'report': str(destination / 'report.json')}), flush=True)
    if args.recover_gaps:
        result['recovery'] = recover(config, symbols)
        save()
        print(json.dumps({'recovery_inserted': sum(v['inserted'] for v in result['recovery']['symbols'].values()),
                          'remaining_minutes': {s: sum(v['minutes'] for v in info['unavailable_minutes'])
                                                for s, info in result['recovery']['symbols'].items()}}), flush=True)
    clock = time.monotonic()
    while True:
        sample = snapshot(symbols, (datetime.now(UTC)-timedelta(seconds=60)).isoformat())
        result['samples'].append(sample)
        save()
        print(json.dumps({'utc': sample['utc'], 'heartbeat_age': sample['heartbeat_age_seconds'],
                          'events_60s': sum(v['events'] for v in sample['symbols'].values()),
                          'ready_symbols': [s for s, v in sample['symbols'].items() if v['reasons'].get('READY_NO_EXIT', 0)+v['reasons'].get('EXIT', 0)],
                          'freshness_rejects': sum(v['reasons'].get('DISCONNECTED_OR_STALE', 0)+v['reasons'].get('STALE_AT_RECEIPT', 0) for v in sample['symbols'].values())}), flush=True)
        remaining = args.seconds-(time.monotonic()-clock)
        if remaining <= 0:
            break
        time.sleep(min(15, remaining))
    result['whole_window'] = snapshot(symbols, started.isoformat())
    result['rest_after'] = rest(config)
    result['dedup_after'] = dedup()
    result['dedup_unchanged'] = result['dedup_before'] == result['dedup_after']
    result['finished_utc'] = datetime.now(UTC).isoformat()
    save()
    print(json.dumps({'status': 'OBSERVED', 'dedup_unchanged': result['dedup_unchanged'],
                      'report': str(destination / 'report.json')}), flush=True)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(json.dumps({'status': 'OBSERVATION_FAILED', 'error_type': type(error).__name__}), flush=True)
        raise SystemExit(2)
