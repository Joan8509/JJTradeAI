"""Pruebas del orquestador común de detectores."""

import unittest
from pathlib import Path

import pandas as pd

from analysis_models import DirectionBias, StrategyEvaluation
from analysis_pipeline import (
    DETECTOR_REGISTRY,
    AnalysisContext,
    DetectorDefinition,
    run_detection_pipeline,
)
from strategy_registry import STRATEGY_REGISTRY
from validation_runner import load_tc2000_bundle


class AnalysisPipelineTests(unittest.TestCase):
    def test_missing_timeframes_are_reported_as_skipped(self) -> None:
        frame = pd.DataFrame(
            {"close": [10.0], "bollinger_upper": [11.0], "bollinger_lower": [9.0]}
        )

        report = run_detection_pipeline(AnalysisContext(datasets={"15m": frame}))

        self.assertEqual(len(report.evaluations), 1)
        self.assertIn("PRIMER_SALTO", report.skipped)
        self.assertIn("EFECTO_IMAN", report.skipped)

    def test_detector_data_errors_are_visible_without_stopping_pipeline(self) -> None:
        invalid_daily = pd.DataFrame({"open": [10.0], "close": [10.0]})

        report = run_detection_pipeline(
            AnalysisContext(datasets={"1D": invalid_daily})
        )

        self.assertIn("EXPUESTO_BOLLINGER", report.errors)
        self.assertIn("PRIMER_SALTO", report.skipped)

    def test_declared_short_history_is_skipped_instead_of_internal_error(self) -> None:
        primer_salto = next(
            item
            for item in DETECTOR_REGISTRY
            if item.detector_id == "PRIMER_SALTO"
        )
        daily = pd.DataFrame({"date": ["2026-07-27"], "open": [10.0]})

        report = run_detection_pipeline(
            AnalysisContext(datasets={"1H": pd.DataFrame({"value": [1]}), "1D": daily}),
            detectors=(primer_salto,),
        )

        self.assertIn("Historial insuficiente", report.skipped["PRIMER_SALTO"])
        self.assertNotIn("PRIMER_SALTO", report.errors)

    def test_pipeline_outputs_are_registered_strategies(self) -> None:
        sample_path = Path(__file__).resolve().parents[1] / "exports" / "sample.txt"
        datasets = load_tc2000_bundle(
            timeframe_15m=sample_path,
            timeframe_1h=sample_path,
            timeframe_1d=sample_path,
        )

        report = run_detection_pipeline(AnalysisContext(datasets=datasets))
        missing_detected = [
            evaluation.strategy_id
            for evaluation in report.evaluations
            if evaluation.detected and evaluation.strategy_id not in STRATEGY_REGISTRY
        ]
        invalid_diagnostics = [
            evaluation.strategy_id
            for evaluation in report.evaluations
            if not evaluation.detected
            and evaluation.strategy_id not in STRATEGY_REGISTRY
            and not evaluation.strategy_id.startswith("SIN_")
        ]

        self.assertFalse(missing_detected)
        self.assertFalse(invalid_diagnostics)
        self.assertTrue(all(item.timeframe for item in report.evaluations))

    def test_multitimeframe_exposure_evaluations_keep_their_timeframe(self) -> None:
        frame = pd.DataFrame(
            {"close": [10.0], "bollinger_upper": [11.0], "bollinger_lower": [9.0]}
        )
        report = run_detection_pipeline(
            AnalysisContext(
                datasets={"15m": frame, "1H": frame, "1D": frame}
            )
        )
        exposure_evaluations = [
            item
            for item in report.evaluations
            if item.strategy_id.startswith("SIN_EXPUESTO_BOLLINGER")
        ]

        self.assertEqual(
            {item.timeframe for item in exposure_evaluations},
            {"15m", "1H", "1D"},
        )

    def test_undeclared_strategy_output_is_rejected_before_aggregation(self) -> None:
        detector = DetectorDefinition(
            "TEST",
            ("DECLARED",),
            ("SIN_TEST",),
            ("15m",),
            (("15m", 1),),
            lambda context: (
                StrategyEvaluation(
                    "UNDECLARED", "Incorrecta", DirectionBias.CALL, True
                ),
            ),
        )

        report = run_detection_pipeline(
            AnalysisContext(datasets={"15m": pd.DataFrame({"value": [1]})}),
            detectors=(detector,),
        )

        self.assertEqual(report.evaluations, ())
        self.assertIn("ID no declarado", report.errors["TEST"])

    def test_detected_or_directional_diagnostic_output_is_rejected(self) -> None:
        detector = DetectorDefinition(
            "TEST",
            ("DECLARED",),
            ("SIN_TEST",),
            ("15m",),
            (("15m", 1),),
            lambda context: (
                StrategyEvaluation(
                    "SIN_TEST", "Diagnostico", DirectionBias.CALL, True
                ),
            ),
        )

        report = run_detection_pipeline(
            AnalysisContext(datasets={"15m": pd.DataFrame({"value": [1]})}),
            detectors=(detector,),
        )

        self.assertIn("debe ser neutral", report.errors["TEST"])

    def test_duplicate_detector_output_is_rejected(self) -> None:
        evaluation = StrategyEvaluation(
            "SIN_TEST", "Diagnostico", DirectionBias.NEUTRAL, False
        )
        detector = DetectorDefinition(
            "TEST",
            ("DECLARED",),
            ("SIN_TEST",),
            ("15m",),
            (("15m", 1),),
            lambda context: (evaluation, evaluation),
        )

        report = run_detection_pipeline(
            AnalysisContext(datasets={"15m": pd.DataFrame({"value": [1]})}),
            detectors=(detector,),
        )

        self.assertIn("Salida duplicada", report.errors["TEST"])

    def test_explicit_wrong_output_timeframe_is_rejected(self) -> None:
        detector = DetectorDefinition(
            "TEST",
            ("DECLARED",),
            ("SIN_TEST",),
            ("15m",),
            (("15m", 1),),
            lambda context: (
                StrategyEvaluation(
                    "SIN_TEST",
                    "Diagnostico",
                    DirectionBias.NEUTRAL,
                    False,
                    timeframe="1D",
                ),
            ),
        )

        report = run_detection_pipeline(
            AnalysisContext(datasets={"15m": pd.DataFrame({"value": [1]})}),
            detectors=(detector,),
        )

        self.assertIn("Temporalidad de salida invalida", report.errors["TEST"])


if __name__ == "__main__":
    unittest.main()
