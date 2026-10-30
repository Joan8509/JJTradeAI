"""Startup invariant check: actual clock lookup, isolated SQLite, no network/I/O."""
from collections import OrderedDict
from contextlib import closing
from datetime import datetime,timedelta,timezone
import json
import sqlite3
from zoneinfo import ZoneInfo

REVISION='et_utc_startup_invariants_v1'


def check_detector_clock(lookup=None):
    if lookup is None:
        from manual_trade_service import detector_first_source
        lookup=detector_first_source
    try:
        with closing(sqlite3.connect(':memory:')) as db:
            db.executescript('CREATE TABLE bollinger_tick_audit(received_at TEXT,symbol TEXT,'
                'source_timestamp TEXT,reason TEXT,message_json TEXT);'
                'CREATE INDEX audit_clock ON bollinger_tick_audit(received_at);')
            for day in ('2026-01-15','2026-07-15'):
                db.execute('DELETE FROM bollinger_tick_audit')
                cache=OrderedDict()
                candle=datetime.fromisoformat(day+'T09:30:00').replace(
                    tzinfo=ZoneInfo('America/New_York'))
                utc=candle.astimezone(timezone.utc)
                tick=dict(symbol='CLOCK_SELFTEST',version=REVISION,
                    signal=dict(candle=candle.isoformat(),side='SUPERIOR'))
                first=(utc+timedelta(seconds=2)).isoformat()
                for offset,reason in ((-1,'READY_NO_EXIT'),(2,'EXIT'),(22,'EXIT')):
                    stamp=(utc+timedelta(seconds=offset)).isoformat()
                    db.execute('INSERT INTO bollinger_tick_audit VALUES(?,?,?,?,?)',
                        (stamp,tick['symbol'],stamp,reason,
                         json.dumps({'_jjtrade':{'geometry':{'side':'SUPERIOR'}}})))
                if lookup(db,'isolated_clock_selftest',tick,cache=cache)!=first:return False
                tick['signal']['candle']=utc.isoformat()
                db.execute('DELETE FROM bollinger_tick_audit')
                if lookup(db,'isolated_clock_selftest',tick,cache=cache)!=first:return False
                if lookup(db,'isolated_clock_selftest',tick,cache=OrderedDict()) is not None:return False
                # Pruned evidence must not silently start a new 30-second clock.
                db.execute('INSERT INTO bollinger_tick_audit VALUES(?,?,?,?,?)',
                    (first,tick['symbol'],first,'EXIT',
                     json.dumps({'_jjtrade':{'geometry':{'side':'SUPERIOR'}}})))
                if lookup(db,'isolated_clock_selftest',tick,cache=OrderedDict()) is not None:return False
        return True
    except Exception:
        return False  # Fixed health flag only; never expose DB content/errors.
