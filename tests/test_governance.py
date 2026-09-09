"""Pruebas de los controles operativos independientes de las estrategias."""

import unittest

from analysis_models import GateStatus
from governance import (
    GovernanceLimits,
    GovernanceRequest,
    OperationWorkflow,
    TradingMode,
    evaluate_governance,
)


class GovernanceTests(unittest.TestCase):
    def test_paper_new_entry_with_plan_is_approved(self) -> None:
        result = evaluate_governance(
            GovernanceRequest(
                watchlist_symbols=("SPY", "TSLA"),
                new_trades_this_week=2,
                entry_plan="Entrar solo después de la confirmación.",
                exit_plan="Salir al invalidarse la estructura.",
            )
        )

        self.assertIs(result.status, GateStatus.APROBADO)
        self.assertEqual(result.reasons, ())

    def test_missing_plans_and_weekly_limit_reject_new_entry(self) -> None:
        result = evaluate_governance(GovernanceRequest(new_trades_this_week=3))

        self.assertIs(result.status, GateStatus.RECHAZADO)
        self.assertEqual(len(result.reasons), 3)

    def test_watchlist_limit_counts_normalized_unique_symbols(self) -> None:
        approved = evaluate_governance(
            GovernanceRequest(
                watchlist_symbols=("spy", " SPY ", "qqq"),
                entry_plan="Plan.",
                exit_plan="Salida.",
            )
        )
        rejected = evaluate_governance(
            GovernanceRequest(
                watchlist_symbols=("SPY", "QQQ", "TSLA", "AAPL"),
                entry_plan="Plan.",
                exit_plan="Salida.",
            )
        )

        self.assertIs(approved.status, GateStatus.APROBADO)
        self.assertIs(rejected.status, GateStatus.RECHAZADO)

    def test_real_mode_requires_explicit_acknowledgement(self) -> None:
        result = evaluate_governance(
            GovernanceRequest(
                mode=TradingMode.REAL,
                workflow=OperationWorkflow.GESTION_POSICION,
            )
        )

        self.assertIs(result.status, GateStatus.RECHAZADO)
        self.assertIn("aceptación humana", result.reasons[0])

    def test_reinforcement_is_not_enabled(self) -> None:
        result = evaluate_governance(
            GovernanceRequest(workflow=OperationWorkflow.REFUERZO)
        )

        self.assertIs(result.status, GateStatus.RECHAZADO)

    def test_invalid_limits_raise_error(self) -> None:
        with self.assertRaises(ValueError):
            evaluate_governance(
                GovernanceRequest(), GovernanceLimits(max_watchlist_symbols=0)
            )
