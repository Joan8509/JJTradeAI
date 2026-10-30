"""Detector candles use ET in production, audit bounds are UTC text."""
from contextlib import closing
from copy import deepcopy
from datetime import datetime,timedelta,timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from zoneinfo import ZoneInfo
import json,sqlite3
from manual_trade_service import detector_first_source
from tests.test_manual_trade_service import state_fixture,NOW


class DetectorClockTimezoneTests(TestCase):
    def test_et_candle_reads_same_first_source_as_utc_without_renewing(self):
        with TemporaryDirectory() as directory,closing(sqlite3.connect(':memory:')) as db:
            path=Path(directory)/'unique_market.db'
            db.executescript('CREATE TABLE bollinger_tick_audit(received_at TEXT,symbol TEXT,source_timestamp TEXT,reason TEXT,message_json TEXT);'
                'CREATE INDEX audit_time ON bollinger_tick_audit(received_at);')
            candle=NOW.replace(minute=15*(NOW.minute//15),second=0,microsecond=0).astimezone(timezone.utc)
            tick=state_fixture()['tick']
            for offset,reason in [(-1,'READY_NO_EXIT'),(2,'EXIT'),(25,'EXIT')]:
                stamp=(candle+timedelta(seconds=offset)).isoformat()
                db.execute('INSERT INTO bollinger_tick_audit VALUES(?,?,?,?,?)',
                    (stamp,tick['symbol'],stamp,reason,json.dumps({'_jjtrade':{'geometry':{'side':tick['signal']['side']}}})))
            expected=(candle+timedelta(seconds=2)).isoformat()
            tick['signal']['candle']=candle.astimezone(ZoneInfo('America/New_York')).isoformat()
            self.assertEqual(detector_first_source(db,path,tick),expected)
            tick['signal']['candle']=candle.isoformat()
            self.assertEqual(detector_first_source(db,path,tick),expected)
            # Same instant in either representation is one immutable clock.
            db.execute('DELETE FROM bollinger_tick_audit')
            self.assertEqual(detector_first_source(db,path,tick),expected)

    def test_et_candle_without_complete_evidence_remains_blocked(self):
        with TemporaryDirectory() as directory,closing(sqlite3.connect(':memory:')) as db:
            db.executescript('CREATE TABLE bollinger_tick_audit(received_at TEXT,symbol TEXT,source_timestamp TEXT,reason TEXT,message_json TEXT);')
            candle=NOW.replace(minute=15*(NOW.minute//15),second=0,microsecond=0).astimezone(timezone.utc)
            tick=state_fixture()['tick'];tick['signal']['candle']=candle.astimezone(ZoneInfo('America/New_York')).isoformat()
            stamp=(candle+timedelta(seconds=20)).isoformat()
            db.execute('INSERT INTO bollinger_tick_audit VALUES(?,?,?,?,?)',(stamp,tick['symbol'],stamp,'EXIT',
                json.dumps({'_jjtrade':{'geometry':{'side':tick['signal']['side']}}})))
            self.assertIsNone(detector_first_source(db,Path(directory)/'pruned.db',tick))

    def test_naive_candle_is_not_implicitly_assigned_a_machine_timezone(self):
        with TemporaryDirectory() as directory,closing(sqlite3.connect(':memory:')) as db:
            tick=state_fixture()['tick'];tick['signal']['candle']='2026-10-30T09:30:00'
            with self.assertRaises(ValueError):detector_first_source(db,Path(directory)/'naive.db',tick)
