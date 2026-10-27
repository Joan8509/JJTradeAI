"""Opening is official/fixed, membership uses bands available at detection."""
from unittest import TestCase
from bollinger_phone_worker import detect_values, EVENT_KEY_VERSION, STRATEGY_VERSION


class DynamicOpeningTests(TestCase):
    def test_nvda_case_enters_when_current_bands_contain_genuine_opening(self):
        args=(212.1,212.78602646538326,211.09747353461677,211.94175,
              213.62,213.05767144903348,210.91582855096647,211.98675)
        self.assertEqual(detect_values(*args,opening=213.055,
            opening_upper=212.87414785807647,opening_lower=211.04285214192356),'SUPERIOR')
        self.assertIsNone(detect_values(*args,opening=213.06))

    def test_put_and_call_use_current_bands_without_old_band_veto(self):
        self.assertEqual(detect_values(100,102,98,100,104,103,97,100.5,
            opening=102.5,opening_upper=102,opening_lower=98),'SUPERIOR')
        self.assertEqual(detect_values(100,102,98,100,96,103,97,99.5,
            opening=97.5,opening_upper=102,opening_lower=98),'INFERIOR')

    def test_inside_current_bands_is_still_mandatory_not_just_direction(self):
        for opening in (103.001,96.999,None,float('nan')):
            self.assertIsNone(detect_values(100,102,98,100,104,103,97,100.5,opening=opening))

    def test_retraction_one_sided_and_wrong_midpoint_do_not_become_signals(self):
        for price,upper,lower,mid in ((102.9,103,97,100.5),(104,103,98,100.5),(104,103,97,99.5)):
            self.assertIsNone(detect_values(100,102,98,100,price,upper,lower,mid,opening=102.5))

    def test_new_payload_version_does_not_reset_event_or_notice_identity(self):
        self.assertNotEqual(STRATEGY_VERSION,EVENT_KEY_VERSION)
        self.assertEqual(EVENT_KEY_VERSION,'v4_apertura_dentro_sin_veto_previo')

    def test_existing_v4_event_and_uncertain_notice_are_not_replayed_by_v5(self):
        from tests import test_bollinger_contract as fixtures
        from bollinger_tick_stream import TickRepository
        from bollinger_phone_worker import tick,candle_keys
        from datetime import datetime
        from contextlib import closing
        from unittest.mock import Mock,patch
        import sqlite3,json
        h=fixtures.BollingerContractTests();h.setUp();self.addCleanup(h.doCleanups)
        signal={'side':'SUPERIOR','price':104.,'candle':fixtures.CANDLE.isoformat()}
        payload=dict(symbol='AAPL',provider='ALPACA',feed='iex',source_kind='TRADE',
            source_timestamp=h.now.isoformat(),received_at=h.now.isoformat(),checked_at=h.now.isoformat(),
            opening=100.,version=STRATEGY_VERSION,signal=signal)
        TickRepository(h.database).flush({'AAPL':payload},[],state='CONECTADO',feed='iex',symbols=['AAPL'],now=h.now)
        event_key=candle_keys(EVENT_KEY_VERSION+'|ALPACA|iex|AAPL',signal['candle'],'SUPERIOR')[0]
        notice_key=candle_keys('v1|fixture|ALPACA|iex|AAPL',signal['candle'],'SUPERIOR')[0]
        original=json.dumps(dict(payload,**signal,version=EVENT_KEY_VERSION))
        with closing(sqlite3.connect(h.database)) as db,db:
            db.executescript('CREATE TABLE bollinger_live_events(event_key TEXT PRIMARY KEY,detected_at TEXT,payload_json TEXT);'
                'CREATE TABLE bollinger_phone_notifications(event_key TEXT PRIMARY KEY,state TEXT,attempted_at TEXT,message_id INTEGER,error TEXT);')
            db.execute('INSERT INTO bollinger_live_events VALUES(?,?,?)',(event_key,h.now.isoformat(),original))
            db.execute('INSERT INTO bollinger_phone_notifications VALUES(?,?,?,?,?)',(notice_key,'ENVIO_NO_CONFIRMADO',h.now.isoformat(),None,None))
        sender=Mock()
        with patch('bollinger_phone_worker.datetime',wraps=datetime) as clock,patch('bollinger_phone_worker.enabled',return_value=True),patch('bollinger_phone_worker.connection',return_value={'chat_id':'fixture'}):
            clock.now.return_value=h.now
            result=tick(h.database,sender=sender,support_worker=Mock())
        sender.assert_not_called();self.assertEqual(result['sent'],0)
        with closing(sqlite3.connect(h.database)) as db:
            self.assertEqual(db.execute('SELECT payload_json FROM bollinger_live_events').fetchall(),[(original,)])
            self.assertEqual(db.execute('SELECT state FROM bollinger_phone_notifications').fetchall(),[('ENVIO_NO_CONFIRMADO',)])
