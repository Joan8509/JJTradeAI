from datetime import datetime, timedelta, timezone
import unittest
import json
import sqlite3
from contextlib import closing

from strategy_research import build_filter_experiments, candidate_outcomes, summarize_research, summarize_detector_coverage


START = datetime(2026, 9, 1, 14, 0, tzinfo=timezone.utc)


def evidence(alert_id, *, start=START, symbol="SPY", version="v1", result=1.0):
    return {
        "alert_id": alert_id, "entry_timestamp": start.isoformat(),
        "exit_timestamp": (start + timedelta(minutes=60)).isoformat(),
        "symbol": symbol, "provider": "ALPACA", "feed": "iex",
        "strategy_id": "TEST", "bias": "CALL", "horizon_minutes": 60,
        "methodology_version": version, "directional_return_pct": result,
        "favorable_excursion_pct": 1.0, "adverse_excursion_pct": -1.0,
    }


class StrategyResearchTests(unittest.TestCase):
    def experiment_rows(self, days=10):
        rows = []
        for day in range(days):
            for index in range(4):
                row = evidence(day * 4 + index, start=START + timedelta(days=day, hours=index),
                               result=1 if index < 2 else -1)
                row["context"] = {"trend_15m": "BAJISTA" if index < 2 else "LATERAL",
                                  "session_segment": "APERTURA" if index < 2 else "MEDIA_SESION"}
                rows.append(row)
        return rows

    def test_experiments_keep_original_hypothesis_and_historical_samples(self):
        initial = build_filter_experiments(self.experiment_rows(), cohort="CONFIRMADAS",
                                          as_of=START + timedelta(days=10), frozen=[])
        original = next(item for item in initial if item["rule"] == "EVITAR_LATERAL")
        later = build_filter_experiments(self.experiment_rows(days=20), cohort="CONFIRMADAS",
                                        as_of=START + timedelta(days=20), frozen=initial)
        updated = next(item for item in later if item["rule"] == "EVITAR_LATERAL")
        self.assertEqual(updated["frozen_at"], original["frozen_at"])
        self.assertEqual(updated["historical_training"], original["historical_training"])
        self.assertEqual(updated["historical_test"], original["historical_test"])
        self.assertEqual(updated["forward_test"]["baseline"]["session_count"], 9)
        self.assertEqual(updated["forward_test"]["filtered"]["sample_size"], 18)

    def test_future_samples_do_not_include_registration_session(self):
        rows = self.experiment_rows()
        initial = build_filter_experiments(rows, cohort="CONFIRMADAS", as_of=START + timedelta(days=9), frozen=[])
        self.assertTrue(all(item["forward_test"]["baseline"]["sample_size"] == 0 for item in initial))

    def test_holdout_outcomes_do_not_change_training_results(self):
        rows = self.experiment_rows()
        initial = build_filter_experiments(rows, cohort="CONFIRMADAS", as_of=START + timedelta(days=10), frozen=[])
        for row in rows:
            if datetime.fromisoformat(row["entry_timestamp"]) >= START + timedelta(days=7):
                row["directional_return_pct"] = -20
        changed = build_filter_experiments(rows, cohort="CONFIRMADAS", as_of=START + timedelta(days=10), frozen=[])
        self.assertEqual(initial[0]["historical_training"], changed[0]["historical_training"])
        self.assertNotEqual(initial[0]["historical_test"], changed[0]["historical_test"])

    def test_unknown_context_is_excluded_from_both_filter_and_baseline(self):
        rows = self.experiment_rows()
        for row in rows:
            row["context"] = {}
        experiments = build_filter_experiments(rows, cohort="CANDIDATAS", as_of=START + timedelta(days=10), frozen=[])
        self.assertTrue(all(item["historical_training"]["baseline"]["sample_size"] == 0 for item in experiments))
        self.assertTrue(all(item["historical_test"]["status"] == "MUESTRA_INSUFICIENTE" for item in experiments))

    def test_relative_improvement_with_negative_return_is_not_labeled_positive(self):
        rows = self.experiment_rows(days=20)
        for row in rows:
            index = row["alert_id"] % 4
            row["directional_return_pct"] = 1 if index == 0 else -2 if index == 1 else -3
        experiments = build_filter_experiments(rows, cohort="CONFIRMADAS", as_of=START + timedelta(days=20), frozen=[])
        filtered = next(item for item in experiments if item["rule"] == "EVITAR_LATERAL")
        self.assertEqual(filtered["historical_test"]["status"], "MEJORA_RELATIVA_RETORNO_NEGATIVO")

    def test_overlapping_windows_do_not_inflate_research_sample(self):
        result = summarize_research([
            evidence(1), evidence(2, start=START + timedelta(minutes=15)),
            evidence(3, start=START + timedelta(minutes=60), result=-1),
            evidence(4, symbol="QQQ"),
        ])[0]
        self.assertEqual(result["all_evaluations"]["sample_size"], 4)
        self.assertEqual(result["non_overlapping"]["sample_size"], 3)
        self.assertEqual(result["non_overlapping"]["negative_count"], 1)

    def test_temporal_split_never_splits_a_session(self):
        rows = [evidence(day * 2 + i, start=START + timedelta(days=day, hours=i), result=1 if day < 7 else -1)
                for day in range(10) for i in range(2)]
        result = summarize_research(list(reversed(rows)))[0]
        self.assertEqual(result["prior_period"]["session_count"], 7)
        self.assertEqual(result["recent_period"]["session_count"], 3)
        self.assertEqual(result["prior_period"]["positive_rate_pct"], 100)
        self.assertEqual(result["recent_period"]["positive_rate_pct"], 0)

    def test_versions_are_kept_separate(self):
        self.assertEqual(len(summarize_research([evidence(1), evidence(2, version="v2")])), 2)

    def test_empty_evidence(self):
        self.assertEqual(summarize_research([]), [])

    def test_coverage_includes_all_eight_strategies_without_results(self):
        coverage = summarize_detector_coverage([])
        self.assertEqual(sum(not item["complementary"] for item in coverage), 8)
        self.assertEqual(len(coverage), 9)
        self.assertTrue(all(item["confirmed_scans"] == 0 for item in coverage))

    def test_coverage_distinguishes_no_detection_pending_and_errors(self):
        payload = {"strategies": {"evaluations": [
            {"strategy_id": "SIN_CT15", "detected": False},
            {"strategy_id": "MOMENTUM_ALCISTA", "detected": True, "bias": "CALL",
             "criteria": [{"required": True, "criterion_id": "path", "status": "NO_DISPONIBLE"}]},
        ], "skipped": {"PRIMER_SALTO": "Falta 1D"}, "errors": {"EFECTO_IMAN": "Error"}}}
        coverage = {item["detector_id"]: item for item in summarize_detector_coverage([
            {"symbol": "SPY", "trigger_timestamp": START.isoformat(), "payload_json": json.dumps(payload)}
        ])}
        self.assertEqual(coverage["CT15"]["evaluated_scans"], 1)
        self.assertEqual(coverage["CT15"]["detected_scans"], 0)
        self.assertEqual(coverage["MOMENTUM"]["latest_status_counts"], {"CANDIDATA_PENDIENTE": 1})
        self.assertEqual(coverage["MOMENTUM"]["confirmed_scans"], 0)
        self.assertEqual(coverage["MOMENTUM"]["blockers"][0]["criterion"], "path")
        self.assertEqual(coverage["PRIMER_SALTO"]["skipped_scans"], 1)
        self.assertEqual(coverage["EFECTO_IMAN"]["error_scans"], 1)

    def test_candidate_research_excludes_confirmed_and_missing_or_future_closes(self):
        payload = {"methodology_version": "v1", "strategies": {"evaluations": [
            {"strategy_id": "MOMENTUM_ALCISTA", "detected": True, "bias": "CALL",
             "criteria": [{"required": True, "status": "NO_DISPONIBLE"}]},
            {"strategy_id": "CT15_ALCISTA", "detected": True, "bias": "CALL",
             "criteria": [{"required": True, "status": "CUMPLE"}]},
        ]}}
        with closing(sqlite3.connect(":memory:")) as connection:
            connection.row_factory = sqlite3.Row
            connection.executescript(
                "CREATE TABLE strategy_alerts (id, symbol, provider, feed, trigger_timestamp, payload_json, detected_count, created_at);"
                "CREATE TABLE minute_bars (symbol, provider, feed, timestamp, high, low, close);"
            )
            connection.execute("INSERT INTO strategy_alerts VALUES (1,'SPY','ALPACA','iex',?,?,2,?)",
                               (START.isoformat(), json.dumps(payload), START.isoformat()))
            # 16 no reemplaza el cierre ausente a 15; 60 está en el futuro.
            for minute in (0, 16, 30, 60):
                connection.execute("INSERT INTO minute_bars VALUES ('SPY','ALPACA','iex',?,102,99,101)",
                                   ((START + timedelta(minutes=minute)).isoformat(),))
            rows, pending = candidate_outcomes(connection, START + timedelta(minutes=30))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["strategy_id"], "MOMENTUM_ALCISTA")
            self.assertEqual(rows[0]["horizon_minutes"], 30)
            self.assertEqual(pending, 2)

    def test_missing_data_without_detection_is_counted_once_per_scan(self):
        criterion = {"criterion_id": "news_clear", "name": "Noticias", "required": True, "status": "NO_DISPONIBLE"}
        payload = {"strategies": {"evaluations": [
            {"strategy_id": "PRIMER_SALTO_RESPETADO_ALCISTA", "detected": False, "criteria": [criterion]},
            {"strategy_id": "PRIMER_SALTO_RESPETADO_BAJISTA", "detected": False, "criteria": [criterion]},
        ]}}
        coverage = summarize_detector_coverage([
            {"symbol": "SPY", "trigger_timestamp": START.isoformat(), "payload_json": json.dumps(payload)}
        ])
        result = next(item for item in coverage if item["detector_id"] == "PRIMER_SALTO")
        self.assertEqual(result["detected_scans"], 0)
        self.assertEqual(result["unavailable_requirements"][0]["scan_count"], 1)
        self.assertEqual(len(result["latest_by_symbol"]["SPY"]["unavailable_requirements"]), 1)


if __name__ == "__main__":
    unittest.main()
