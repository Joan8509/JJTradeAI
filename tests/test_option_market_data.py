"""Pruebas de cadena y selección de opciones Alpaca."""

from datetime import date
import unittest

from alpaca_market_data import AlpacaMarketConfig
from option_market_data import (
    AlpacaOptionDataProvider,
    OptionSelectionPolicy,
    select_option_candidates,
)
from risk_engine import RiskLimits


def snapshot_payload(symbol: str, *, delta: float = 0.5) -> dict:
    return {
        "snapshots": {
            symbol: {
                "latestQuote": {
                    "bp": 1.00,
                    "ap": 1.05,
                    "bs": 25,
                    "as": 30,
                    "t": "2026-07-20T15:00:00Z",
                },
                "latestTrade": {"p": 1.02},
                "impliedVolatility": 0.22,
                "greeks": {
                    "delta": delta,
                    "gamma": 0.03,
                    "theta": -0.04,
                    "vega": 0.10,
                },
            }
        },
        "next_page_token": None,
    }


def policy() -> OptionSelectionPolicy:
    return OptionSelectionPolicy(
        risk_limits=RiskLimits(
            max_spread_absolute=0.10,
            max_spread_pct=10,
            max_spot_strike_distance_pct=2,
            min_days_to_expiration=2,
            max_position_cost=200,
        ),
        min_bid_size=10,
        min_ask_size=10,
        min_delta=0.35,
        max_delta=0.65,
    )


class OptionMarketDataTests(unittest.TestCase):
    def test_fetch_chain_parses_occ_quote_and_greeks(self) -> None:
        requests = []

        def transport(request):
            requests.append(request)
            return snapshot_payload("SPY260724C00600000")

        provider = AlpacaOptionDataProvider(
            AlpacaMarketConfig("key", "secret"),
            option_feed="opra",
            transport=transport,
        )
        result = provider.fetch_chain(
            "spy",
            option_type="call",
            expiration_date_gte=date(2026, 7, 22),
            expiration_date_lte=date(2026, 7, 31),
            strike_price_gte=590,
            strike_price_lte=610,
        )

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].option_type, "CALL")
        self.assertEqual(result[0].strike, 600)
        self.assertEqual(result[0].expiration, date(2026, 7, 24))
        self.assertEqual(result[0].delta, 0.5)
        self.assertIn("type=call", requests[0].full_url)
        self.assertIn("strike_price_gte=590", requests[0].full_url)
        self.assertNotIn("secret", requests[0].full_url)

    def test_chain_paginates(self) -> None:
        calls = []

        def transport(request):
            calls.append(request)
            payload = snapshot_payload(
                "SPY260724C00600000" if len(calls) == 1 else "SPY260724C00601000"
            )
            payload["next_page_token"] = "next" if len(calls) == 1 else None
            return payload

        provider = AlpacaOptionDataProvider(
            AlpacaMarketConfig("key", "secret"), transport=transport
        )
        result = provider.fetch_chain(
            "SPY",
            option_type="call",
            expiration_date_gte=date(2026, 7, 20),
            expiration_date_lte=date(2026, 7, 31),
        )

        self.assertEqual(len(result), 2)
        self.assertIn("page_token=next", calls[1].full_url)

    def test_opra_candidate_can_be_eligible(self) -> None:
        provider = AlpacaOptionDataProvider(
            AlpacaMarketConfig("key", "secret"),
            option_feed="opra",
            transport=lambda request: snapshot_payload("SPY260724C00600000"),
        )
        chain = provider.fetch_chain(
            "SPY",
            option_type="call",
            expiration_date_gte=date(2026, 7, 20),
            expiration_date_lte=date(2026, 7, 31),
        )

        result = select_option_candidates(
            chain, spot=600, policy=policy(), as_of=date(2026, 7, 20)
        )

        self.assertTrue(result[0].eligible)

    def test_indicative_quote_is_never_marked_eligible(self) -> None:
        provider = AlpacaOptionDataProvider(
            AlpacaMarketConfig("key", "secret"),
            option_feed="indicative",
            transport=lambda request: snapshot_payload("SPY260724C00600000"),
        )
        chain = provider.fetch_chain(
            "SPY",
            option_type="call",
            expiration_date_gte=date(2026, 7, 20),
            expiration_date_lte=date(2026, 7, 31),
        )

        result = select_option_candidates(
            chain, spot=600, policy=policy(), as_of=date(2026, 7, 20)
        )

        self.assertFalse(result[0].eligible)

    def test_missing_delta_fails_delta_gate(self) -> None:
        payload = snapshot_payload("SPY260724P00600000", delta=-0.5)
        payload["snapshots"]["SPY260724P00600000"]["greeks"] = {}
        provider = AlpacaOptionDataProvider(
            AlpacaMarketConfig("key", "secret"),
            option_feed="opra",
            transport=lambda request: payload,
        )
        chain = provider.fetch_chain(
            "SPY",
            option_type="put",
            expiration_date_gte=date(2026, 7, 20),
            expiration_date_lte=date(2026, 7, 31),
        )

        result = select_option_candidates(
            chain, spot=600, policy=policy(), as_of=date(2026, 7, 20)
        )

        self.assertFalse(result[0].delta_approved)
        self.assertFalse(result[0].eligible)


if __name__ == "__main__":
    unittest.main()
