import unittest
from datetime import datetime, timezone
import pandas as pd
from bollinger_strategy_study import evaluate_event, replay_events, summarize


class BollingerStudyTests(unittest.TestCase):
    def event(self, side="SUPERIOR"):
        return {"symbol": "AAPL", "provider": "ALPACA", "feed": "iex", "side": side,
                "source_timestamp": "2026-10-08T14:00:00+00:00", "detected_at": "2026-10-08T14:01:00+00:00",
                "price": 100, "origin": "RECONSTRUIDA"}

    def bars(self, price=101):
        return pd.DataFrame({"open": [100.]*5, "high": [max(100,price)+1.]*5,
                             "low": [min(100,price)-1.]*5, "close": [float(price)]*5},
                            index=pd.date_range("2026-10-08T14:01:00Z", periods=5, freq="min"))

    def evaluate(self, event, bars, now="2026-10-08T15:00:00Z", close="2026-10-08T20:00:00Z"):
        return evaluate_event(event, bars, pd.Timestamp(close), as_of=pd.Timestamp(now), horizon=5)

    def test_continuation_and_reversal_for_both_directions(self):
        for side, price in (("SUPERIOR",101),("INFERIOR",99)):
            positive = self.evaluate(self.event(side), self.bars(price))
            negative = self.evaluate(self.event(side), self.bars(200-price))
            self.assertEqual(positive["result"], "POSITIVO")
            self.assertEqual(negative["result"], "NEGATIVO")
            self.assertAlmostEqual(positive["directional_return_pct"], 1)

    def test_missing_minute_does_not_count_as_positive(self):
        result = self.evaluate(self.event(), self.bars().iloc[1:])
        self.assertEqual(result["status"], "DATOS_INCOMPLETOS")

    def test_trade_with_seconds_uses_first_full_minute_after_detection(self):
        event={**self.event(),'origin':'EN_VIVO','source_kind':'TRADE',
               'source_timestamp':'2026-10-08T14:00:20.123456+00:00',
               'detected_at':'2026-10-08T14:00:21+00:00'}
        result=self.evaluate(event,self.bars())
        self.assertEqual(result['start'],'2026-10-08T14:01:00+00:00')
        self.assertEqual(result['result'],'POSITIVO')

    def test_future_and_market_close_are_excluded(self):
        self.assertEqual(self.evaluate(self.event(), self.bars(), now="2026-10-08T14:04:00Z")["status"], "PENDIENTE")
        self.assertEqual(self.evaluate(self.event(), self.bars(), close="2026-10-08T14:05:00Z")["status"], "SIN_RECORRIDO_ANTES_DEL_CIERRE")

    def test_overlapping_events_not_counted_twice_and_live_separate(self):
        row = self.evaluate(self.event(), self.bars())
        live = {**row, "origin": "EN_VIVO"}
        summary = summarize([row, dict(row), live])
        self.assertEqual(len(summary), 2)
        self.assertTrue(all(r["sample"] == 1 for r in summary))
        self.assertTrue(all(r["status"] == "MUESTRA_INSUFICIENTE" for r in summary))

    def test_replay_does_not_use_future_partial_candle_close(self):
        dates = pd.date_range("2026-10-08T13:30:00Z", periods=330, freq="min")
        prices = [100.+(i//15 % 2)*.1 for i in range(330)]
        prices[305:310] = [103.]*5
        bars = pd.DataFrame({"date": dates, "open": prices, "high": prices, "low": prices, "close": prices, "volume": 10})
        full = replay_events(bars, symbol="TEST", provider="ALPACA", feed="iex")
        partial = replay_events(bars.iloc[:310], symbol="TEST", provider="ALPACA", feed="iex")
        self.assertTrue(partial)
        cutoff = dates[309] + pd.Timedelta(minutes=1)
        self.assertEqual([r for r in full if pd.Timestamp(r["detected_at"]) <= cutoff], partial)
