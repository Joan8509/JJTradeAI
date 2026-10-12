import json
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from cloud_snapshot_api import authorized, snapshot
from bollinger_phone_worker import STRATEGY_VERSION
from telegram_alerts import connection, send_message
from web_vercel.api.dashboard import COOKIE, create_session, valid_session, fetch_snapshot, settings


class CloudWebTests(unittest.TestCase):
    def test_private_session_is_signed_and_expires(self):
        secret = b"s"*32
        token = create_session(secret, now=1000)
        cookie = f"{COOKIE}={token}"
        self.assertTrue(valid_session(cookie, secret, now=1001))
        self.assertFalse(valid_session(cookie, secret, now=30000))
        self.assertFalse(valid_session(cookie, b"other"*8, now=1001))
        self.assertFalse(valid_session(f"{COOKIE}=invalid", secret, now=1001))
        self.assertFalse(valid_session(None, secret))

    def test_missing_login_and_backend_settings_fail_closed(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ValueError):
                settings()
            with self.assertRaises(ValueError):
                fetch_snapshot()
        self.assertFalse(authorized(None, "x"*32))
        self.assertFalse(authorized("Bearer weak", "weak"))
        self.assertTrue(authorized("Bearer "+"x"*32, "x"*32))

    def test_snapshot_rejects_insecure_backend_and_does_not_call_it(self):
        with patch.dict(os.environ, {"JJTRADE_BACKEND_URL": "http://example.com/snapshot", "JJTRADE_BACKEND_KEY": "x"*32}), patch("web_vercel.api.dashboard.build_opener") as opener:
            with self.assertRaises(ValueError):
                fetch_snapshot()
        opener.assert_not_called()

    def test_environment_telegram_secret_is_not_returned_or_written(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"unused.json"
            with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "123:private", "TELEGRAM_CHAT_ID": "555"}), patch("telegram_alerts.call", return_value={"message_id": 1}) as api:
                saved = connection(path)
                self.assertNotIn("123:private", json.dumps(saved))
                send_message("test", path)
                self.assertEqual(api.call_args.args[0], "123:private")
            self.assertFalse(path.exists())

    def test_snapshot_filters_old_versions_stale_data_and_private_fields(self):
        now = datetime(2026, 10, 9, 14, 0, tzinfo=timezone.utc)
        session = SimpleNamespace(opens_at=now.replace(hour=13, minute=30), closes_at=now.replace(hour=20, minute=0))
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory)/"market.db"
            status = Path(directory)/"status.json"
            status.write_text(json.dumps({"state": "VIGILANDO", "heartbeat": now.isoformat(), "pid": 99, "private": "secret"}))
            row = {"symbol": "AAPL", "version": STRATEGY_VERSION, "source_timestamp": "2026-10-09T13:59:00+00:00", "status": "SALIDA_DETECTADA", "signal": {"side": "SUPERIOR", "price": 100}, "private": "secret"}
            db = sqlite3.connect(database)
            db.execute("CREATE TABLE bollinger_radar_state(payload_json TEXT)")
            for item in (row, {**row, "symbol": "MSFT", "version": "v1"}, {**row, "symbol": "SPY", "source_timestamp": "2026-10-09T13:50:00+00:00"}):
                db.execute("INSERT INTO bollinger_radar_state VALUES(?)", (json.dumps(item),))
            db.commit()
            db.close()
            with patch("cloud_snapshot_api.MarketSessionRepository") as calendar:
                calendar.return_value.session.return_value = session
                result = snapshot(database, as_of=now, status_path=status, study_path=Path(directory)/"absent.json")
            self.assertEqual([r["symbol"] for r in result["current"]], ["AAPL"])
            self.assertNotIn("secret", json.dumps(result))
            status.write_text(json.dumps({"state": "VIGILANDO", "heartbeat": "2026-10-09T13:50:00+00:00"}))
            with patch("cloud_snapshot_api.MarketSessionRepository") as calendar:
                calendar.return_value.session.return_value = session
                result = snapshot(database, as_of=now, status_path=status, study_path=Path(directory)/"absent.json")
            self.assertEqual(result["current"], [])
            self.assertFalse(result["radar_healthy"])
