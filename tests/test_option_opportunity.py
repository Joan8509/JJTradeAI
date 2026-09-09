"""Pruebas de política externa y enriquecimiento de alertas."""

from datetime import date
import json
from pathlib import Path
import tempfile
import unittest

import pandas as pd

from data_providers import DataBundle, DataProviderKind
from option_market_data import OptionSnapshot
from option_opportunity import (
    OptionOpportunityPolicy,
    OptionOpportunityService,
    load_option_opportunity_policy,
)
from option_market_data import OptionSelectionPolicy
from risk_engine import RiskLimits


def policy_payload() -> dict:
    return {
        "option_feed": "opra",
        "max_search_dte": 14,
        "max_spread_absolute": 0.10,
        "max_spread_pct": 10,
        "max_spot_strike_distance_pct": 2,
        "min_days_to_expiration": 2,
        "max_position_cost": 200,
        "min_bid_size": 10,
        "min_ask_size": 10,
        "min_delta": 0.35,
        "max_delta": 0.65,
        "max_results": 5,
    }


def policy() -> OptionOpportunityPolicy:
    return OptionOpportunityPolicy(
        option_feed="opra",
        max_search_dte=14,
        selection=OptionSelectionPolicy(
            risk_limits=RiskLimits(0.10, 10, 2, 2, 200),
            min_bid_size=10,
            min_ask_size=10,
            min_delta=0.35,
            max_delta=0.65,
        ),
    )


def bundle() -> DataBundle:
    return DataBundle(
        DataProviderKind.MARKET_DATA_API,
        {"15m": pd.DataFrame({"close": [600.0]})},
        {},
    )


class FakeOptionProvider:
    option_feed = "opra"

    def __init__(self) -> None:
        self.calls = []

    def fetch_chain(self, symbol, **kwargs):
        self.calls.append((symbol, kwargs))
        return (
            OptionSnapshot(
                "SPY260724C00600000",
                "SPY",
                "CALL",
                600,
                date(2026, 7, 24),
                1,
                1.05,
                20,
                20,
                None,
                1.02,
                0.2,
                0.5,
                0.1,
                -0.1,
                0.1,
                "opra",
            ),
        )


class OptionOpportunityTests(unittest.TestCase):
    def test_loads_complete_strict_policy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "policy.json"
            path.write_text(json.dumps(policy_payload()), encoding="utf-8")

            result = load_option_opportunity_policy(path)

            self.assertEqual(result.option_feed, "opra")
            self.assertEqual(result.selection.min_bid_size, 10)

    def test_rejects_missing_or_unknown_policy_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "policy.json"
            payload = policy_payload()
            del payload["max_delta"]
            payload["secret_threshold"] = 1
            path.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "Faltan campos"):
                load_option_opportunity_policy(path)

    def test_no_bias_does_not_query_option_provider(self) -> None:
        provider = FakeOptionProvider()
        service = OptionOpportunityService(provider, policy())

        result = service.enrich(
            "SPY",
            bundle(),
            {"data_as_of": "2026-07-20T14:00:00Z", "decision": {"decision": "NO_OPERAR"}},
        )

        self.assertEqual(result["option_selection"]["status"], "SIN_SESGO")
        self.assertEqual(provider.calls, [])

    def test_tentative_bias_queries_and_attaches_candidates(self) -> None:
        provider = FakeOptionProvider()
        service = OptionOpportunityService(provider, policy())

        result = service.enrich(
            "SPY",
            bundle(),
            {
                "data_as_of": "2026-07-20T14:00:00Z",
                "decision": {"decision": "NO_OPERAR", "tentative_bias": "CALL"},
            },
        )

        selection = result["option_selection"]
        self.assertEqual(selection["status"], "CANDIDATOS")
        self.assertEqual(selection["eligible_count"], 1)
        self.assertTrue(selection["candidates"][0]["eligible"])
        self.assertEqual(provider.calls[0][1]["option_type"], "call")


if __name__ == "__main__":
    unittest.main()
