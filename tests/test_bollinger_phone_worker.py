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

    def test_jump_outside_opening_bands_remains_excluded(self):
        self.assertIsNone(detect_values(100, 102, 98, 100, 105, 104, 96, 100.5,
                          opening=104, opening_upper=103, opening_lower=97))
        self.assertIsNone(detect_values(100, 102, 98, 100, 95, 104, 96, 99.5,
                          opening=96, opening_upper=103, opening_lower=97))

    def test_exposure_without_both_bands_opening_is_not_this_strategy(self):
        for side in ('SUPERIOR','INFERIOR'):
            for upper,lower in ((103,98),(102,97),(103,99),(101,97),(102,98)):
                frame = self.frame(side)
                frame.loc[1, "bollinger_upper"] = upper
                frame.loc[1, "bollinger_lower"] = lower
                self.assertIsNone(detect_exit(frame),(side,upper,lower))

    def test_previously_exposed_price_is_not_new_exit(self):
        frame = self.frame()
        frame.loc[0, "close"] = 103
        self.assertIsNone(detect_exit(frame))

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
        self.assertIn("$35",lines[3])
        self.assertIn("$90",lines[3])
        self.assertNotIn("Medias",text)
        signal['side']='INFERIOR'
        self.assertIn('Salida: inferior',message_for('AAPL',signal,datetime(2026,10,8,14,16,tzinfo=timezone.utc)))

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
                self.assertEqual(sender.call_args.kwargs['reply_markup']['inline_keyboard'][0][0]['url'],
                                 'https://jj.example/?operar=AAPL&lado=CALL')
                with patch("bollinger_phone_worker.enabled", return_value=False), patch("bollinger_phone_worker.prepare_market_frame", return_value=self.frame("INFERIOR")):
                    result = tick(database, as_of=now, sender=sender)
                self.assertEqual(result["state"], "VIGILANDO_SIN_AVISOS")
                sender.assert_called_once()
                with sqlite3.connect(database) as db:
                    self.assertEqual(db.execute("SELECT COUNT(*) FROM bollinger_live_events").fetchone()[0], 2)
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
