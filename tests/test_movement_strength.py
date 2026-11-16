from contextlib import closing
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from movement_strength import evaluate
from movement_strength_store import capture, archive_readings, identity

NOW = datetime(2026, 11, 11, 15, 0, 12, tzinfo=timezone.utc)


def event(side='SUPERIOR'):
    from bollinger_phone_worker import STRATEGY_VERSION
    return dict(symbol='QQQ', provider='ALPACA', feed='iex', source_kind='TRADE',
        source_timestamp=NOW.isoformat(), detected_at=(NOW+timedelta(milliseconds=100)).isoformat(),
        version=STRATEGY_VERSION, side=side, price=101 if side == 'SUPERIOR' else 99,
        band_expansion=dict(previous_upper=101, previous_lower=99, upper_pct=7, lower_pct=8, required_pct=3))


def ticks(side='SUPERIOR'):
    sign = 1 if side == 'SUPERIOR' else -1
    rows = []
    for i in range(11):
        t = NOW-timedelta(seconds=10-i)
        progress = .01*i if i <= 5 else .05+.19*(i-5)
        rows.append(dict(time=t.isoformat(), received=t.isoformat(),
                         processed=t.isoformat(), price=100+sign*progress))
    return rows


def volume():
    return dict(ratio=2, sessions=20, closed_at=(NOW-timedelta(seconds=12)).isoformat(), known_at=NOW.isoformat())


