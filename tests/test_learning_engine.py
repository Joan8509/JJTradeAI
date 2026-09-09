"""Pruebas del aprendizaje estadístico controlado."""

import unittest
from datetime import datetime, timezone

from learning_engine import LearningPolicy, TemporalValidationPolicy, audit_learning_advisory, build_learning_advisory, evaluate_temporal_stability, summarize_alert_feedback, summarize_context_performance, summarize_strategy_performance


class LearningEngineTests(unittest.TestCase):
    def test_metrics_remain_uncalibrated_without_approved_sample_policy(self) -> None:
        records = [
            {
                "strategies": ["CT15"],
                "mode": "PAPER",
                "pnl": 50,
                "decision": "CALL",
                "decision_followed": 1,
            },
            {
                "strategies": ["CT15"],
                "mode": "PAPER",
                "pnl": -20,
                "decision": "NO_OPERAR",
                "decision_followed": 0,
            },
        ]

        result = summarize_strategy_performance(records)[0]

        self.assertEqual(result["sample_size"], 2)
        self.assertEqual(result["observed_win_rate"], 50.0)
        self.assertEqual(result["profit_factor"], 2.5)
        self.assertEqual(result["sample_status"], "SIN_UMBRAL_APROBADO")
        self.assertEqual(result["confidence"], "NO_CALIBRADA")
        self.assertEqual(result["decision_call_count"], 1)
        self.assertEqual(result["decision_put_count"], 0)
        self.assertEqual(result["decision_no_operar_count"], 1)
        self.assertEqual(result["human_override_count"], 1)

    def test_explicit_sample_policy_can_mark_sufficient_sample(self) -> None:
        records = [
            {"strategies": ["CT15"], "mode": "PAPER", "pnl": 10, "decision_followed": 1},
            {"strategies": ["CT15"], "mode": "PAPER", "pnl": 5, "decision_followed": 1},
        ]

        result = summarize_strategy_performance(
            records, LearningPolicy(minimum_sample_size=2)
        )[0]

        self.assertEqual(result["sample_status"], "MUESTRA_MINIMA_ALCANZADA")
        self.assertEqual(result["confidence"], "NO_CALIBRADA")

    def test_paper_and_real_are_separate_groups(self) -> None:
        records = [
            {"strategies": ["CT15"], "mode": "PAPER", "pnl": 10, "decision_followed": 1},
            {"strategies": ["CT15"], "mode": "REAL", "pnl": -10, "decision_followed": 1},
        ]

        result = summarize_strategy_performance(records)

        self.assertEqual(len(result), 2)

    def test_missing_decision_followed_is_counted_as_not_followed(self) -> None:
        records = [
            {
                "strategies": ["CT15"],
                "mode": "PAPER",
                "pnl": 10,
                "decision_followed": None,
            }
        ]

        result = summarize_strategy_performance(records)[0]

        self.assertEqual(result["decision_followed_rate"], 0.0)
        self.assertEqual(result["human_override_count"], 1)

    def test_alert_feedback_excludes_not_taken_and_separates_modes(self) -> None:
        records = [
            {"strategies": ["CT15"], "mode": "PAPER", "trade_taken": True, "result": "POSITIVO", "pnl": 40},
            {"strategies": ["CT15"], "mode": "PAPER", "trade_taken": False, "result": "NO_OPERADA", "pnl": None},
            {"strategies": ["CT15"], "mode": "REAL", "trade_taken": True, "result": "NEGATIVO", "pnl": -20},
        ]
        result = summarize_alert_feedback(records)
        self.assertEqual(len(result), 2)
        paper = next(item for item in result if item["mode"] == "PAPER")
        self.assertEqual(paper["sample_size"], 1)
        self.assertEqual(paper["observed_positive_rate"], 100.0)
        self.assertEqual(paper["confidence"], "DESCRIPTIVA_NO_PREDICTIVA")

    def test_context_calibration_requires_minimum_sample(self) -> None:
        record = {"strategies": ["CT15"], "mode": "PAPER", "trade_taken": True, "result": "POSITIVO", "context": {"trend_15m": "ALCISTA"}}
        insufficient = summarize_context_performance([record], LearningPolicy(minimum_sample_size=2))
        trend = next(item for item in insufficient if item["context_dimension"] == "trend_15m")
        self.assertFalse(trend["eligible_for_calibration"])
        sufficient = summarize_context_performance([record, record], LearningPolicy(minimum_sample_size=2))
        trend = next(item for item in sufficient if item["context_dimension"] == "trend_15m")
        self.assertTrue(trend["eligible_for_calibration"])

    def test_visual_confirmation_is_descriptive_context_only(self) -> None:
        record = {
            "strategies": ["CT15"],
            "mode": "PAPER",
            "trade_taken": True,
            "result": "POSITIVO",
            "context": {"visual_confirmation": "APROBADO"},
        }

        result = summarize_context_performance(
            [record],
            LearningPolicy(minimum_sample_size=10),
        )
        visual = next(
            item
            for item in result
            if item["context_dimension"] == "visual_confirmation"
        )

        self.assertEqual(visual["context_value"], "APROBADO")
        self.assertFalse(visual["eligible_for_calibration"])
        self.assertEqual(visual["confidence"], "DESCRIPTIVA_NO_PREDICTIVA")

    def test_temporal_validation_detects_non_overlapping_degradation(self) -> None:
        records = []
        for index in range(15):
            records.append({
                "outcome_id": index + 1, "created_at": f"2026-01-{index + 1:02d}",
                "strategies": ["CT15"], "mode": "PAPER", "methodology_version": "1.0",
                "trade_taken": True, "result": "POSITIVO" if index < 10 else "NEGATIVO",
            })
        result = evaluate_temporal_stability(
            records,
            TemporalValidationPolicy(training_fraction=2 / 3, minimum_training_size=10, minimum_test_size=5),
        )[0]
        self.assertEqual(result["training_positive_rate"], 100.0)
        self.assertEqual(result["test_positive_rate"], 0.0)
        self.assertEqual(result["status"], "DEGRADACION_OBSERVADA")
        self.assertTrue(result["out_of_sample"])

    def test_temporal_validation_keeps_versions_and_modes_separate(self) -> None:
        records = [
            {"outcome_id": 1, "created_at": "2026-01-01", "strategies": ["CT15"], "mode": mode, "methodology_version": version, "trade_taken": True, "result": "POSITIVO"}
            for mode, version in (("PAPER", "1.0"), ("REAL", "1.0"), ("PAPER", "2.0"))
        ]
        result = evaluate_temporal_stability(records)
        self.assertEqual(len(result), 3)
        self.assertTrue(all(item["status"] == "MUESTRA_TEMPORAL_INSUFICIENTE" for item in result))

    def test_learning_advisory_excludes_outcomes_not_known_at_alert_time(self) -> None:
        records = [
            {"outcome_id": 1, "created_at": "2026-01-01T12:00:00+00:00", "event_at": "2026-01-01T10:00:00+00:00", "methodology_version": "1.0", "strategies": ["CT15"], "mode": "PAPER", "trade_taken": True, "result": "POSITIVO", "context": {"trend_15m": "ALCISTA"}},
            {"outcome_id": 2, "created_at": "2026-01-03T12:00:00+00:00", "event_at": "2026-01-03T10:00:00+00:00", "methodology_version": "1.0", "strategies": ["CT15"], "mode": "PAPER", "trade_taken": True, "result": "NEGATIVO", "context": {"trend_15m": "ALCISTA"}},
            {"outcome_id": 3, "created_at": "2026-01-01T12:00:00+00:00", "event_at": "2026-01-01T10:00:00+00:00", "methodology_version": "1.0", "strategies": ["CT15"], "mode": "REAL", "trade_taken": True, "result": "NEGATIVO", "context": {"trend_15m": "ALCISTA"}},
            {"outcome_id": 4, "created_at": "2026-01-01T12:00:00+00:00", "event_at": "2026-01-01T10:00:00+00:00", "methodology_version": "2.0", "strategies": ["CT15"], "mode": "PAPER", "trade_taken": True, "result": "NEGATIVO", "context": {"trend_15m": "ALCISTA"}},
            {"outcome_id": 5, "created_at": "2026-01-01T12:00:00+00:00", "event_at": "2026-01-02T10:00:00+00:00", "methodology_version": "1.0", "strategies": ["CT15"], "mode": "PAPER", "trade_taken": True, "result": "NEGATIVO", "context": {"trend_15m": "ALCISTA"}},
        ]
        advisory = build_learning_advisory(
            records, strategy_ids=["CT15"], context={"trend_15m": "ALCISTA"},
            as_of=datetime(2026, 1, 2, tzinfo=timezone.utc),
            methodology_version="1.0", minimum_sample_size=1,
        )
        self.assertEqual(advisory["known_outcome_count"], 2)
        paper_general = next(item for item in advisory["rows"] if item["mode"] == "PAPER" and item["context_dimension"] == "GENERAL")
        real_general = next(item for item in advisory["rows"] if item["mode"] == "REAL" and item["context_dimension"] == "GENERAL")
        self.assertEqual(paper_general["observed_positive_rate"], 100.0)
        self.assertEqual(real_general["observed_positive_rate"], 0.0)
        self.assertEqual(advisory["authority"], "DESCRIPTIVA_NO_INFLUYE_DECISION")
        self.assertEqual(advisory["methodology_version"], "1.0")
        self.assertEqual(advisory["policy_version"], "LEARNING_ADVISORY_V2")
        self.assertEqual(len(advisory["history_fingerprint_sha256"]), 64)
        self.assertEqual(advisory["source_outcome_ids"], [1, 3])

    def test_learning_advisory_requires_timezone(self) -> None:
        with self.assertRaisesRegex(ValueError, "zona horaria"):
            build_learning_advisory(
                [], strategy_ids=[], context={}, as_of=datetime(2026, 1, 1),
                methodology_version="1.0",
            )

    def test_learning_advisory_requires_methodology_version(self) -> None:
        with self.assertRaisesRegex(ValueError, "methodology_version"):
            build_learning_advisory(
                [],
                strategy_ids=[],
                context={},
                as_of=datetime(2026, 1, 1, tzinfo=timezone.utc),
                methodology_version=" ",
            )

    def test_learning_advisory_audit_detects_later_correction(self) -> None:
        original_records = [{
            "outcome_id": 1, "created_at": "2026-01-01T12:00:00+00:00", "event_at": "2026-01-01T10:00:00+00:00",
            "methodology_version": "1.0",
            "strategies": ["CT15"], "mode": "PAPER", "trade_taken": True,
            "result": "POSITIVO", "context": {"trend_15m": "ALCISTA"},
        }]
        advisory = build_learning_advisory(
            original_records, strategy_ids=["CT15"], context={"trend_15m": "ALCISTA"},
            as_of=datetime(2026, 1, 2, tzinfo=timezone.utc),
            methodology_version="1.0", minimum_sample_size=1,
        )
        reproducible = audit_learning_advisory(
            advisory, original_records, strategy_ids=["CT15"], context={"trend_15m": "ALCISTA"}
        )
        self.assertEqual(reproducible["status"], "REPRODUCIBLE")
        corrected = [{**original_records[0], "outcome_id": 2, "result": "NEGATIVO"}]
        changed = audit_learning_advisory(
            advisory, corrected, strategy_ids=["CT15"], context={"trend_15m": "ALCISTA"}
        )
        self.assertEqual(changed["status"], "HISTORIAL_CAMBIO")
        self.assertNotEqual(changed["stored_fingerprint"], changed["current_fingerprint"])

    def test_old_advisory_without_fingerprint_is_not_auditable(self) -> None:
        result = audit_learning_advisory(
            {"as_of": "2026-01-01T00:00:00+00:00", "minimum_sample_size": 10},
            [], strategy_ids=[], context={},
        )
        self.assertEqual(result["status"], "NO_AUDITABLE")


if __name__ == "__main__":
    unittest.main()
