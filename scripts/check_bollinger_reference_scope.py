"""Read-only scope coverage report. No provider, message or trading imports."""
import argparse
from contextlib import closing
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from bollinger_reference_scope import REGULAR, EXTENDED, NY, required_periods, regular_session


def coverage(database, symbol, feed, candle, scope):
    started = time.monotonic()
    result = dict(symbol=symbol, scope=scope, required_periods=20,
                  status='UNAVAILABLE', missing_periods=[], previous_final_minute=False)
    with closing(sqlite3.connect(Path(database).resolve().as_uri()+'?mode=ro', uri=True, timeout=.25)) as db:
        db.execute('PRAGMA query_only=ON')
        db.set_progress_handler(lambda: time.monotonic()-started > 1.5, 1000)
        local_day = candle.astimezone(NY).date()
        rows = db.execute('SELECT opens_at,closes_at FROM market_sessions WHERE session_date>=? '
                          'AND session_date<=? ORDER BY session_date',
                          ((local_day-timedelta(days=7)).isoformat(), local_day.isoformat())).fetchall()
        periods = required_periods(rows, candle, scope=scope)
        if regular_session(rows, candle) is None or not periods:
            result['status'] = 'CALENDAR_UNAVAILABLE'
            return result
        for a, b in periods:
            row = db.execute('SELECT timestamp FROM minute_bars WHERE provider=? AND feed=? AND symbol=? '
                             'AND timestamp>=? AND timestamp<=? ORDER BY timestamp DESC LIMIT 1',
                             ('ALPACA', feed, symbol, a.isoformat(), (b-timedelta(minutes=1)).isoformat())).fetchone()
            if row is None:
                result['missing_periods'].append(a.isoformat())
            if (a, b) == periods[-1]:
                result['previous_final_minute'] = bool(row and datetime.fromisoformat(row[0]) == b-timedelta(minutes=1))
    result['periods_available'] = 20-len(result['missing_periods'])
    result['status'] = ('COMPLETE' if not result['missing_periods'] and result['previous_final_minute']
                        else 'MISSING_REFERENCES')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, default=ROOT/'exports/market_data.db')
    parser.add_argument('--at', required=True, help='Regular candle start with timezone; never authorizes historical alerts.')
    parser.add_argument('--symbols', nargs='+', required=True)
    parser.add_argument('--feed', default='iex', choices=['iex'])
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    stamp = datetime.fromisoformat(args.at)
    if stamp.tzinfo is None or stamp.minute % 15 or stamp.second or stamp.microsecond:
        parser.error('--at must be a timezone-aware 15-minute candle boundary')
    stamp = stamp.astimezone(timezone.utc)
    results = []
    for symbol in args.symbols:
        for scope in (REGULAR, EXTENDED):
            try:
                results.append(coverage(args.database, symbol.upper(), args.feed, stamp, scope))
            except sqlite3.Error as error:
                results.append(dict(symbol=symbol.upper(), scope=scope, status='UNAVAILABLE', error_type=type(error).__name__))
        time.sleep(.02)  # Release read locks between symbols on DELETE databases.
    extended = [r for r in results if r['scope'] == EXTENDED]
    report = dict(checked_utc=datetime.now(timezone.utc).isoformat(), candle=stamp.isoformat(),
                  feed=args.feed, results=results,
                  coverage_passed=bool(extended) and all(r['status'] == 'COMPLETE' for r in extended),
                  tc2000_numerical_parity_verified=False,
                  policy_activated=False, database_mutations=0, messages_sent=0, orders_sent=0)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
