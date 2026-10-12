from datetime import datetime, timedelta, timezone
import unittest

from market_calendar import MarketSession
from paper_entry_validation import entry_evidence, validate_paper_entry
from tests.test_alert_reevaluation import report


NOW = datetime(2026, 10, 7, 15, 0, tzinfo=timezone.utc)


class PaperEntryValidationTests(unittest.TestCase):
    def setUp(self):
        payload = report()
        payload["methodology_version"] = "test-v1"
        self.alert = {"id": 1, "report": payload, "trigger_timestamp": (NOW - timedelta(minutes=1)).isoformat(),
                      "provider": "ALPACA", "feed": "iex"}
        self.review = {"id": 2, "path_clear": True, "news_clear": True, "panorama_approved": True}
        self.contract = {"id": 3, "candidate": {"symbol": "TEST_OPTION", "option_type": "CALL", "eligible": True,
                                                "risk_status": "APROBADO", "quote_timestamp": (NOW - timedelta(seconds=30)).isoformat()}}
        self.governance = {"id": 4, "status": "APROBADO", "mode": "PAPER"}
        self.session = MarketSession(NOW.date(), NOW.replace(hour=13, minute=30), NOW.replace(hour=20))
        rows = []
        for index in range(25):
            entry = NOW - timedelta(days=index + 1)
            rows.append({"alert_id": index + 10, "strategy_id": "TEST", "bias": "CALL", "horizon_minutes": 60,
                         "methodology_version": "test-v1", "symbol": "SPY", "provider": "ALPACA", "feed": "iex",
                         "entry_timestamp": entry.isoformat(), "exit_timestamp": (entry + timedelta(hours=1)).isoformat(),
                         "directional_return_pct": 1, "favorable_excursion_pct": 1, "adverse_excursion_pct": -0.1})
        self.research = {"generated_at": (NOW - timedelta(seconds=10)).isoformat(), "entry_observations": {"CONFIRMADAS": rows}}

    def validate(self, **changes):
        args = dict(alert=self.alert, review=self.review, contract=self.contract, governance=self.governance,
                    visual_audit=None, research=self.research, as_of=NOW, session=self.session)
        args.update(changes)
        return validate_paper_entry(**args)

    def test_current_rules_and_prior_favorable_evidence_allow_paper_only(self):
        result = self.validate()
        self.assertEqual(result["paper_entry_validation"]["status"], "APROBADA_PAPER")
        self.assertEqual(result["decision"]["decision"], "CALL")
        self.assertEqual(result["decision"]["confidence"], "NO_CALIBRADA")
        self.assertNotIn("paper_entry_validation", self.alert["report"])

    def test_negative_history_blocks_otherwise_approved_rules(self):
        for row in self.research["entry_observations"]["CONFIRMADAS"]:
            row["directional_return_pct"] = -1
        result = self.validate()
        self.assertEqual(result["decision"]["decision"], "NO_OPERAR")
        self.assertEqual(result["paper_entry_validation"]["methodology_decision"]["decision"], "CALL")

    def test_old_signal_cannot_be_approved_today(self):
        self.alert["trigger_timestamp"] = (NOW - timedelta(days=1)).isoformat()
        self.assertEqual(self.validate()["decision"]["decision"], "NO_OPERAR")

    def test_favorable_history_never_bypasses_risk_or_human_review(self):
        self.assertEqual(self.validate(contract=None)["decision"]["decision"], "NO_OPERAR")
        self.review["news_clear"] = None
        self.assertEqual(self.validate()["decision"]["decision"], "NO_OPERAR")

    def test_session_closed_or_real_mode_is_blocked(self):
        self.assertEqual(self.validate(session=None)["decision"]["decision"], "NO_OPERAR")
        self.governance["mode"] = "REAL"
        self.assertEqual(self.validate()["decision"]["decision"], "NO_OPERAR")

    def test_wrong_feed_version_current_alert_and_future_outcomes_are_excluded(self):
        rows = self.research["entry_observations"]["CONFIRMADAS"]
        rows[0]["feed"] = "sip"
        rows[1]["methodology_version"] = "other"
        rows[2]["alert_id"] = 1
        rows[3]["exit_timestamp"] = (NOW + timedelta(minutes=1)).isoformat()
        evidence = entry_evidence(self.alert, self.research, as_of=NOW)
        self.assertEqual(evidence["rows"][0]["sample_size"], 21)

    def test_stale_quote_is_rejected(self):
        self.contract["candidate"]["quote_timestamp"] = (NOW - timedelta(minutes=10)).isoformat()
        self.assertEqual(self.validate()["decision"]["decision"], "NO_OPERAR")


if __name__ == "__main__":
    unittest.main()
