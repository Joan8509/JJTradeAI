from contextlib import closing
import unittest
import tempfile
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import pandas as pd

from bollinger_phone_worker import detect_exit, detect_values, message_for, tick
from datetime import datetime, timezone


class BollingerPhoneTests(unittest.TestCase):
    def test_authorized_three_percent_minimum_in_both_directions(self):
        for price,mid,side in ((204,150.5,'SUPERIOR'), (96,149.5,'INFERIOR')):
            args=(150,200,100,150,price,203,97,mid)
            self.assertEqual(detect_values(*args,opening=150),side)
            for upper,lower in ((203,97.01),(202.99,97)):
                weak=(*args[:5],upper,lower,mid)
                self.assertIsNone(detect_values(*weak,opening=150))

    def test_minimum_does_not_override_opening_midpoint_or_direction(self):
        self.assertIsNone(detect_values(150,200,100,150,202,201,99,149,opening=150))
        self.assertIsNone(detect_values(150,200,100,150,202,201,99,151,opening=203))
        self.assertIsNone(detect_values(150,200,100,150,198,201,99,151,opening=150))

    def test_signal_retains_numeric_expansion_without_changing_message_format(self):
        signal=detect_exit(self.frame())
        self.assertEqual(signal['band_expansion']['required_pct'],3)
        self.assertGreaterEqual(signal['band_expansion']['minimum_pct'],3)
        self.assertEqual(len(message_for('AAPL',signal,datetime.now(timezone.utc)).splitlines()),4)

    def test_legacy_notice_alias_blocks_new_source_after_restart(self):
        from bollinger_phone_worker import candle_keys, claim_notice
        for state in ('ENVIADO','ENVIANDO','ENVIO_NO_CONFIRMADO'):
            with tempfile.TemporaryDirectory() as directory:
                path=Path(directory)/'market.db'
                with closing(sqlite3.connect(path)) as db, db:
                    db.execute('CREATE TABLE bollinger_phone_notifications(event_key TEXT PRIMARY KEY,state TEXT,attempted_at TEXT)')
                    keys=candle_keys('v1|chat|ALPACA|iex|MU','2026-10-14T11:30:00-04:00','INFERIOR')
                    db.execute('INSERT INTO bollinger_phone_notifications VALUES(?,?,?)',(keys[1],state,'2026-10-14T15:40:00+00:00'))
                with closing(sqlite3.connect(path)) as db, db:
                    self.assertFalse(claim_notice(db,keys,'2026-10-14T15:41:00+00:00'))
                with closing(sqlite3.connect(path)) as db, db:
                    other=candle_keys('v1|chat|ALPACA|iex|MU','2026-10-14T15:45:00+00:00','INFERIOR')
                    self.assertTrue(claim_notice(db,other,'2026-10-14T15:46:00+00:00'))

    def test_delivery_failure_survives_no_signal_cycles_until_success(self):
        from bollinger_phone_worker import delivery_status
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'market.db'
            with closing(sqlite3.connect(path)) as db, db:
                db.execute('CREATE TABLE bollinger_phone_notifications(event_key TEXT PRIMARY KEY,state TEXT,attempted_at TEXT)')
                db.execute('INSERT INTO bollinger_phone_notifications VALUES(?,?,?)',('old','ENVIO_NO_CONFIRMADO','2026-10-14T15:40:00+00:00'))
            self.assertEqual(delivery_status(path)['last_delivery_state'],'ENVIO_NO_CONFIRMADO')
            with closing(sqlite3.connect(path)) as db, db:
                db.execute('INSERT INTO bollinger_phone_notifications VALUES(?,?,?)',('new','ENVIADO','2026-10-14T15:41:00+00:00'))
            self.assertEqual(delivery_status(path)['last_delivery_state'],'ENVIADO')

    def test_status_reader_lock_retries_without_stopping_monitor(self):
        from bollinger_phone_worker import write_status
        import json
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/'status.json'
            with patch('pathlib.Path.replace',side_effect=[PermissionError('reader lock'),None]) as replace, \
                 patch('bollinger_phone_worker.time.sleep'):
                self.assertTrue(write_status({'state':'VIGILANDO'},target))
                self.assertEqual(replace.call_count,2)
            # A persistent lock is not fatal either; the next cycle tries again.
            with patch('pathlib.Path.replace',side_effect=PermissionError('reader lock')), \
                 patch('bollinger_phone_worker.time.sleep'):
                self.assertFalse(write_status({'state':'VIGILANDO'},target))
            self.assertTrue(write_status({'state':'VIGILANDO'},target))
            self.assertEqual(json.loads(target.read_text(encoding='utf-8'))['state'],'VIGILANDO')

    def frame(self, side="SUPERIOR"):
        return pd.DataFrame([
            {"date": "2026-10-08T14:00:00Z", "close": 100, "bollinger_upper": 102, "bollinger_lower": 98, "bollinger_mid": 100},
            {"date": "2026-10-08T14:15:00Z", "open": 100, "close": 104 if side == "SUPERIOR" else 96,
             "bollinger_upper": 103, "bollinger_lower": 97, "bollinger_mid": 100.5 if side == "SUPERIOR" else 99.5}])

    def test_both_directions_detected_without_waiting_for_close(self):
        for side in ("SUPERIOR", "INFERIOR"):
            self.assertEqual(detect_exit(self.frame(side))["side"], side)

    def test_small_exposure_is_measured_without_suppressing_early_alert(self):
        for side,price in (('SUPERIOR',103.02),('INFERIOR',96.98)):
            frame=self.frame(side)
            frame['close']=frame['close'].astype(float)
            frame.loc[1,'close']=price
            signal=detect_exit(frame)
            self.assertTrue(signal['small_exposure'])
            self.assertAlmostEqual(signal['exposure_pct_bandwidth'],.02/6*100)
            text=message_for('TEST',signal,datetime(2026,10,12,14,0,tzinfo=timezone.utc))
            self.assertIn('TEST',text)
            self.assertNotIn('ancho de Bollinger',text)

    def test_gap_opening_outside_bands_is_excluded_in_both_directions(self):
        for side, opening in (("SUPERIOR", 104), ("INFERIOR", 96)):
            frame = self.frame(side)
            frame.loc[1, "open"] = opening
            self.assertIsNone(detect_exit(frame))

    def test_unknown_opening_cannot_authorize_notification(self):
        self.assertIsNone(detect_exit(self.frame().drop(columns="open")))

    def test_opening_outside_old_band_can_develop_real_exit(self):
        self.assertEqual(detect_values(100, 102, 98, 100, 104, 103, 97, 100.5,
                         opening=102.1, opening_upper=102.3, opening_lower=97.8), 'SUPERIOR')
        self.assertEqual(detect_values(100, 102, 98, 100, 96, 103, 97, 99.5,
                         opening=97.9, opening_upper=102.2, opening_lower=97.7), 'INFERIOR')

    def test_jump_still_outside_current_bands_remains_excluded(self):
        self.assertIsNone(detect_values(100, 102, 98, 100, 105, 104, 96, 100.5,
                          opening=104.01, opening_upper=103, opening_lower=97))
        self.assertIsNone(detect_values(100, 102, 98, 100, 95, 104, 96, 99.5,
                          opening=95.99, opening_upper=103, opening_lower=97))

    def test_exposure_without_both_bands_opening_is_not_this_strategy(self):
        for side in ('SUPERIOR','INFERIOR'):
            for upper,lower in ((103,98),(102,97),(103,99),(101,97),(102,98)):
                frame = self.frame(side)
                frame.loc[1, "bollinger_upper"] = upper
                frame.loc[1, "bollinger_lower"] = lower
                self.assertIsNone(detect_exit(frame),(side,upper,lower))

    def test_previous_exposure_does_not_veto_a_new_inside_opening(self):
        for side, previous_close in (('SUPERIOR',103),('INFERIOR',97)):
            frame = self.frame(side)
            frame.loc[0, "close"] = previous_close
            self.assertEqual(detect_exit(frame)['side'],side)
            frame.loc[1,'open']=104 if side=='SUPERIOR' else 96
            self.assertIsNone(detect_exit(frame))

    def test_meta_marked_candle_inside_opening_and_both_bands_open(self):
        # Archived first minute of the marked 09:45-10:00 candle. Previous
        # close is 0.1187 above its band; this candle's own opening is inside.
        args=(751.63,751.5113244385666,739.7901755614334,745.65075,
              753.765,752.9076822226375,739.2223177773624,746.065)
        opening=dict(opening=751.31,opening_upper=752.2988241362781,
                     opening_lower=739.5856758637218)
        self.assertEqual(detect_values(*args,**opening),'SUPERIOR')
        narrowed=list(args);narrowed[6]=args[2]
        self.assertIsNone(detect_values(*narrowed,**opening))

    def test_midpoint_must_accompany_direction(self):
        frame = self.frame()
        frame.loc[1, "bollinger_mid"] = 99
        self.assertIsNone(detect_exit(frame))

    def test_touch_inside_and_nan_do_not_trigger(self):
        for price in (102, 103, float("nan")):
            frame = self.frame()
            frame.loc[1, "close"] = price
            self.assertIsNone(detect_exit(frame))

    def test_paused_service_never_reads_database_or_sends(self):
        with patch("bollinger_phone_worker.enabled", return_value=False), patch("bollinger_phone_worker.MarketSessionRepository") as calendar, patch("bollinger_phone_worker.send_message") as sender:
            calendar.return_value.session.return_value = None
            self.assertEqual(tick("absent.db")["state"], "FUERA_DE_SESION")
        sender.assert_not_called()

    def test_message_has_only_company_side_candle_and_configured_range(self):
        signal = detect_exit(self.frame())
        text = message_for("AAPL", signal, datetime(2026, 10, 8, 14, 16, tzinfo=timezone.utc))
        lines=text.splitlines()
        self.assertEqual(len(lines),4)
        self.assertIn("AAPL",lines[0])
        self.assertIn("Apple",lines[0])
        self.assertEqual(lines[1],"Salida: superior")
        self.assertIn("10:15 AM ET",lines[2])
        self.assertIn("$45",lines[3])
        self.assertIn("$95",lines[3])
        self.assertNotIn("Medias",text)
        signal['side']='INFERIOR'
        self.assertIn('Salida: inferior',message_for('AAPL',signal,datetime(2026,10,8,14,16,tzinfo=timezone.utc)))

    def test_spcx_notice_names_current_issuer_without_inventing_price_range(self):
        signal=detect_exit(self.frame())
        lines=message_for('SPCX',signal,datetime(2026,10,8,14,16,tzinfo=timezone.utc)).splitlines()
        self.assertEqual(len(lines),4)
        self.assertEqual(lines[0],'SPCX · SpaceX')
        self.assertEqual(lines[3],'Rango de precios: Sin rango definido')

    def test_only_one_notice_per_candle_and_restart(self):
        now = datetime(2026, 10, 8, 14, 17, tzinfo=timezone.utc)
        session = SimpleNamespace(opens_at=now.replace(hour=13, minute=30), closes_at=now.replace(hour=20, minute=0))
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "market.db"
            with sqlite3.connect(database) as db:
                db.execute("CREATE TABLE live_bollinger_preview(symbol TEXT,updated_at TEXT)")
                db.execute("INSERT INTO live_bollinger_preview VALUES('AAPL',?)", (now.isoformat(),))
                db.execute("CREATE TABLE minute_bars(symbol TEXT,provider TEXT,feed TEXT,timestamp TEXT)")
                db.execute("INSERT INTO minute_bars VALUES('AAPL','alpaca','iex',?)", (now.replace(minute=16).isoformat(),))
            db.close()
            with patch("bollinger_phone_worker.enabled", return_value=True), \
                    patch("bollinger_phone_worker.connection", return_value={"chat_id": "1"}), \
                    patch("bollinger_phone_worker.MarketSessionRepository") as calendar, \
                    patch("bollinger_phone_worker.MarketBarStore") as store, \
                    patch("bollinger_phone_worker._minute_reference_ready", return_value=True), \
                    patch("manual_trade_links.signal_link", return_value="https://jj.example/?operar=AAPL&lado=CALL"), \
                    patch("bollinger_phone_worker.aggregate_minute_bars", return_value=self.frame()), \
                    patch("bollinger_phone_worker.prepare_market_frame", return_value=self.frame()):
                calendar.return_value.session.return_value = session
                store.return_value.load_frame.return_value = self.frame()
                from unittest.mock import Mock
                sender = Mock(return_value={"message_id": 12,"date":int(now.timestamp())})
                self.assertEqual(tick(database, as_of=now, sender=sender)["sent"], 1)
                self.assertEqual(tick(database, as_of=now, sender=sender)["sent"], 0)
                sender.assert_called_once()
                self.assertEqual(sender.call_args.kwargs, {})  # Detection only: no buttons.
                self.assertEqual(len(sender.call_args.args[0].splitlines()),4)
                with patch("bollinger_phone_worker.enabled", return_value=False), patch("bollinger_phone_worker.prepare_market_frame", return_value=self.frame("INFERIOR")):
                    result = tick(database, as_of=now, sender=sender)
                self.assertEqual(result["state"], "VIGILANDO_SIN_AVISOS")
                sender.assert_called_once()
                with sqlite3.connect(database) as db:
                    self.assertEqual(db.execute("SELECT COUNT(*) FROM bollinger_live_events").fetchone()[0], 2)
                    import json
                    events=[json.loads(row[0]) for row in db.execute('SELECT payload_json FROM bollinger_live_events')]
                    self.assertTrue(all(event['band_expansion']['required_pct']==3 for event in events))
                    self.assertTrue(all(event['band_expansion']['minimum_pct']>=3 for event in events))
                    timing=db.execute('SELECT send_started_at,telegram_message_at,state FROM bollinger_notice_timing').fetchall()
                    self.assertEqual(timing,[(now.isoformat(),now.isoformat(),'ENVIADO')])
                db.close()

    def test_same_observed_bar_reuses_support_but_next_bar_recalculates(self):
        from bollinger_phone_worker import _signal_support
        _signal_support.cache_clear()
        with patch('bollinger_phone_worker.live_context',return_value={'state':'DESCRIPTIVO'}) as support:
            _signal_support('sample.db','AAPL','ALPACA','iex','2026-10-13T14:00:00+00:00','SUPERIOR',100.)
            _signal_support('sample.db','AAPL','ALPACA','iex','2026-10-13T14:00:00+00:00','SUPERIOR',100.)
            self.assertEqual(support.call_count,1)
            _signal_support('sample.db','AAPL','ALPACA','iex','2026-10-13T14:01:00+00:00','SUPERIOR',101.)
            self.assertEqual(support.call_count,2)
        _signal_support.cache_clear()

    def test_closed_market_never_sends(self):
        with patch("bollinger_phone_worker.enabled", return_value=True), \
                patch("bollinger_phone_worker.connection", return_value={"chat_id": "1"}), \
                patch("bollinger_phone_worker.MarketSessionRepository") as calendar:
            calendar.return_value.session.return_value = None
            self.assertEqual(tick("absent.db")["state"], "FUERA_DE_SESION")

    def test_removed_symbol_is_not_analyzed_even_if_old_scanner_keeps_publishing(self):
        now=datetime(2026,10,13,14,17,tzinfo=timezone.utc)
        session=SimpleNamespace(opens_at=now.replace(hour=13,minute=30),closes_at=now.replace(hour=20,minute=0))
        with tempfile.TemporaryDirectory() as directory:
            database=Path(directory)/'market.db'
            with sqlite3.connect(database) as db:
                db.execute('CREATE TABLE live_bollinger_preview(symbol TEXT,updated_at TEXT)')
                db.execute("INSERT INTO live_bollinger_preview VALUES('GOOG',?)",(now.isoformat(),))
            db.close()
            with patch('bollinger_phone_worker.enabled',return_value=False), \
                    patch('bollinger_phone_worker.MarketSessionRepository') as calendar, \
                    patch('bollinger_phone_worker.detect_exit') as detector:
                calendar.return_value.session.return_value=session
                result=tick(database,as_of=now)
                self.assertEqual(result['observed'],0)
                detector.assert_not_called()
