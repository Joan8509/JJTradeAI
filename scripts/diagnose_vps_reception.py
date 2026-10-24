"""Bounded, sequential IEX diagnostic; never starts tasks, alerts or orders.

Disable and stop the production collector before invoking under Administrator.
Uses its singleton locks and real fast-ingest worker; records only safe metadata.
"""
from contextlib import closing, redirect_stdout, redirect_stderr
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import logging
from pathlib import Path
import sqlite3
import sys
from threading import Event, Lock, Thread
import time
from urllib.request import Request, urlopen
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import vps_private_runtime as runtime
from alpaca_market_data import AlpacaMarketConfig, AlpacaStockBarStream
from bollinger_tick_stream import RealtimeBollingerWorker
from scanner_instance import ScannerInstanceLease

UTC = timezone.utc


def stamp():
    return datetime.now(UTC).isoformat()


def sql_snapshot(since):
    with closing(sqlite3.connect(runtime.DATABASE.as_uri() + '?mode=ro', uri=True, timeout=10)) as db:
        rows = db.execute('SELECT * FROM bollinger_phone_notifications ORDER BY event_key').fetchall()
        return {
            'checked_utc': stamp(),
            'runtime': db.execute('SELECT state,heartbeat,feed FROM bollinger_tick_runtime WHERE id=1').fetchone(),
            'audit': db.execute('SELECT symbol,COUNT(*),MIN(source_timestamp),MAX(source_timestamp),'
                               'MAX(received_at) FROM bollinger_tick_audit WHERE received_at>=? GROUP BY symbol', (since,)).fetchall(),
            'bars': {symbol: db.execute("SELECT timestamp,received_at FROM minute_bars WHERE provider='ALPACA' "
                                       "AND feed='iex' AND symbol=? ORDER BY timestamp DESC LIMIT 1", (symbol,)).fetchone()
                     for symbol in ('AAPL', 'SPY')},
            'dedup_count': len(rows),
            'dedup_states': db.execute('SELECT state,COUNT(*) FROM bollinger_phone_notifications GROUP BY state').fetchall(),
            'dedup_digest': hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest(),
        }


def rest(config):
    headers = {'APCA-API-KEY-ID': config.api_key, 'APCA-API-SECRET-KEY': config.api_secret,
               'Cache-Control': 'no-cache'}
    results = []
    for kind in ('trades', 'quotes'):
        try:
            with urlopen(Request('https://data.alpaca.markets/v2/stocks/' + kind +
                                 '/latest?symbols=AAPL,SPY&feed=iex', headers=headers), timeout=15) as response:
                payload = json.load(response)
                now = datetime.now(UTC)
                results.append({'kind': kind, 'utc': now.isoformat(), 'http_status': response.status,
                                'server_date': response.headers.get('Date'),
                                'symbols': {s: {'timestamp': v['t'], 'age_seconds': round((now - datetime.fromisoformat(
                                    v['t'].replace('Z', '+00:00'))).total_seconds(), 3)}
                                    for s, v in payload.get(kind, {}).items() if s in ('AAPL', 'SPY')}})
        except HTTPError as error:
            results.append({'kind': kind, 'http_status': error.code})
        except Exception:
            results.append({'kind': kind, 'status': 'REQUEST_FAILED'})
    return results


