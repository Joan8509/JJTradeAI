"""Pruebas para la compuerta configurable de opciones."""

from datetime import date
import unittest

from analysis_models import GateStatus
from risk_engine import OptionQuote, RiskLimits, evaluate_option_risk


class RiskEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.quote = OptionQuote(
            symbol="SPY",
            option_type="CALL",
            spot=600.0,
            strike=602.0,
            bid=1.00,
            ask=1.05,
            expiration=date(2026, 7, 3),
        )

    def test_complete_limits_can_approve(self) -> None:
        limits = RiskLimits(
            max_spread_absolute=0.10,
            max_spread_pct=10.0,
            max_spot_strike_distance_pct=1.0,
            min_days_to_expiration=2,
            max_position_cost=200.0,
        )
        result = evaluate_option_risk(
            self.quote, limits, as_of=date(2026, 6, 24)
        )
        self.assertEqual(result.status, GateStatus.APROBADO)

    def test_option_type_is_normalized(self) -> None:
        quote = OptionQuote(
            symbol="SPY",
            option_type=" call ",
            spot=600.0,
            strike=602.0,
            bid=1.00,
            ask=1.05,
            expiration=date(2026, 7, 3),
        )
        limits = RiskLimits(
            max_spread_absolute=0.10,
            max_spread_pct=10.0,
            max_spot_strike_distance_pct=1.0,
            min_days_to_expiration=2,
            max_position_cost=200.0,
        )

        result = evaluate_option_risk(quote, limits, as_of=date(2026, 6, 24))

        self.assertEqual(result.status, GateStatus.APROBADO)

    def test_missing_limits_are_not_approved(self) -> None:
        result = evaluate_option_risk(
            self.quote, RiskLimits(), as_of=date(2026, 6, 24)
        )
        self.assertEqual(result.status, GateStatus.NO_DISPONIBLE)
        self.assertTrue(
            all("no configurado" in criterion.detail for criterion in result.criteria[1:])
        )
        self.assertFalse(any("None" in criterion.detail for criterion in result.criteria))

    def test_excessive_spread_is_rejected(self) -> None:
        limits = RiskLimits(
            max_spread_absolute=0.01,
            max_spread_pct=1.0,
            max_spot_strike_distance_pct=1.0,
            min_days_to_expiration=2,
            max_position_cost=200.0,
        )
        result = evaluate_option_risk(
            self.quote, limits, as_of=date(2026, 6, 24)
        )
        self.assertEqual(result.status, GateStatus.RECHAZADO)

    def test_expired_contract_is_rejected_even_without_limits(self) -> None:
        expired = OptionQuote(
            symbol="SPY",
            option_type="CALL",
            spot=600.0,
            strike=602.0,
            bid=1.00,
            ask=1.05,
            expiration=date(2026, 6, 20),
        )

        result = evaluate_option_risk(
            expired, RiskLimits(), as_of=date(2026, 6, 24)
        )

        self.assertEqual(result.status, GateStatus.RECHAZADO)

    def test_negative_limits_are_invalid_configuration(self) -> None:
        with self.assertRaises(ValueError):
            evaluate_option_risk(
                self.quote,
                RiskLimits(max_spread_absolute=-0.01),
                as_of=date(2026, 6, 24),
            )

        with self.assertRaises(ValueError):
            evaluate_option_risk(
                self.quote,
                RiskLimits(min_days_to_expiration=-1),
                as_of=date(2026, 6, 24),
            )

    def test_zero_strike_is_invalid_quote(self) -> None:
        quote = OptionQuote(
            symbol="SPY",
            option_type="CALL",
            spot=600.0,
            strike=0.0,
            bid=1.00,
            ask=1.05,
            expiration=date(2026, 7, 3),
        )

        with self.assertRaises(ValueError):
            evaluate_option_risk(
                quote,
                RiskLimits(max_spread_absolute=0.10),
                as_of=date(2026, 6, 24),
            )


if __name__ == "__main__":
    unittest.main()
