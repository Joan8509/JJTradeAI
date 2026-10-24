"""Bounded one-hour recovery, including after close; no streams/messages/orders.

Run as the DPAPI owner. One request per second, sweeps >=300s apart, honors
429 Retry-After. This process does not start/stop tasks or activate the radar.
"""
from contextlib import closing
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sqlite3
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.observe_vps_recovery import connect, parse, recover, snapshot, dedup, ranges
import vps_private_runtime as runtime
from alpaca_market_data import AlpacaMarketConfig

UTC = timezone.utc


def reference_coverage(symbols, now):
    local_day = now.astimezone(__import__('zoneinfo').ZoneInfo('America/New_York')).date()
    with closing(connect()) as db:
        sessions = db.execute('SELECT opens_at,closes_at FROM market_sessions WHERE session_date>=? '
                              'AND session_date<=? ORDER BY session_date',
                              ((local_day-timedelta(days=7)).isoformat(), local_day.isoformat())).fetchall()
        opens, closes = db.execute('SELECT opens_at,closes_at FROM market_sessions WHERE session_date=?',
                                   (local_day.isoformat(),)).fetchone()
        opens, closes = parse(opens), parse(closes)
        candle = min(closes, opens+timedelta(minutes=15*int((now-opens).total_seconds()//900)))
        expected = []
        for start, end in sessions:
            start, end = parse(start), min(parse(end), candle)
            while start < end:
                expected.append(start)
                start += timedelta(minutes=15)
        expected = expected[-20:]
        result = {}
        for symbol in symbols:
            minutes = {parse(r[0]) for r in db.execute("SELECT timestamp FROM minute_bars WHERE provider='ALPACA' "
                "AND feed='iex' AND symbol=? AND timestamp>=? AND timestamp<?", (symbol, expected[0].isoformat(), candle.isoformat()))}
            absent = [p.isoformat() for p in expected if not any(p <= t < p+timedelta(minutes=15) for t in minutes)]
            previous_close = candle-timedelta(minutes=1) if candle > opens else parse(sessions[-2][1])-timedelta(minutes=1)
            opening_available = bool(db.execute("SELECT 1 FROM minute_bars WHERE provider='ALPACA' AND feed='iex' "
                                                "AND symbol=? AND timestamp=?", (symbol, candle.isoformat())).fetchone())
            result[symbol] = {'current_candle': candle.isoformat(), 'expected_periods': len(expected),
                'market_open': opens <= now < closes,
                'missing_15m_period_starts': absent,
                'previous_official_closing_minute': previous_close.isoformat(),
                'previous_closing_minute_present': previous_close in minutes,
                'current_opening_minute_present': opening_available,
                'blocked_calculations': (['previous_Bollinger_20_closes', 'current_Bollinger_19_closes_plus_price',
                                          'Bollinger_at_open_19_closes_plus_open', 'midpoint_direction', 'both_bands_expansion']
                                         if absent or previous_close not in minutes else []),
                'history_periods_present': len(expected)==20 and not absent and previous_close in minutes}
    return result


def read_observation(symbols):
    """A bounded SQLite read may fail; stale evidence must not remain healthy."""
    try:
        now = datetime.now(UTC)
        return {'observation_available': True,
                'latest_snapshot': snapshot(symbols, (now-timedelta(seconds=60)).isoformat()),
                'reference_coverage': reference_coverage(symbols, now)}
    except sqlite3.OperationalError:
        return {'observation_available': False, 'latest_snapshot': None, 'reference_coverage': {},
                'last_observation_error': {'utc': datetime.now(UTC).isoformat(),
                                           'error_type': 'OperationalError'}}


def main():
    import msvcrt
    private = runtime.load_config()
    if private['feed'] != 'iex' or runtime.authorized('radar'):
        raise ValueError('Observation requires IEX and gated radar')
    with (ROOT/'exports/backups/readiness_retry.lock').open('a+b') as lock:
        lock.seek(0); lock.write(b'0'); lock.flush(); lock.seek(0)
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        config = AlpacaMarketConfig(private['ALPACA_API_KEY'], private['ALPACA_API_SECRET'], 'iex')
        with closing(connect()) as db:
            symbols = json.loads(db.execute('SELECT symbols_json FROM bollinger_tick_runtime WHERE id=1').fetchone()[0])
            close = parse(db.execute('SELECT closes_at FROM market_sessions WHERE session_date=?',
                (datetime.now(UTC).astimezone(__import__('zoneinfo').ZoneInfo('America/New_York')).date().isoformat(),)).fetchone()[0])
        destination = ROOT/'exports/backups'/('readiness_'+datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ'))
        destination.mkdir()
        state = {'pid': os.getpid(), 'started_utc': datetime.now(UTC).isoformat(),
                 'stop_at_utc': (datetime.now(UTC)+timedelta(hours=1)).isoformat(), 'interval_seconds': 300,
                 'request_minimum_interval_seconds': 1, 'feed': 'iex',
                 'radar_activation_supported': False, 'messages_sent': 0, 'orders_enabled': False,
                 'dedup_before': dedup(), 'rounds': [], 'status': 'RUNNING'}
        next_retry = time.monotonic()
        def save():
            tmp = destination/'report.tmp'
            tmp.write_text(json.dumps(state, indent=2), encoding='utf-8')
            tmp.replace(destination/'report.json')
            pointer = {'report': str(destination/'report.json'), 'pid': os.getpid(),
                       'updated_utc': datetime.now(UTC).isoformat(), 'status': state['status'],
                       'next_retry_utc': state.get('next_retry_utc'), 'stop_at_utc': state['stop_at_utc']}
            tmp = ROOT/'exports/backups/readiness_current.tmp'
            tmp.write_text(json.dumps(pointer, indent=2), encoding='utf-8')
            tmp.replace(ROOT/'exports/backups/readiness_current.json')
        while datetime.now(UTC) < parse(state['stop_at_utc']):
            if runtime.authorized('radar') or (ROOT/'exports/backups/readiness_retry.stop').exists():
                state['status'] = 'STOPPED_BY_GATE_OR_REQUEST'
                break
            if time.monotonic() >= next_retry:
                try:
                    current_dedup = dedup()
                    if current_dedup != state['dedup_before']:
                        state['status'] = 'STOPPED_DEDUP_CHANGED'
                        break
                    result = recover(config, symbols, request_interval=1.0)
                    state['dedup_after'] = dedup()
                    state['dedup_unchanged'] = state['dedup_after']==state['dedup_before']
                except sqlite3.OperationalError:
                    # A partial sweep may have inserted official missing bars.
                    # Do not claim zero writes or retry immediately after an
                    # interrupted read; the next sweep rechecks dedup first.
                    result = {'status': 'LOCAL_STORAGE_UNAVAILABLE', 'symbols': {},
                              'inserted_total': None, 'error_type': 'OperationalError'}
                    state['dedup_unchanged'] = None
                state['rounds'].append({'finished_utc': datetime.now(UTC).isoformat(), 'recovery': result})
                next_retry = time.monotonic()+max(300, result.get('retry_after_seconds', 300))
                state['next_retry_utc'] = (datetime.now(UTC)+timedelta(seconds=next_retry-time.monotonic())).isoformat()
                if state['dedup_unchanged'] is False:
                    state['status'] = 'STOPPED_DEDUP_CHANGED'
                    save()
                    break
            state.update(read_observation(symbols))
            save()
            time.sleep(min(15, max(0.1, next_retry-time.monotonic())))
        if state['status']=='RUNNING':
            state['status']='BOUNDED_WATCH_COMPLETED'
        state['finished_utc']=datetime.now(UTC).isoformat()
        save()


if __name__ == '__main__':
    try:
        main()
    except BaseException as error:
        # No URLs, headers, values, raw exception strings or traceback.
        try:
            (ROOT/'exports/backups/readiness_failure.json').write_text(json.dumps({
                'utc':datetime.now(UTC).isoformat(),'error_type':type(error).__name__}),encoding='utf-8')
            pointer = ROOT/'exports/backups/readiness_current.json'
            if pointer.exists():
                value = json.loads(pointer.read_text(encoding='utf-8'))
                if value.get('pid') == os.getpid():
                    value.update(status='FAILED', updated_utc=datetime.now(UTC).isoformat(),
                                 error_type=type(error).__name__)
                    pointer.write_text(json.dumps(value,indent=2),encoding='utf-8')
        finally:
            raise SystemExit(2)
