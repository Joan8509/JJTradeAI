"""Pruebas end-to-end de todas las compuertas del análisis."""

import unittest

import pandas as pd
from pathlib import Path

from analysis_models import DirectionBias, FinalDecision, GateStatus, StrategyEvaluation
from analysis_pipeline import DETECTOR_REGISTRY, AnalysisContext, DetectorDefinition
from assessment_service import assess_market
from data_loader import load_tc2000_txt
from indicators import add_bollinger_metrics, add_gap_metrics, calculate_bollinger


def _datasets(*, daily_day: str = "2026-06-24") -> dict[str, pd.DataFrame]:
    frame_15m = pd.DataFrame(
        {
            "date": ["2026-06-23 15:45", "2026-06-24 09:30"],
            "open": [96.0, 99.0], "high": [98.0, 101.0], "low": [95.0, 98.5], "close": [97.0, 100.0],
            "moving_average_20": [98.0, 98.5], "moving_average_40": [99.0, 98.0],
            "moving_average_100": [100.0, 97.0], "moving_average_200": [101.0, 96.0],
            "bollinger_mid": [98.0, 98.5], "bollinger_upper": [101.0, 102.0], "bollinger_lower": [95.0, 94.5],
            "bollinger_mid_slope": [-0.2, 0.5], "bollinger_upper_change": [0.0, 1.0],
            "bollinger_lower_change": [0.0, -0.5], "bollinger_both_expanding": [False, True],
        }
    )
    hourly = pd.DataFrame(
        {
            "date": ["2026-06-24 09:30"], "open": [99.0], "high": [101.0], "low": [98.0], "close": [100.0],
            "moving_average_20": [98.0], "moving_average_40": [97.0], "moving_average_100": [96.0], "moving_average_200": [95.0],
            "bollinger_mid": [98.0], "bollinger_upper": [103.0], "bollinger_lower": [93.0],
            "bollinger_mid_slope": [0.5], "bollinger_upper_change": [1.0], "bollinger_lower_change": [-1.0],
            "bollinger_both_expanding": [True],
        }
    )
    daily = pd.DataFrame(
        {
            "date": [f"{daily_day} 00:00"], "open": [99.0], "high": [101.0], "low": [98.0], "close": [100.0],
            "moving_average_20": [98.0], "moving_average_40": [97.0], "moving_average_100": [96.0], "moving_average_200": [95.0],
            "bollinger_mid": [98.0], "bollinger_upper": [103.0], "bollinger_lower": [93.0],
            "bollinger_mid_slope": [0.5], "bollinger_upper_change": [1.0], "bollinger_lower_change": [-1.0],
            "bollinger_both_expanding": [True],
        }
    )
    return {"15m": frame_15m, "1H": hourly, "1D": daily}