class StrengthTests(unittest.TestCase):
    def test_strong_symmetric_call_and_put_and_no_mutation(self):
        for side in ('SUPERIOR', 'INFERIOR'):
            e, t, v = event(side), ticks(side), volume()
            original = deepcopy((e, t, v))
            result = evaluate(e, t, v)
            self.assertEqual(result['classification'], 'ALTA')
            self.assertEqual(result['favorable_components'], 4)
            self.assertEqual((e, t, v), original)
            self.assertFalse(result['calibrated'])

    def test_future_or_late_received_ticks_do_not_change_result(self):
        base = evaluate(event(), ticks(), volume())
        future = dict(time=(NOW+timedelta(seconds=1)).isoformat(), received=NOW.isoformat(),
                      processed=NOW.isoformat(), price=900)
        late = dict(time=NOW.isoformat(), received=(NOW+timedelta(seconds=1)).isoformat(),
                    processed=NOW.isoformat(), price=900)
        processed = {**late, 'received':NOW.isoformat(), 'processed':late['received']}
        self.assertEqual(evaluate(event(), ticks()+[future, late, processed], volume()), base)

    def test_missing_history_or_volume_is_partial_never_high_or_low(self):
        self.assertEqual(evaluate(event(), ticks())['classification'], 'PARCIAL')
        result = evaluate(event())
        self.assertEqual(result['observed_components'], 1)
        self.assertEqual(result['classification'], 'PARCIAL')
        self.assertEqual(len(result['missing']), 3)

    def test_holes_and_wrong_endpoint_disable_tick_metrics(self):
        for data in (ticks()[::4], ticks()[:-1], ticks()[:-1]+[{**ticks()[-1], 'price':999}]):
            result = evaluate(event(), data, volume())
            self.assertNotIn('speed', result['components'])
            self.assertNotIn('continuity', result['components'])

    def test_sparse_anchors_allow_average_speed_but_not_continuity(self):
        result = evaluate(event(), [ticks()[i] for i in (0,5,10)], volume())
        self.assertIn('speed', result['components'])
        self.assertNotIn('continuity', result['components'])
        self.assertEqual(result['classification'], 'PARCIAL')

    def test_ambiguous_same_timestamp_prices_cannot_imply_continuity(self):
        data = ticks()+[{**ticks()[7], 'price':999}]
        self.assertNotIn('continuity', evaluate(event(), data, volume())['components'])

    def test_opposite_band_opening_speed_uses_same_reference(self):
        data = ticks()
        for i, row in enumerate(data):
            row.update(previous_upper=101, previous_lower=99, upper=101+.02*i, lower=99-.03*i)
        result = evaluate(event(), data, volume())
        self.assertAlmostEqual(result['metrics']['opposite_band_speed_pct_width_per_second'], 1.5)
        data[5]['previous_lower'] = 98
        self.assertNotIn('opposite_band_speed_pct_width_per_second', evaluate(event(), data, volume())['metrics'])

    def test_volume_future_and_too_few_sessions_are_unknown(self):
        for value in ({**volume(), 'sessions':9}, {**volume(), 'known_at':(NOW+timedelta(seconds=1)).isoformat()},
                      {**volume(), 'closed_at':(NOW+timedelta(seconds=1)).isoformat()}):
            self.assertNotIn('volume', evaluate(event(), ticks(), value)['components'])

    def test_bar_naive_or_future_decision_are_not_scored(self):
        for change in (dict(source_kind='BAR'),dict(source_timestamp='2026-11-11T15:00:12'),
                       dict(detected_at=(NOW-timedelta(seconds=1)).isoformat())):
            self.assertEqual(evaluate(event() | change, ticks(), volume())['classification'], 'DATOS_INSUFICIENTES')

    def test_retracement_is_not_continuity_and_weak_known_metrics_can_be_low(self):
        data = ticks()
        for row, price in zip(data[5:], [101.5,102,103,102,101.5,101]):
            row['price'] = price
        e = event(); e['band_expansion'].update(upper_pct=3, lower_pct=3)
        result = evaluate(e, data, volume() | dict(ratio=.5))
        self.assertFalse(result['components']['continuity'])
        self.assertEqual(result['classification'], 'BAJA')

    def test_readonly_source_capture_and_reproducible_isolated_archive(self):
        with tempfile.TemporaryDirectory() as folder:
            source, archive = Path(folder)/'market.db', Path(folder)/'strength.db'
            e = event()
            with closing(sqlite3.connect(source)) as db, db:
                db.executescript('''CREATE TABLE bollinger_live_events(event_key TEXT,detected_at TEXT,payload_json TEXT);
                  CREATE TABLE bollinger_tick_audit(symbol TEXT,received_at TEXT,source_timestamp TEXT,message_json TEXT);
                  CREATE INDEX audit_time ON bollinger_tick_audit(received_at);
                  CREATE TABLE bollinger_tick_runtime(id INTEGER,feed TEXT);
                  CREATE TABLE minute_bars(provider TEXT,feed TEXT,symbol TEXT,timestamp TEXT,volume REAL,received_at TEXT);
                  CREATE INDEX minute_lookup ON minute_bars(provider,feed,symbol,timestamp);''')
                db.execute('INSERT INTO bollinger_live_events VALUES(?,?,?)', ('key',e['detected_at'],json.dumps(e)))
                db.execute("INSERT INTO bollinger_tick_runtime VALUES(1,'iex')")
                for t in ticks():
                    msg = dict(T='t',p=t['price'],_jjtrade=dict(processed_at=t['processed'],geometry={}))
                    db.execute('INSERT INTO bollinger_tick_audit VALUES(?,?,?,?)', ('QQQ',t['received'],t['time'],json.dumps(msg)))
                minute = NOW.replace(second=0)-timedelta(minutes=1)
                for day in range(21):
                    dt = minute-timedelta(days=day)
                    db.execute('INSERT INTO minute_bars VALUES(?,?,?,?,?,?)',
                        ('ALPACA','iex','QQQ',dt.isoformat(),200 if day == 0 else 100,
                         (dt+timedelta(minutes=1)).isoformat()))
            before = hashlib.sha256(source.read_bytes()).hexdigest()
            self.assertEqual(capture(source, archive, now=NOW+timedelta(seconds=5)), 1)
            self.assertEqual(capture(source, archive, now=NOW+timedelta(seconds=6)), 0)
            value = archive_readings([e], archive=archive)[identity(e)]
            self.assertEqual(value['classification'], 'ALTA')
            self.assertEqual(before, hashlib.sha256(source.read_bytes()).hexdigest())
            with closing(sqlite3.connect(archive)) as db:
                raw, evidence = db.execute('SELECT event_json,evidence_json FROM strength').fetchone()
                inputs = json.loads(evidence)
                self.assertEqual(evaluate(json.loads(raw), inputs['ticks'], inputs['volume']), value)

    def test_empty_archive_display_has_no_creation_side_effect(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'absent.db'
            self.assertEqual(archive_readings([event()], archive=path), {})
            self.assertFalse(path.exists())

    def test_panel_displays_partial_and_missing_without_execution(self):
        from streamlit.testing.v1 import AppTest
        def page(value):
            import streamlit as st
            from movement_strength import render
            render(value,st=st)
        app = AppTest.from_function(page,args=(evaluate(event()),)).run(timeout=20)
        self.assertEqual(len(app.exception), 0)
        self.assertIn('parcial', '\n'.join(v.value for v in app.markdown))
        self.assertEqual(len(app.dataframe), 1)


if __name__ == '__main__':
    unittest.main()
