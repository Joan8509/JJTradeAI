"""Pruebas del scanner continuo y su registro auditable."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

from live_market import MarketBar
from live_strategy_service import (
    AlertRepository,
    ContinuousStrategyScanner,
    bundle_daily_session_closed,
    detector_failure_from_report,
    reconcile_scanner_result_incidents,
)
from market_store import MarketBarStore, MarketContinuityService
from scanner_incident import ScannerIncidentRepository


START = datetime(2026, 7, 20, 13, 30, tzinfo=timezone.utc)


class UnusedProvider:
    def fetch_minute_bars(self, symbol, *, start, end):
        raise AssertionError("No debe solicitar backfill durante esta prueba.")


def report(symbol: str) -> dict:
    return {
        "symbol": symbol,
        "data_as_of": "2026-07-20T13:30:00+00:00",
        "methodology_version": "test-1.0",
        "decision": {"decision": "NO_OPERAR"},
        "strategy_summary": {"detected": 2, "confirmed": 1},
        "strategies": {"evaluations": [], "errors": {}},
    }


class LiveStrategyServiceTests(unittest.TestCase):
    def test_daily_close_requires_same_session_as_intraday(self) -> None:
        class Bundle:
            metadata = {"closed_through": {"1D": "2026-07-20T20:00:00Z", "15m": "2026-07-20T20:00:00Z"}}

        self.assertTrue(bundle_daily_session_closed(Bundle()))
        Bundle.metadata["closed_through"]["1D"] = "2026-07-19T20:00:00Z"
        self.assertFalse(bundle_daily_session_closed(Bundle()))

    def test_detector_failure_is_extracted_from_report(self) -> None:
        failure = detector_failure_from_report(
            {
                "strategies": {
                    "errors": {
                        "Z_DETECTOR": "salida invalida",
                        "A_DETECTOR": "ID no declarado",
                    }
                }
            }
        )

        self.assertIsInstance(failure, RuntimeError)
        self.assertIn("A_DETECTOR: ID no declarado", str(failure))
        self.assertIn("Z_DETECTOR: salida invalida", str(failure))
        self.assertLess(
            str(failure).index("A_DETECTOR"),
            str(failure).index("Z_DETECTOR"),
        )

    def test_report_without_detector_errors_has_no_failure(self) -> None:
        self.assertIsNone(
            detector_failure_from_report({"strategies": {"errors": {}}})
        )

    def test_invalid_strategy_contract_becomes_failure(self) -> None:
        failure = detector_failure_from_report({"strategies": []})
        self.assertIsInstance(failure, RuntimeError)

    def test_only_new_clean_analysis_resolves_processing_incidents(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = ScannerIncidentRepository(Path(directory) / "market.db")
            repository.record(
                symbol="SPY",
                bar_timestamp=START,
                error=RuntimeError("temporary"),
            )
            later_bar = MarketBar(
                "SPY",
                START + timedelta(minutes=14),
                1,
                2,
                1,
                1.5,
                10,
            )

            replay = reconcile_scanner_result_incidents(
                repository,
                bar=later_bar,
                result=None,
            )
            failing = reconcile_scanner_result_incidents(
                repository,
                bar=later_bar,
                result={
                    "report": {
                        "strategies": {
                            "errors": {"FAULTY": "contrato invalido"}
                        }
                    }
                },
            )
            clean = reconcile_scanner_result_incidents(
                repository,
                bar=MarketBar(
                    "SPY",
                    START + timedelta(minutes=29),
                    1,
                    2,
                    1,
                    1.5,
                    10,
                ),
                result={"report": {"strategies": {"errors": {}}}},
            )

            self.assertEqual(replay["resolved_count"], 0)
            self.assertIsNotNone(failing["incident_id"])
            self.assertEqual(failing["resolved_count"], 0)
            self.assertEqual(clean["resolved_count"], 2)
            self.assertEqual(repository.unresolved_count(symbols=("SPY",)), 0)

    def _scanner(self, database: Path, calls: list[str]):
        store = MarketBarStore(database)
        continuity = MarketContinuityService(
            store, UnusedProvider(), provider_name="ALPACA", feed="iex"
        )

        def evaluator(symbol, bundle):
            calls.append(symbol)
            self.assertEqual(set(bundle.datasets), {"15m", "1H", "1D"})
            self.assertEqual(set(bundle.auxiliary_datasets), {"1m"})
            return report(symbol)

        return ContinuousStrategyScanner(
            continuity,
            AlertRepository(database),
            feed="iex",
            evaluator=evaluator,
        )

    def test_only_scans_when_fifteen_minute_bar_closes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "market.db"
            calls = []
            scanner = self._scanner(database, calls)
            for minute in range(14):
                result = scanner.on_bar(
                    MarketBar("SPY", START + timedelta(minutes=minute), 1, 2, 1, 1.5, 10)
                )
                self.assertIsNone(result)

            result = scanner.on_bar(
                MarketBar("SPY", START + timedelta(minutes=14), 1, 2, 1, 1.5, 10)
            )

            self.assertEqual(calls, ["SPY"])
            self.assertEqual(result["report"]["decision"]["decision"], "NO_OPERAR")

    def test_replayed_closing_bar_does_not_duplicate_alert(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "market.db"
            calls = []
            scanner = self._scanner(database, calls)
            closing = MarketBar("SPY", START + timedelta(minutes=14), 1, 2, 1, 1.5, 10)

            first = scanner.on_bar(closing)
            second = scanner.on_bar(closing)

            self.assertIsNotNone(first)
            self.assertIsNone(second)
            self.assertEqual(calls, ["SPY"])
            self.assertEqual(len(AlertRepository(database).recent()), 1)

    def test_alert_repository_preserves_report(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = AlertRepository(Path(directory) / "alerts.db")

            alert_id = repository.record(
                provider="ALPACA",
                feed="iex",
                symbol="spy",
                trigger_timestamp=START,
                report=report("SPY"),
            )
            saved = repository.recent()[0]

            self.assertEqual(alert_id, saved["id"])
            self.assertEqual(saved["decision"], "NO_OPERAR")
            self.assertEqual(saved["detected_count"], 2)
            self.assertEqual(saved["report"]["symbol"], "SPY")

    def test_alert_acknowledgements_are_versioned_and_count_new_alerts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = AlertRepository(Path(directory) / "alerts.db")
            alert_id = repository.record(
                provider="ALPACA", feed="iex", symbol="SPY",
                trigger_timestamp=START, report=report("SPY"),
            )
            self.assertEqual(repository.unacknowledged_count(), 1)
            self.assertEqual(repository.recent_unacknowledged()[0]["id"], alert_id)
            viewed = repository.record_acknowledgement(alert_id, status="VISTA")
            attended = repository.record_acknowledgement(alert_id, status="ATENDIDA", notes="Revisada")
            self.assertEqual(repository.unacknowledged_count(), 0)
            self.assertEqual(repository.recent_unacknowledged(), [])
            self.assertEqual([item["id"] for item in repository.acknowledgements(alert_id)], [attended, viewed])

    def test_repository_keeps_unchanged_scan_without_repeating_attention(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = AlertRepository(Path(directory) / "alerts.db")
            first = repository.record(
                provider="ALPACA", feed="iex", symbol="SPY",
                trigger_timestamp=START, report=report("SPY"),
            )
            second = repository.record(
                provider="ALPACA", feed="iex", symbol="SPY",
                trigger_timestamp=START + timedelta(minutes=15), report=report("SPY"),
            )

            saved = repository.recent()
            self.assertEqual([item["id"] for item in saved], [second, first])
            self.assertEqual(saved[0]["event_type"], "SETUP_SIN_CAMBIO")
            self.assertFalse(saved[0]["requires_ack"])
            self.assertEqual(repository.unacknowledged_count(), 1)

    def test_scan_without_setup_is_saved_but_not_counted_as_new_alert(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = AlertRepository(Path(directory) / "alerts.db")
            payload = report("SPY")
            payload["strategy_summary"] = {"detected": 0, "confirmed": 0}
            alert_id = repository.record(
                provider="ALPACA", feed="iex", symbol="SPY",
                trigger_timestamp=START, report=payload,
            )
            saved = repository.recent()[0]
            self.assertEqual(saved["id"], alert_id)
            self.assertEqual(saved["event_type"], "SIN_SETUP")
            self.assertEqual(saved["report"]["alert_event"]["type"], "SIN_SETUP")
            self.assertEqual(repository.unacknowledged_count(), 0)
            self.assertEqual(repository.recent_unacknowledged(), [])

    def test_discarded_alert_requires_notes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = AlertRepository(Path(directory) / "alerts.db")
            alert_id = repository.record(
                provider="ALPACA", feed="iex", symbol="SPY",
                trigger_timestamp=START, report=report("SPY"),
            )
            with self.assertRaisesRegex(ValueError, "notas"):
                repository.record_acknowledgement(alert_id, status="DESCARTADA")

    def test_human_reviews_are_versioned_and_preserve_pending(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = AlertRepository(Path(directory) / "alerts.db")
            alert_id = repository.record(
                provider="ALPACA", feed="iex", symbol="SPY",
                trigger_timestamp=START, report=report("SPY"),
            )
            first = repository.record_human_review(
                alert_id, path_clear=True, news_clear=None,
                panorama_approved=None, notes="Primera revisión",
            )
            second = repository.record_human_review(
                alert_id, path_clear=True, news_clear=True,
                panorama_approved=True, notes="Completada",
            )

            reviews = repository.human_reviews(alert_id)
            self.assertEqual([item["id"] for item in reviews], [second, first])
            self.assertIsNone(reviews[1]["news_clear"])
            self.assertTrue(reviews[0]["panorama_approved"])

    def test_rejected_human_review_requires_notes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = AlertRepository(Path(directory) / "alerts.db")
            alert_id = repository.record(
                provider="ALPACA", feed="iex", symbol="SPY",
                trigger_timestamp=START, report=report("SPY"),
            )
            with self.assertRaisesRegex(ValueError, "notas"):
                repository.record_human_review(
                    alert_id, path_clear=False, news_clear=None,
                    panorama_approved=None,
                )

    def test_reevaluation_is_unique_per_alert_and_review(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = AlertRepository(Path(directory) / "alerts.db")
            alert_id = repository.record(provider="ALPACA", feed="iex", symbol="SPY", trigger_timestamp=START, report=report("SPY"))
            review_id = repository.record_human_review(alert_id, path_clear=True, news_clear=True, panorama_approved=True)
            payload = {"decision": {"decision": "NO_OPERAR"}, "review_id": review_id}
            first = repository.record_reevaluation(alert_id, review_id, payload)
            second = repository.record_reevaluation(alert_id, review_id, payload)
            self.assertIsNotNone(first)
            self.assertIsNone(second)
            self.assertEqual(len(repository.reevaluations(alert_id)), 1)

    def test_contract_selection_requires_candidate_to_be_eligible(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = AlertRepository(Path(directory) / "alerts.db")
            payload = report("SPY")
            payload["option_selection"] = {"candidates": [
                {"symbol": "GOOD", "eligible": True, "risk_status": "APROBADO"},
                {"symbol": "BAD", "eligible": False, "risk_status": "RECHAZADO"},
            ]}
            alert_id = repository.record(provider="ALPACA", feed="iex", symbol="SPY", trigger_timestamp=START, report=payload)
            selection_id = repository.record_contract_selection(alert_id, "GOOD", notes="Elegido")
            self.assertEqual(repository.contract_selections(alert_id)[0]["id"], selection_id)
            with self.assertRaisesRegex(ValueError, "no es elegible"):
                repository.record_contract_selection(alert_id, "BAD")
            with self.assertRaisesRegex(ValueError, "no pertenece"):
                repository.record_contract_selection(alert_id, "UNKNOWN")

    def test_governance_reviews_are_evaluated_and_versioned(self) -> None:
        from governance import GovernanceRequest, TradingMode

        with tempfile.TemporaryDirectory() as directory:
            repository = AlertRepository(Path(directory) / "alerts.db")
            alert_id = repository.record(provider="ALPACA", feed="iex", symbol="SPY", trigger_timestamp=START, report=report("SPY"))
            approved = repository.record_governance_review(
                alert_id,
                GovernanceRequest(symbol="SPY", watchlist_symbols=("SPY",), entry_plan="Entrada sobre nivel", exit_plan="Salida por invalidación"),
            )
            rejected = repository.record_governance_review(
                alert_id,
                GovernanceRequest(mode=TradingMode.REAL, symbol="SPY", watchlist_symbols=("SPY",), entry_plan="Entrada", exit_plan="Salida"),
            )
            reviews = repository.governance_reviews(alert_id)
            self.assertEqual([item["id"] for item in reviews], [rejected, approved])
            self.assertEqual(reviews[0]["status"], "RECHAZADO")
            self.assertEqual(reviews[1]["status"], "APROBADO")

    def test_reevaluation_versions_include_contract_and_governance(self) -> None:
        from governance import GovernanceRequest

        with tempfile.TemporaryDirectory() as directory:
            repository = AlertRepository(Path(directory) / "alerts.db")
            alert_id = repository.record(provider="ALPACA", feed="iex", symbol="SPY", trigger_timestamp=START, report=report("SPY"))
            review_id = repository.record_human_review(alert_id, path_clear=True, news_clear=True, panorama_approved=True)
            governance_id = repository.record_governance_review(
                alert_id,
                GovernanceRequest(
                    symbol="SPY",
                    watchlist_symbols=("SPY",),
                    entry_plan="Entrada",
                    exit_plan="Salida",
                ),
            )
            first = repository.record_reevaluation(alert_id, review_id, {"decision": {"decision": "NO_OPERAR"}, "review_id": review_id})
            second = repository.record_reevaluation(
                alert_id,
                review_id,
                {
                    "decision": {"decision": "CALL"},
                    "review_id": review_id,
                    "governance_review_id": governance_id,
                },
            )
            self.assertIsNotNone(first)
            self.assertIsNotNone(second)
            self.assertEqual(len(repository.reevaluations(alert_id)), 2)

    def test_reevaluation_rejects_foreign_evidence_ids(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = AlertRepository(Path(directory) / "alerts.db")
            first_alert = repository.record(
                provider="ALPACA", feed="iex", symbol="SPY",
                trigger_timestamp=START, report=report("SPY"),
            )
            second_alert = repository.record(
                provider="ALPACA", feed="iex", symbol="QQQ",
                trigger_timestamp=START, report=report("QQQ"),
            )
            first_review = repository.record_human_review(
                first_alert, path_clear=True, news_clear=True,
                panorama_approved=True,
            )
            second_review = repository.record_human_review(
                second_alert, path_clear=True, news_clear=True,
                panorama_approved=True,
            )

            with self.assertRaisesRegex(ValueError, "revision humana"):
                repository.record_reevaluation(
                    first_alert,
                    second_review,
                    {"decision": {"decision": "NO_OPERAR"}},
                )
            self.assertIsNotNone(first_review)

    def test_alert_outcome_is_linked_versioned_and_learning_uses_latest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = AlertRepository(Path(directory) / "alerts.db")
            payload = report("SPY")
            payload["strategies"] = {"evaluations": [{"strategy_id": "CT15", "detected": True, "required_criteria_satisfied": True}]}
            alert_id = repository.record(provider="ALPACA", feed="iex", symbol="SPY", trigger_timestamp=START, report=payload)
            review_id = repository.record_human_review(alert_id, path_clear=True, news_clear=True, panorama_approved=True)
            reevaluation_id = repository.record_reevaluation(
                alert_id,
                review_id,
                {
                    "decision": {"decision": "CALL"},
                    "review_id": review_id,
                    "visual_evidence": {"status": "APROBADO"},
                },
            )
            first = repository.record_outcome(alert_id, reevaluation_id, mode="PAPER", trade_taken=True, result="NEGATIVO", pnl=-25)
            second = repository.record_outcome(alert_id, reevaluation_id, mode="PAPER", trade_taken=True, result="POSITIVO", pnl=50, notes="Corrección")
            self.assertEqual([item["id"] for item in repository.outcomes(alert_id)], [second, first])
            learning = repository.alert_learning_records("PAPER")
            self.assertEqual(len(learning), 1)
            self.assertEqual(learning[0]["result"], "POSITIVO")
            self.assertEqual(learning[0]["strategies"], ["CT15"])
            self.assertIn("created_at", learning[0])
            self.assertEqual(learning[0]["event_at"], START.isoformat())
            self.assertEqual(learning[0]["methodology_version"], "test-1.0")
            self.assertEqual(learning[0]["visual_evidence_status"], "APROBADO")
            self.assertEqual(
                learning[0]["context"]["visual_confirmation"], "APROBADO"
            )

    def test_alert_outcome_rejects_inconsistent_not_taken_feedback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = AlertRepository(Path(directory) / "alerts.db")
            alert_id = repository.record(provider="ALPACA", feed="iex", symbol="SPY", trigger_timestamp=START, report=report("SPY"))
            review_id = repository.record_human_review(alert_id, path_clear=True, news_clear=True, panorama_approved=True)
            reevaluation_id = repository.record_reevaluation(alert_id, review_id, {"decision": {"decision": "NO_OPERAR"}, "review_id": review_id})
            with self.assertRaisesRegex(ValueError, "NO_OPERADA"):
                repository.record_outcome(alert_id, reevaluation_id, mode="PAPER", trade_taken=False, result="POSITIVO")

    def test_alert_outcome_mode_must_match_linked_governance(self) -> None:
        from governance import GovernanceRequest, TradingMode

        with tempfile.TemporaryDirectory() as directory:
            repository = AlertRepository(Path(directory) / "alerts.db")
            alert_id = repository.record(
                provider="ALPACA", feed="iex", symbol="SPY",
                trigger_timestamp=START, report=report("SPY"),
            )
            review_id = repository.record_human_review(
                alert_id, path_clear=True, news_clear=True,
                panorama_approved=True,
            )
            governance_id = repository.record_governance_review(
                alert_id,
                GovernanceRequest(
                    mode=TradingMode.REAL,
                    symbol="SPY",
                    watchlist_symbols=("SPY",),
                    entry_plan="Entrada",
                    exit_plan="Salida",
                    real_mode_acknowledged=True,
                ),
            )
            reevaluation_id = repository.record_reevaluation(
                alert_id,
                review_id,
                {
                    "decision": {"decision": "NO_OPERAR"},
                    "governance_review_id": governance_id,
                },
            )

            with self.assertRaisesRegex(ValueError, "no coincide"):
                repository.record_outcome(
                    alert_id, reevaluation_id, mode="PAPER",
                    trade_taken=True, result="POSITIVO",
                )
            outcome_id = repository.record_outcome(
                alert_id, reevaluation_id, mode="REAL",
                trade_taken=True, result="POSITIVO",
            )

        self.assertIsInstance(outcome_id, int)

    def test_real_outcome_requires_linked_real_governance(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = AlertRepository(Path(directory) / "alerts.db")
            alert_id = repository.record(
                provider="ALPACA", feed="iex", symbol="SPY",
                trigger_timestamp=START, report=report("SPY"),
            )
            review_id = repository.record_human_review(
                alert_id, path_clear=True, news_clear=True,
                panorama_approved=True,
            )
            reevaluation_id = repository.record_reevaluation(
                alert_id,
                review_id,
                {"decision": {"decision": "NO_OPERAR"}},
            )

            with self.assertRaisesRegex(ValueError, "requiere una revision"):
                repository.record_outcome(
                    alert_id, reevaluation_id, mode="REAL",
                    trade_taken=True, result="NEGATIVO",
                )

    def test_alert_identity_requires_timezone(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = AlertRepository(Path(directory) / "alerts.db")

            with self.assertRaisesRegex(ValueError, "zona horaria"):
                repository.exists(
                    provider="ALPACA",
                    feed="iex",
                    symbol="SPY",
                    trigger_timestamp=datetime(2026, 7, 20, 9, 30),
                )

    def test_optional_enricher_is_persisted_in_alert_report(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "market.db"
            calls = []
            store = MarketBarStore(database)
            continuity = MarketContinuityService(
                store, UnusedProvider(), provider_name="ALPACA", feed="iex"
            )
            scanner = ContinuousStrategyScanner(
                continuity,
                AlertRepository(database),
                feed="iex",
                evaluator=lambda symbol, bundle: report(symbol),
                report_enricher=lambda symbol, bundle, raw: {
                    **raw,
                    "option_selection": {"status": "SIN_SESGO"},
                },
            )

            scanner.on_bar(
                MarketBar("SPY", START + timedelta(minutes=14), 1, 2, 1, 1.5, 10)
            )

            saved = AlertRepository(database).recent()[0]["report"]
            self.assertEqual(saved["option_selection"]["status"], "SIN_SESGO")
            self.assertEqual(saved["live_data_freshness"]["status"], "RECHAZADO")
            self.assertEqual(saved["learning_advisory"]["authority"], "DESCRIPTIVA_NO_INFLUYE_DECISION")

    def test_current_closing_bar_records_approved_freshness(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "market.db"
            closing_time = START + timedelta(minutes=14)
            store = MarketBarStore(database)
            continuity = MarketContinuityService(
                store, UnusedProvider(), provider_name="ALPACA", feed="iex"
            )
            scanner = ContinuousStrategyScanner(
                continuity,
                AlertRepository(database),
                feed="iex",
                evaluator=lambda symbol, bundle: report(symbol),
                now=lambda: closing_time + timedelta(seconds=65),
            )

            result = scanner.on_bar(
                MarketBar("SPY", closing_time, 1, 2, 1, 1.5, 10)
            )

            self.assertEqual(
                result["report"]["live_data_freshness"]["status"], "APROBADO"
            )

    def test_queued_analysis_preserves_official_updated_bar(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database=Path(directory)/'market.db'
            store=MarketBarStore(database)
            continuity=MarketContinuityService(store,UnusedProvider(),provider_name='ALPACA',feed='iex')
            original=MarketBar('SPY',START,100,102,99,100,100)
            updated=MarketBar('SPY',START,100,102,99,101,120)
            store.upsert_bar(updated,provider='ALPACA',feed='iex')
            seen=[]
            def preview(symbol,bundle):
                seen.append(float(bundle.auxiliary_datasets['1m'].iloc[-1].close))
                return report(symbol)
            scanner=ContinuousStrategyScanner(continuity,AlertRepository(database),feed='iex',
                evaluator=lambda symbol,bundle:report(symbol),preview_evaluator=preview)
            scanner.on_bar(original,already_persisted=True)
            self.assertEqual(seen,[101.])
            saved=store.load_frame(symbol='SPY',provider='ALPACA',feed='iex')
            self.assertEqual(float(saved.iloc[-1].close),101.)
            self.assertEqual(float(saved.iloc[-1].volume),120.)

    def test_failed_rest_reconciliation_blocks_effective_freshness(self) -> None:
        class RejectedReconciler:
            def reconcile(self, symbol, *, start, end, local):
                return {"status": "RECHAZADO", "difference_count": 1, "differences": [{"field": "close"}], "detail": "No coincide."}

        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "market.db"
            store = MarketBarStore(database)
            continuity = MarketContinuityService(store, UnusedProvider(), provider_name="ALPACA", feed="iex")
            closing_time = START + timedelta(minutes=14)
            scanner = ContinuousStrategyScanner(
                continuity, AlertRepository(database), feed="iex",
                evaluator=lambda symbol, bundle: {**report(symbol), "freshness_seen": bundle.metadata["freshness_approved"]},
                now=lambda: closing_time + timedelta(seconds=30),
                reconciler=RejectedReconciler(),
            )
            for minute in range(15):
                result = scanner.on_bar(MarketBar("SPY", START + timedelta(minutes=minute), 1, 2, 1, 1.5, 10))
            self.assertFalse(result["report"]["freshness_seen"])
            self.assertEqual(result["report"]["live_data_freshness"]["status"], "RECHAZADO")
            self.assertEqual(result["report"]["market_data_reconciliation"]["status"], "RECHAZADO")
            from market_reconciliation import MarketReconciliationRepository
            saved = MarketReconciliationRepository(database).recent()
            self.assertEqual(saved[0]["status"], "RECHAZADO")
            self.assertEqual(result["report"]["market_data_reconciliation"]["id"], saved[0]["id"])

    def test_reconciliation_survives_evaluator_failure(self) -> None:
        class ApprovedReconciler:
            def reconcile(self, symbol, *, start, end, local):
                return {"status": "APROBADO", "difference_count": 0, "differences": [], "detail": "Coincide."}

        with tempfile.TemporaryDirectory() as directory:
            from market_reconciliation import MarketReconciliationRepository
            database = Path(directory) / "market.db"
            continuity = MarketContinuityService(MarketBarStore(database), UnusedProvider(), provider_name="ALPACA", feed="iex")
            scanner = ContinuousStrategyScanner(
                continuity, AlertRepository(database), feed="iex",
                evaluator=lambda symbol, bundle: (_ for _ in ()).throw(RuntimeError("falló evaluador")),
                reconciler=ApprovedReconciler(),
            )
            for minute in range(14):
                scanner.on_bar(MarketBar("SPY", START + timedelta(minutes=minute), 1, 2, 1, 1.5, 10))
            with self.assertRaisesRegex(RuntimeError, "evaluador"):
                scanner.on_bar(MarketBar("SPY", START + timedelta(minutes=14), 1, 2, 1, 1.5, 10))
            self.assertEqual(MarketReconciliationRepository(database).recent()[0]["status"], "APROBADO")


if __name__ == "__main__":
    unittest.main()