class AssessmentServiceTests(unittest.TestCase):
    def test_confirmed_ct15_and_all_gates_can_produce_call(self) -> None:
        context = AnalysisContext(
            datasets=_datasets(),
            reviews={
                "ct15.prior_trend": True,
                "ct15.trendline_drawn": True,
                "ct15.trendline_broken": True,
            },
        )
        result = assess_market(
            context,
            panorama_path_clear=True,
            news_clear=True,
            panorama_human_approval=True,
            data_current_review=True,
            risk_status=GateStatus.APROBADO,
            risk_option_type="CALL",
            governance_status=GateStatus.APROBADO,
        )

        self.assertIs(result.decision.decision, FinalDecision.CALL)
        self.assertIn("CT15_ALCISTA@15m", result.decision.supporting_strategies)

    def test_pending_common_invalidations_prevent_final_entry(self) -> None:
        context = AnalysisContext(
            datasets=_datasets(),
            reviews={
                "ct15.prior_trend": True,
                "ct15.trendline_drawn": True,
                "ct15.trendline_broken": True,
            },
        )
        pending_reviews = (
            {"news_clear": None, "data_current_review": True},
            {"news_clear": True, "data_current_review": None},
        )

        for reviews in pending_reviews:
            with self.subTest(**reviews):
                result = assess_market(
                    context,
                    panorama_path_clear=True,
                    news_clear=reviews["news_clear"],
                    panorama_human_approval=True,
                    data_current_review=reviews["data_current_review"],
                    risk_status=GateStatus.APROBADO,
                    risk_option_type="CALL",
                    governance_status=GateStatus.APROBADO,
                )

                self.assertIs(result.decision.decision, FinalDecision.NO_OPERAR)
                self.assertTrue(
                    any(
                        reason.startswith(
                            "Hay invalidaciones pendientes de revisión:"
                        )
                        for reason in result.decision.reasons
                    )
                )

    def test_misaligned_data_forces_no_operar(self) -> None:
        context = AnalysisContext(
            datasets=_datasets(daily_day="2026-06-23"),
            reviews={
                "ct15.prior_trend": True,
                "ct15.trendline_drawn": True,
                "ct15.trendline_broken": True,
            },
        )
        result = assess_market(
            context,
            panorama_path_clear=True,
            news_clear=True,
            panorama_human_approval=True,
            data_current_review=True,
            risk_status=GateStatus.APROBADO,
            risk_option_type="CALL",
            governance_status=GateStatus.APROBADO,
        )

        self.assertIs(result.decision.decision, FinalDecision.NO_OPERAR)
        self.assertIs(result.data_quality.status, GateStatus.RECHAZADO)
        self.assertIs(result.decision.data_quality_status, GateStatus.RECHAZADO)
        self.assertIn("La calidad de datos no está aprobada.", result.decision.reasons)

    def test_opposite_option_contract_rejects_risk_gate(self) -> None:
        context = AnalysisContext(
            datasets=_datasets(),
            reviews={
                "ct15.prior_trend": True,
                "ct15.trendline_drawn": True,
                "ct15.trendline_broken": True,
            },
        )
        result = assess_market(
            context,
            panorama_path_clear=True,
            news_clear=True,
            panorama_human_approval=True,
            data_current_review=True,
            risk_status=GateStatus.APROBADO,
            risk_option_type="PUT",
            governance_status=GateStatus.APROBADO,
        )

        self.assertIs(result.decision.decision, FinalDecision.NO_OPERAR)
        self.assertIs(result.decision.risk_status, GateStatus.RECHAZADO)

    def test_risk_option_type_is_normalized_before_direction_match(self) -> None:
        context = AnalysisContext(
            datasets=_datasets(),
            reviews={
                "ct15.prior_trend": True,
                "ct15.trendline_drawn": True,
                "ct15.trendline_broken": True,
            },
        )
        result = assess_market(
            context,
            panorama_path_clear=True,
            news_clear=True,
            panorama_human_approval=True,
            data_current_review=True,
            risk_status=GateStatus.APROBADO,
            risk_option_type=" call ",
            governance_status=GateStatus.APROBADO,
        )

        self.assertIs(result.decision.decision, FinalDecision.CALL)
        self.assertIs(result.decision.risk_status, GateStatus.APROBADO)

    def test_approved_risk_without_contract_direction_is_not_enough(self) -> None:
        context = AnalysisContext(
            datasets=_datasets(),
            reviews={
                "ct15.prior_trend": True,
                "ct15.trendline_drawn": True,
                "ct15.trendline_broken": True,
            },
        )
        result = assess_market(
            context,
            panorama_path_clear=True,
            news_clear=True,
            panorama_human_approval=True,
            data_current_review=True,
            risk_status=GateStatus.APROBADO,
            governance_status=GateStatus.APROBADO,
        )

        self.assertIs(result.decision.decision, FinalDecision.NO_OPERAR)
        self.assertIs(result.decision.risk_status, GateStatus.NO_DISPONIBLE)

    def test_project_sample_txt_runs_through_full_service(self) -> None:
        path = Path(__file__).resolve().parents[1] / "exports" / "sample.txt"
        frame = add_gap_metrics(add_bollinger_metrics(calculate_bollinger(load_tc2000_txt(path))))
        result = assess_market(
            AnalysisContext(datasets={"15m": frame, "1H": frame, "1D": frame}),
            panorama_path_clear=True,
            news_clear=True,
            panorama_human_approval=True,
            data_current_review=True,
        )

        self.assertIsInstance(result.decision.decision, FinalDecision)

    def test_detector_contract_error_rejects_quality_and_final_decision(self) -> None:
        faulty = DetectorDefinition(
            detector_id="FAULTY",
            strategy_ids=("DECLARED",),
            diagnostic_ids=("SIN_FAULTY",),
            required_timeframes=("15m",),
            minimum_rows=(("15m", 1),),
            evaluate=lambda context: (
                StrategyEvaluation(
                    "UNDECLARED",
                    "Salida invalida",
                    DirectionBias.CALL,
                    True,
                ),
            ),
        )
        context = AnalysisContext(
            datasets=_datasets(),
            reviews={
                "ct15.prior_trend": True,
                "ct15.trendline_drawn": True,
                "ct15.trendline_broken": True,
            },
        )

        result = assess_market(
            context,
            panorama_path_clear=True,
            news_clear=True,
            panorama_human_approval=True,
            data_current_review=True,
            risk_status=GateStatus.APROBADO,
            risk_option_type="CALL",
            governance_status=GateStatus.APROBADO,
            detectors=(*DETECTOR_REGISTRY, faulty),
        )

        self.assertIn("FAULTY", result.pipeline.errors)
        self.assertIs(result.data_quality.status, GateStatus.RECHAZADO)
        self.assertTrue(
            any(
                issue.startswith("Error interno del detector FAULTY:")
                for issue in result.data_quality.issues
            )
        )
        self.assertIs(result.decision.decision, FinalDecision.NO_OPERAR)
        self.assertIs(
            result.decision.data_quality_status,
            GateStatus.RECHAZADO,
        )


if __name__ == "__main__":
    unittest.main()