def main():
    import msvcrt
    import websocket
    logging.disable(logging.CRITICAL)
    report = {'started_utc': stamp(), 'endpoint': 'wss://stream.data.alpaca.markets/v2/iex',
              'duration_target_seconds': 120, 'radar_started': False, 'orders_enabled': False}
    output = ROOT / 'exports/backups' / ('reception_' + datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ'))
    output.mkdir()
    def save():
        (output / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    save()
    print(json.dumps({'report': str(output / 'report.json')}), flush=True)
    with (runtime.PRIVATE / 'collector.supervisor.lock').open('r+b') as singleton:
        msvcrt.locking(singleton.fileno(), msvcrt.LK_NBLCK, 1)
        with ScannerInstanceLease(ROOT / 'exports/live_scanner.lock'):
            private = runtime.load_config()
            if private['feed'] != 'iex' or not runtime.authorized('collector') or runtime.authorized('radar'):
                raise RuntimeError('Diagnostic gating failed')
            config = AlpacaMarketConfig(private['ALPACA_API_KEY'], private['ALPACA_API_SECRET'], 'iex')
            with closing(sqlite3.connect(runtime.DATABASE.as_uri() + '?mode=ro', uri=True)) as db:
                symbols = json.loads(db.execute('SELECT symbols_json FROM bollinger_tick_runtime WHERE id=1').fetchone()[0])
            report['symbols'] = symbols
            report['before'] = sql_snapshot(report['started_utc'])
            report['rest_before'] = rest(config)
            ack = Event()
            mutex = Lock()
            counts = Counter()
            originals = websocket.WebSocketApp
            def factory(url, **callbacks):
                original_message = callbacks['on_message']
                def message(socket, raw):
                    items = json.loads(raw)
                    items = items if isinstance(items, list) else [items]
                    with mutex:
                        report['last_frame_utc'] = stamp()
                        for item in items:
                            typ = item.get('T')
                            counts[str(typ)] += 1
                            if typ == 'subscription':
                                report['subscription'] = {k: item.get(k, []) for k in ('trades', 'bars', 'updatedBars')}
                                report['subscription_utc'] = stamp()
                                if all(set(symbols).issubset(item.get(k, [])) for k in ('trades', 'bars', 'updatedBars')):
                                    ack.set()
                            if typ in ('t', 'c', 'x', 'b', 'u'):
                                report['last_market_event'] = {'type': typ, 'symbol': item.get('S'),
                                                               'source_timestamp': item.get('t'), 'received_utc': stamp()}
                            if typ == 'error':
                                report['provider_error_code'] = item.get('code')
                    original_message(socket, raw)
                def pong(socket, payload):
                    with mutex:
                        counts['pong'] += 1
                        report['last_pong_utc'] = stamp()
                callbacks.update(on_message=message, on_pong=pong)
                return originals(url, **callbacks)
            websocket.WebSocketApp = factory
            worker = RealtimeBollingerWorker(runtime.DATABASE, 'iex', symbols)
            stream = AlpacaStockBarStream(config, on_trade_message=worker.trade)
            def error(failure):
                report['stream_error_type'] = type(failure).__name__
            def monitor():
                if not ack.wait(30):
                    report['status'] = 'SUBSCRIPTION_NOT_CONFIRMED'
                    stream.stop()
                    return
                start = time.monotonic()
                report['observation_started_utc'] = stamp()
                report['samples'] = []
                while True:
                    remaining = 120 - (time.monotonic() - start)
                    if remaining > 0:
                        time.sleep(min(10, remaining))
                    with mutex:
                        report['frame_counts'] = dict(counts)
                    report['samples'].append(sql_snapshot(report['observation_started_utc']))
                    save()
                    if time.monotonic() - start >= 120:
                        break
                report['observation_elapsed_seconds'] = round(time.monotonic() - start, 3)
                report['observation_ended_utc'] = stamp()
                stream.stop()
            observer = Thread(target=monitor, daemon=True)
            observer.start()
            try:
                with redirect_stdout(runtime.DiscardedWorkerOutput()), redirect_stderr(runtime.DiscardedWorkerOutput()):
                    stream.run(symbols, lambda bar: worker.bar(bar, lambda _: None),
                               on_status=worker.status, on_error=error)
                observer.join(timeout=155)
            finally:
                stream.stop()
                worker.close()
                websocket.WebSocketApp = originals
            report['worker_failed'] = worker.failed.is_set()
            report['after'] = sql_snapshot(report.get('observation_started_utc', report['started_utc']))
            report['dedup_unchanged'] = report['before']['dedup_digest'] == report['after']['dedup_digest']
            report['rest_after'] = rest(config)
            report['finished_utc'] = stamp()
            report['status'] = report.get('status', 'OBSERVATION_COMPLETE')
            save()
    print(json.dumps(report), flush=True)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(json.dumps({'status': 'DIAGNOSTIC_FAILED', 'error_type': type(error).__name__}), flush=True)
        raise SystemExit(2)
