from datetime import datetime, timedelta, timezone
import unittest

from signal_entry_research import evaluate_entry_path


START = datetime(2026, 10, 6, 14, 59, tzinfo=timezone.utc)


class SignalEntryResearchTests(unittest.TestCase):
    def bars(self):
        return [{"timestamp": (START + timedelta(minutes=m)).isoformat(),
                 "open": 105, "high": 110, "low": 104, "close": 108} for m in range(20)]

    def evaluate(self, **changes):
        args = dict(available_at=START + timedelta(minutes=1, seconds=20), trigger=START,
                    bias="CALL", horizon=15, bars=self.bars(), as_of=START + timedelta(minutes=20))
        args.update(changes)
        return evaluate_entry_path(**args)

    def test_entry_after_signal_uses_open_and_exact_horizon_close(self):
        result = self.evaluate()
        self.assertEqual(result["status"], "EVALUADA")
        self.assertEqual(result["entry_timestamp"], (START + timedelta(minutes=2)).isoformat())
        self.assertEqual(result["exit_timestamp"], (START + timedelta(minutes=17)).isoformat())
        self.assertEqual(result["entry_price"], 105)
        self.assertEqual(result["exit_price"], 108)
        self.assertEqual(result["entry_delay_seconds"], 40)

    def test_missing_bar_does_not_invent_path(self):
        bars = self.bars()
        del bars[7]
        self.assertEqual(self.evaluate(bars=bars)["status"], "DATOS_INCOMPLETOS")

    def test_unfinished_exit_bar_is_not_used(self):
        self.assertEqual(self.evaluate(as_of=START + timedelta(minutes=16, seconds=59))["status"], "HORIZONTE_PENDIENTE")

    def test_backfilled_old_signal_is_not_given_historical_entry(self):
        self.assertEqual(self.evaluate(available_at=START + timedelta(days=1))["status"], "REGISTRO_RETROACTIVO")

    def test_put_reverses_return(self):
        self.assertEqual(self.evaluate(bias="PUT")["directional_return_pct"], -self.evaluate()["directional_return_pct"])

    def test_invalid_prices_are_not_scored(self):
        bars = self.bars()
        bars[5]["open"] = float("inf")
        self.assertEqual(self.evaluate(bars=bars)["status"], "DATOS_INVALIDOS")

    def test_crossing_regular_session_close_is_excluded(self):
        late = datetime(2026, 10, 6, 19, 55, tzinfo=timezone.utc)
        self.assertEqual(self.evaluate(trigger=late, available_at=late + timedelta(minutes=1))["status"], "FUERA_DE_SESION")


if __name__ == "__main__":
    unittest.main()
