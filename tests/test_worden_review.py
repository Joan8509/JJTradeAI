from contextlib import closing
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from worden_review import WordenReviewRepository


class WordenReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Path(self.temp.name) / "test.db"
        with closing(sqlite3.connect(self.database)) as db:
            db.executescript("CREATE TABLE strategy_alerts (id,trigger_timestamp,payload_json); CREATE TABLE alert_visual_evidence (id,alert_id,timeframe,indicators_json);")
            self.payload = json.dumps({"strategies": {"evaluations": [{"strategy_id": "EFECTO_IMAN_TENDENCIA_ALCISTA", "detected": True}]}})
            db.execute("INSERT INTO strategy_alerts VALUES (1,?,?)", (datetime.now(timezone.utc).isoformat(), self.payload))
            db.execute("INSERT INTO alert_visual_evidence VALUES (1,1,'1H','[\"WORDEN\"]')")
            db.execute("INSERT INTO alert_visual_evidence VALUES (2,2,'1H','[\"WORDEN\"]')")
            db.commit()
        self.repository = WordenReviewRepository(self.database)

    def tearDown(self):
        self.temp.cleanup()

    def test_observation_is_versioned_without_changing_signal(self):
        for status in ("SIN_CRUCE", "CRUCE_OBSERVADO"):
            self.repository.record(1, observed_at=datetime.now(timezone.utc) - timedelta(minutes=1), status=status, evidence_id=1)
        self.assertEqual(len(self.repository.recent(1)), 2)
        with closing(sqlite3.connect(self.database)) as db:
            self.assertEqual(db.execute("SELECT payload_json FROM strategy_alerts").fetchone()[0], self.payload)

    def test_evidence_from_another_alert_is_rejected(self):
        with self.assertRaises(ValueError):
            self.repository.record(1, observed_at=datetime.now(timezone.utc), status="CRUCE_OBSERVADO", evidence_id=2)

    def test_future_observation_is_rejected(self):
        with self.assertRaises(ValueError):
            self.repository.record(1, observed_at=datetime.now(timezone.utc) + timedelta(days=1), status="CRUCE_OBSERVADO")


if __name__ == "__main__":
    unittest.main()
