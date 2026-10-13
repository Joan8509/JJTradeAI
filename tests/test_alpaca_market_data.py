"""Pruebas del adaptador Alpaca sin conectarse a servicios externos."""

from datetime import datetime, timedelta, timezone
import os
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import pandas as pd

from alpaca_market_data import (
    AlpacaMarketConfig,
    AlpacaMarketDataProvider,
    AlpacaStockBarStream,
    alpaca_messages_to_bars,
    build_alpaca_data_bundle,
)
from data_providers import DataProviderKind


START = datetime(2026, 7, 20, 13, 30, tzinfo=timezone.utc)
END = datetime(2026, 7, 20, 20, 0, tzinfo=timezone.utc)


class AlpacaMarketDataTests(unittest.TestCase):
    def test_one_socket_subscribes_bars_and_trades_and_handles_corrections(self):
        sockets,subscriptions,trades,bars,statuses=[],[],[],[],[]
        class Socket:
            def __init__(self,url,**callbacks):
                self.callbacks=callbacks
                sockets.append(self)
            def send(self,data):
                subscriptions.append(json.loads(data))
            def run_forever(self,**kwargs):
                self.callbacks['on_open'](self)
                self.callbacks['on_message'](self,json.dumps([{'T':'success','msg':'authenticated'}]))
                self.assert_not_connected_yet=not statuses
                self.callbacks['on_message'](self,json.dumps([{'T':'subscription','trades':['AAPL'],'bars':['AAPL']}]))
                self.callbacks['on_message'](self,json.dumps([
                    {'T':'t','S':'AAPL','p':100,'s':100,'c':['@'],'z':'C','i':1,'t':START.isoformat()},
                    {'T':'c','S':'AAPL','oi':1,'cp':99}, {'T':'x','S':'AAPL','i':1},
                    {'T':'b','S':'AAPL','t':START.isoformat(),'o':99,'h':100,'l':99,'c':100,'v':100}]))
            def close(self):
                pass
        with patch.dict('sys.modules',{'websocket':SimpleNamespace(WebSocketApp=Socket)}):
            AlpacaStockBarStream(AlpacaMarketConfig('key','secret'),on_trade_message=trades.append).run(
                ['AAPL'],bars.append,on_status=statuses.append)
        self.assertEqual(len(sockets),1)
        self.assertTrue(sockets[0].assert_not_connected_yet)
        self.assertEqual(subscriptions[1],{'action':'subscribe','bars':['AAPL'],'updatedBars':['AAPL'],'trades':['AAPL']})
        self.assertEqual([message['T'] for message in trades],['t','c','x'])
        self.assertEqual(len(bars),1)
        self.assertEqual(statuses,['CONECTADO'])

    def test_config_requires_credentials(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, "ALPACA_API_KEY"):
                AlpacaMarketConfig.from_env()

    def test_config_builds_feed_specific_stream_url(self) -> None:
        config = AlpacaMarketConfig("key", "secret", feed="sip")

        self.assertTrue(config.stock_stream_url.endswith("/v2/sip"))

    def test_fetch_bars_paginates_and_does_not_expose_credentials(self) -> None:
        calls = []

        def transport(request):
            calls.append(request)
            if len(calls) == 1:
                return {
                    "bars": [{"t": "2026-07-20T13:30:00Z", "o": 1, "h": 2, "l": 1, "c": 2, "v": 10}],
                    "next_page_token": "next",
                }
            return {
                "bars": [{"t": "2026-07-20T13:31:00Z", "o": 2, "h": 3, "l": 2, "c": 3, "v": 20}],
                "next_page_token": None,
            }

        provider = AlpacaMarketDataProvider(
            AlpacaMarketConfig("key", "secret"), transport=transport
        )
        result = provider.fetch_minute_bars("spy", start=START, end=END)

        self.assertEqual(len(result), 2)
        self.assertEqual(len(calls), 2)
        self.assertIn("page_token=next", calls[1].full_url)
        self.assertNotIn("secret", calls[0].full_url)

    def test_fetch_bundle_returns_canonical_timeframes(self) -> None:
        bars = []
        for minute in range(60):
            timestamp = START + timedelta(minutes=minute)
            price = 100 + minute
            bars.append({"t": timestamp.isoformat(), "o": price, "h": price + 1, "l": price - 1, "c": price + 0.5, "v": 10})

        provider = AlpacaMarketDataProvider(
            AlpacaMarketConfig("key", "secret"),
            transport=lambda request: {"bars": bars, "next_page_token": None},
        )
        result = provider.fetch_bundle("SPY", start=START, end=END)

        self.assertIs(result.provider, DataProviderKind.MARKET_DATA_API)
        self.assertEqual(set(result.datasets), {"15m", "1H", "1D"})
        self.assertEqual(set(result.auxiliary_datasets), {"1m"})
        self.assertEqual(len(result.auxiliary_datasets["1m"]), 60)
        self.assertEqual(result.metadata["symbol"], "SPY")
        self.assertNotIn("api_key", result.metadata)
        self.assertIn("bollinger_mid", result.datasets["15m"].columns)
        self.assertIn("moving_average_200", result.datasets["1D"].columns)
        self.assertTrue(result.datasets["1D"].empty)
        self.assertIn("15m", result.metadata["closed_through"])
        self.assertIn("1H", result.metadata["closed_through"])
        self.assertNotIn("1D", result.metadata["closed_through"])

    def test_stream_messages_ignore_control_events(self) -> None:
        result = alpaca_messages_to_bars(
            [
                {"T": "success", "msg": "authenticated"},
                {"T": "b", "S": "SPY", "t": "2026-07-20T13:30:00Z", "o": 1, "h": 2, "l": 1, "c": 1.5, "v": 10},
            ]
        )

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].symbol, "SPY")

    def test_stream_messages_accept_late_updated_bars(self) -> None:
        result = alpaca_messages_to_bars(
            [
                {
                    "T": "u", "S": "SPY",
                    "t": "2026-07-20T13:30:00Z",
                    "o": 1, "h": 2, "l": 1, "c": 1.6, "v": 12,
                },
            ]
        )

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].close, 1.6)
        self.assertEqual(result[0].volume, 12)

    def test_builds_bundle_from_previously_persisted_minutes(self) -> None:
        bars = []
        for minute in range(60):
            price = 100 + minute
            bars.append({
                "date": START + timedelta(minutes=minute),
                "open": price,
                "high": price + 1,
                "low": price - 1,
                "close": price + 0.5,
                "volume": 10,
            })

        result = build_alpaca_data_bundle(
            pd.DataFrame(bars), symbol="spy", feed="iex"
        )

        self.assertEqual(set(result.datasets), {"15m", "1H", "1D"})
        self.assertEqual(set(result.auxiliary_datasets), {"1m"})
        self.assertEqual(result.metadata["symbol"], "SPY")


if __name__ == "__main__":
    unittest.main()
