"""Pruebas del diario local y sus estadísticas descriptivas."""

from pathlib import Path
from datetime import datetime, timezone
import tempfile
import unittest

from journal import JournalRepository


class JournalRepositoryTests(unittest.TestCase):
    def test_records_trade_and_builds_statistics(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = JournalRepository(Path(directory) / "journal.db")
            analysis_id = repository.record_analysis(
                symbol="spy",
                data_as_of="2026-06-24",
                methodology_version="draft",
                decision="CALL",
                confidence="NO_CALIBRADA",
                strategies=["TEST_STRATEGY"],
                payload={"reason": "test"},
            )
            trade_id = repository.record_trade(
                analysis_id=analysis_id,
                action="CALL",
                contracts=1,
                entry_price=1.0,
            )
            repository.close_trade(trade_id, exit_price=1.5, fees=1.0)

            self.assertEqual(
                repository.strategy_statistics(),
                [
                    {
                        "strategy_id": "TEST_STRATEGY",
                        "operations": 1,
                        "win_rate": 100.0,
                        "total_pnl": 49.0,
                    }
                ],
            )

    def test_closed_trade_cannot_be_closed_again(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = JournalRepository(Path(directory) / "journal.db")
            analysis_id = repository.record_analysis(
                symbol="SPY",
                data_as_of="2026-06-24",
                methodology_version="draft",
                decision="CALL",
                confidence="NO_CALIBRADA",
                strategies=["TEST"],
                payload={},
            )
            trade_id = repository.record_trade(
                analysis_id=analysis_id,
                action="CALL",
                contracts=1,
                entry_price=1.0,
            )
            repository.close_trade(trade_id, exit_price=1.5)

            with self.assertRaises(ValueError):
                repository.close_trade(trade_id, exit_price=2.0)

    def test_learning_records_ignore_open_trades(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = JournalRepository(Path(directory) / "journal.db")
            analysis_id = repository.record_analysis(
                symbol="SPY",
                data_as_of="2026-06-24",
                methodology_version="draft",
                decision="CALL",
                confidence="NO_CALIBRADA",
                strategies=["TEST"],
                payload={},
            )
            repository.record_trade(
                analysis_id=analysis_id,
                action="CALL",
                contracts=1,
                entry_price=1.0,
            )

            self.assertEqual(repository.learning_records(), [])

    def test_lists_closed_trades_with_analysis_context(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = JournalRepository(Path(directory) / "journal.db")
            analysis_id = repository.record_analysis(
                symbol="SPY",
                data_as_of="2026-06-24",
                methodology_version="draft",
                decision="CALL",
                confidence="NO_CALIBRADA",
                strategies=["TEST_STRATEGY"],
                payload={},
            )
            trade_id = repository.record_trade(
                analysis_id=analysis_id,
                action="CALL",
                contracts=1,
                entry_price=1.0,
                mode="PAPER",
            )
            repository.close_trade(trade_id, exit_price=1.5, fees=1.0)

            trades = repository.list_closed_trades()

            self.assertEqual(len(trades), 1)
            self.assertEqual(trades[0]["symbol"], "SPY")
            self.assertEqual(trades[0]["decision"], "CALL")
            self.assertEqual(trades[0]["mode"], "PAPER")
            self.assertEqual(trades[0]["strategies"], ["TEST_STRATEGY"])
            self.assertEqual(trades[0]["pnl"], 49.0)

    def test_learning_records_and_statistics_filter_by_mode(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = JournalRepository(Path(directory) / "journal.db")
            paper_analysis_id = repository.record_analysis(
                symbol="SPY",
                data_as_of="2026-06-24",
                methodology_version="draft",
                decision="CALL",
                confidence="NO_CALIBRADA",
                strategies=["TEST_STRATEGY"],
                payload={},
            )
            real_analysis_id = repository.record_analysis(
                symbol="QQQ",
                data_as_of="2026-06-24",
                methodology_version="draft",
                decision="PUT",
                confidence="NO_CALIBRADA",
                strategies=["TEST_STRATEGY"],
                payload={},
            )
            paper_trade_id = repository.record_trade(
                analysis_id=paper_analysis_id,
                action="CALL",
                contracts=1,
                entry_price=1.0,
                mode="PAPER",
            )
            real_trade_id = repository.record_trade(
                analysis_id=real_analysis_id,
                action="PUT",
                contracts=1,
                entry_price=1.0,
                mode="REAL",
                real_mode_acknowledged=True,
            )
            repository.close_trade(paper_trade_id, exit_price=1.5)
            repository.close_trade(real_trade_id, exit_price=0.5)

            paper_records = repository.learning_records("PAPER")
            real_records = repository.learning_records("REAL")
            paper_stats = repository.strategy_statistics("PAPER")
            real_stats = repository.strategy_statistics("REAL")

            self.assertEqual(len(paper_records), 1)
            self.assertEqual(len(real_records), 1)
            self.assertEqual(paper_records[0]["mode"], "PAPER")
            self.assertEqual(real_records[0]["mode"], "REAL")
            self.assertEqual(paper_stats[0]["total_pnl"], 50.0)
            self.assertEqual(real_stats[0]["total_pnl"], -50.0)

    def test_planned_trade_requires_entry_and_exit_plans(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = JournalRepository(Path(directory) / "journal.db")
            analysis_id = repository.record_analysis(
                symbol="QQQ",
                data_as_of="2026-06-24",
                methodology_version="draft",
                decision="NO_OPERAR",
                confidence="NO_CALIBRADA",
                strategies=[],
                payload={},
            )

            with self.assertRaises(ValueError):
                repository.record_planned_trade(
                    analysis_id=analysis_id,
                    action="CALL",
                    contracts=1,
                    entry_price=1.0,
                )

    def test_record_analysis_rejects_invalid_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = JournalRepository(Path(directory) / "journal.db")
            base = {
                "symbol": "SPY",
                "data_as_of": "2026-06-24",
                "methodology_version": "draft",
                "decision": "NO_OPERAR",
                "confidence": "NO_CALIBRADA",
                "strategies": [],
                "payload": {},
            }

            for field, value in (
                ("data_as_of", ""),
                ("methodology_version", ""),
                ("decision", "ESPERAR"),
                ("confidence", ""),
            ):
                with self.subTest(field=field):
                    args = dict(base)
                    args[field] = value
                    with self.assertRaises(ValueError):
                        repository.record_analysis(**args)

    def test_lists_open_trade_and_counts_weekly_by_mode(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = JournalRepository(Path(directory) / "journal.db")
            analysis_id = repository.record_analysis(
                symbol="SPY",
                data_as_of="2026-06-24",
                methodology_version="draft",
                decision="CALL",
                confidence="NO_CALIBRADA",
                strategies=["TEST"],
                payload={},
            )
            repository.record_planned_trade(
                analysis_id=analysis_id,
                action="CALL",
                contracts=1,
                entry_price=1.0,
                mode="PAPER",
                entry_plan="Confirmación completa.",
                exit_plan="Salir al invalidarse.",
            )

            self.assertEqual(len(repository.list_open_trades()), 1)
            self.assertEqual(
                repository.weekly_new_trade_count(
                    "PAPER", now=datetime.now(timezone.utc)
                ),
                1,
            )
            self.assertEqual(repository.list_recent_analyses()[0]["symbol"], "SPY")

    def test_recent_analyses_include_tentative_decision_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = JournalRepository(Path(directory) / "journal.db")
            repository.record_analysis(
                symbol="SPY",
                data_as_of="2026-06-24",
                methodology_version="draft",
                decision="NO_OPERAR",
                confidence="NO_CALIBRADA",
                strategies=[],
                payload={
                    "data_source": {
                        "provider": "TC2000_UPLOAD",
                        "timeframes": ["15m", "1H"],
                        "files": {"15m": "SPY_15m.txt"},
                    },
                    "decision": {
                        "tentative_bias": "CALL",
                        "tentative_strategies": ["TEST_PENDING"],
                    },
                    "report_audit": {
                        "readiness": "INCOMPLETO",
                        "learning_ready": False,
                        "missing_gate_count": 2,
                        "missing_strategy_count": 1,
                        "blocker_detector_count": 1,
                    },
                },
            )
            repository.record_analysis(
                symbol="QQQ",
                data_as_of="2026-06-24",
                methodology_version="draft",
                decision="NO_OPERAR",
                confidence="NO_CALIBRADA",
                strategies=[],
                payload={"legacy": True},
            )
            repository.record_analysis(
                symbol="AAPL",
                data_as_of="2026-06-24",
                methodology_version="draft",
                decision="NO_OPERAR",
                confidence="NO_CALIBRADA",
                strategies=[],
                payload={
                    "decision": {
                        "tentative_bias": "PUT",
                        "tentative_strategies": "LEGACY_PENDING",
                    }
                },
            )

            analyses = repository.list_recent_analyses()

            self.assertEqual(analyses[0]["tentative_bias"], "PUT")
            self.assertEqual(analyses[0]["tentative_strategies"], "LEGACY_PENDING")
            self.assertEqual(analyses[1]["tentative_bias"], "")
            self.assertEqual(analyses[1]["tentative_strategies"], "")
            self.assertEqual(analyses[2]["tentative_bias"], "CALL")
            self.assertEqual(analyses[2]["tentative_strategies"], "TEST_PENDING")
            self.assertEqual(analyses[2]["data_provider"], "TC2000_UPLOAD")
            self.assertEqual(analyses[2]["data_source_timeframes"], "15m|1H")
            self.assertEqual(analyses[2]["data_source_files"], "15m:SPY_15m.txt")
            self.assertEqual(analyses[2]["audit_readiness"], "INCOMPLETO")
            self.assertFalse(analyses[2]["audit_learning_ready"])
            self.assertEqual(analyses[2]["audit_missing_gate_count"], 2)
            self.assertEqual(analyses[2]["audit_missing_strategy_count"], 1)
            self.assertEqual(analyses[2]["audit_blocker_detector_count"], 1)
            self.assertEqual(analyses[1]["audit_readiness"], "")

    def test_trade_against_decision_requires_override_reason(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = JournalRepository(Path(directory) / "journal.db")
            analysis_id = repository.record_analysis(
                symbol="SPY",
                data_as_of="2026-06-24",
                methodology_version="draft",
                decision="NO_OPERAR",
                confidence="NO_CALIBRADA",
                strategies=[],
                payload={},
            )
            trade = {
                "analysis_id": analysis_id,
                "action": "PUT",
                "contracts": 1,
                "entry_price": 1.0,
                "entry_plan": "Entrada discrecional documentada.",
                "exit_plan": "Salida definida.",
            }

            with self.assertRaises(ValueError):
                repository.record_planned_trade(**trade)

            trade_id = repository.record_planned_trade(
                **trade, override_reason="Decisión humana para comparar resultados."
            )
            self.assertFalse(repository.list_open_trades()[0]["decision_followed"])
            self.assertGreater(trade_id, 0)

    def test_direct_trade_against_decision_requires_override_reason(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = JournalRepository(Path(directory) / "journal.db")
            analysis_id = repository.record_analysis(
                symbol="SPY",
                data_as_of="2026-06-24",
                methodology_version="draft",
                decision="CALL",
                confidence="NO_CALIBRADA",
                strategies=[],
                payload={},
            )

            with self.assertRaises(ValueError):
                repository.record_trade(
                    analysis_id=analysis_id,
                    action="PUT",
                    contracts=1,
                    entry_price=1.0,
                )

    def test_trade_with_incomplete_analysis_audit_requires_override_reason(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = JournalRepository(Path(directory) / "journal.db")
            analysis_id = repository.record_analysis(
                symbol="SPY",
                data_as_of="2026-06-24",
                methodology_version="draft",
                decision="CALL",
                confidence="NO_CALIBRADA",
                strategies=["TEST"],
                payload={"report_audit": {"readiness": "INCOMPLETO"}},
            )
            trade = {
                "analysis_id": analysis_id,
                "action": "CALL",
                "contracts": 1,
                "entry_price": 1.0,
                "entry_plan": "Plan documentado.",
                "exit_plan": "Salida documentada.",
            }

            with self.assertRaises(ValueError):
                repository.record_planned_trade(**trade)

            trade_id = repository.record_planned_trade(
                **trade,
                override_reason="Caso incompleto usado solo para comparativa PAPER.",
            )

            self.assertGreater(trade_id, 0)

    def test_direct_trade_with_blocked_analysis_audit_requires_override_reason(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = JournalRepository(Path(directory) / "journal.db")
            analysis_id = repository.record_analysis(
                symbol="SPY",
                data_as_of="2026-06-24",
                methodology_version="draft",
                decision="PUT",
                confidence="NO_CALIBRADA",
                strategies=["TEST"],
                payload={"report_audit": {"readiness": "BLOQUEADO"}},
            )

            with self.assertRaises(ValueError):
                repository.record_trade(
                    analysis_id=analysis_id,
                    action="PUT",
                    contracts=1,
                    entry_price=1.0,
                )

            trade_id = repository.record_trade(
                analysis_id=analysis_id,
                action="PUT",
                contracts=1,
                entry_price=1.0,
                override_reason="Bloqueo documentado para experimento controlado.",
            )

            self.assertGreater(trade_id, 0)

    def test_real_trade_requires_explicit_acknowledgement(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = JournalRepository(Path(directory) / "journal.db")
            analysis_id = repository.record_analysis(
                symbol="SPY",
                data_as_of="2026-06-24",
                methodology_version="draft",
                decision="CALL",
                confidence="NO_CALIBRADA",
                strategies=[],
                payload={},
            )

            with self.assertRaises(ValueError):
                repository.record_trade(
                    analysis_id=analysis_id,
                    action="CALL",
                    contracts=1,
                    entry_price=1.0,
                    mode="REAL",
                )

            trade_id = repository.record_trade(
                analysis_id=analysis_id,
                action="CALL",
                contracts=1,
                entry_price=1.0,
                mode="REAL",
                real_mode_acknowledged=True,
            )

            self.assertGreater(trade_id, 0)

    def test_records_and_lists_report_audits(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = JournalRepository(Path(directory) / "journal.db")

            audit_id = repository.record_report_audit(
                symbol="spy",
                data_as_of="2026-06-24T09:30:00",
                decision="NO_OPERAR",
                readiness="INCOMPLETO",
                learning_ready=False,
                missing_evidence=["riesgo: NO_DISPONIBLE"],
                blockers=[],
                detected_strategies=["EXPUESTO_BOLLINGER_INFERIOR"],
                payload={
                    "source": "test",
                    "app_version": "0.2.1-beta",
                    "methodology_version": "investep-draft-0.1",
                    "package_id": "SPY_2026-06-24",
                    "package_session": "2026-06-24",
                    "package_timeframes": "15m|1H",
                    "data_provider": "TC2000_TXT",
                    "data_source_timeframes": "15m|1H",
                    "data_source_files": "15m:SPY_15m.txt",
                    "data_quality_status": "APROBADO",
                    "panorama_status": "REQUIERE_REVISION",
                    "risk_status": "NO_DISPONIBLE",
                    "governance_status": "APROBADO",
                    "tentative_bias": "CALL",
                    "tentative_strategies": "TEST_PENDING",
                    "first_missing_evidence": "riesgo: NO_DISPONIBLE",
                    "first_blocker": "calidad_datos_issue: OHLC",
                    "missing_gate_count": 2,
                    "missing_strategy_count": 3,
                    "missing_invalidation_count": 1,
                    "blocker_gate_count": 0,
                    "blocker_invalidation_count": 0,
                    "blocker_detector_count": 0,
                    "evaluated_count": 8,
                    "detected_count": 1,
                    "confirmed_count": 0,
                    "skipped_count": 0,
                    "error_count": 0,
                },
            )
            audits = repository.list_recent_report_audits()

            self.assertGreater(audit_id, 0)
            self.assertEqual(audits[0]["symbol"], "SPY")
            self.assertFalse(audits[0]["learning_ready"])
            self.assertEqual(
                audits[0]["missing_evidence"], ["riesgo: NO_DISPONIBLE"]
            )
            self.assertEqual(
                audits[0]["detected_strategies"],
                ["EXPUESTO_BOLLINGER_INFERIOR"],
            )
            self.assertEqual(audits[0]["evaluated_count"], 8)
            self.assertEqual(audits[0]["detected_count"], 1)
            self.assertEqual(audits[0]["app_version"], "0.2.1-beta")
            self.assertEqual(audits[0]["methodology_version"], "investep-draft-0.1")
            self.assertEqual(audits[0]["package_id"], "SPY_2026-06-24")
            self.assertEqual(audits[0]["package_session"], "2026-06-24")
            self.assertEqual(audits[0]["package_timeframes"], "15m|1H")
            self.assertEqual(audits[0]["data_provider"], "TC2000_TXT")
            self.assertEqual(audits[0]["data_source_timeframes"], "15m|1H")
            self.assertEqual(audits[0]["data_source_files"], "15m:SPY_15m.txt")
            self.assertEqual(audits[0]["data_quality_status"], "APROBADO")
            self.assertEqual(audits[0]["panorama_status"], "REQUIERE_REVISION")
            self.assertEqual(audits[0]["risk_status"], "NO_DISPONIBLE")
            self.assertEqual(audits[0]["governance_status"], "APROBADO")
            self.assertEqual(audits[0]["tentative_bias"], "CALL")
            self.assertEqual(audits[0]["tentative_strategies"], "TEST_PENDING")
            self.assertEqual(audits[0]["first_missing_evidence"], "riesgo: NO_DISPONIBLE")
            self.assertEqual(audits[0]["first_blocker"], "calidad_datos_issue: OHLC")
            self.assertEqual(audits[0]["missing_gate_count"], 2)
            self.assertEqual(audits[0]["missing_strategy_count"], 3)

    def test_rejects_invalid_report_audit_readiness(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = JournalRepository(Path(directory) / "journal.db")

            with self.assertRaises(ValueError):
                repository.record_report_audit(
                    symbol="SPY",
                    data_as_of="2026-06-24",
                    decision="NO_OPERAR",
                    readiness="LISTO_OPERAR",
                    learning_ready=False,
                    missing_evidence=[],
                    blockers=[],
                    detected_strategies=[],
                    payload={},
                )

    def test_record_report_audit_rejects_invalid_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = JournalRepository(Path(directory) / "journal.db")
            base = {
                "symbol": "SPY",
                "data_as_of": "2026-06-24",
                "decision": "NO_OPERAR",
                "readiness": "INCOMPLETO",
                "learning_ready": False,
                "missing_evidence": [],
                "blockers": [],
                "detected_strategies": [],
                "payload": {},
            }

            for field, value in (("data_as_of", ""), ("decision", "ESPERAR")):
                with self.subTest(field=field):
                    args = dict(base)
                    args[field] = value
                    with self.assertRaises(ValueError):
                        repository.record_report_audit(**args)

    def test_old_report_audit_payload_without_counts_uses_zeroes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = JournalRepository(Path(directory) / "journal.db")
            repository.record_report_audit(
                symbol="SPY",
                data_as_of="2026-06-24",
                decision="NO_OPERAR",
                readiness="INCOMPLETO",
                learning_ready=False,
                missing_evidence=[],
                blockers=[],
                detected_strategies=[],
                payload={"legacy": True},
            )

            audit = repository.list_recent_report_audits()[0]

            self.assertEqual(audit["evaluated_count"], 0)
            self.assertEqual(audit["detected_count"], 0)
            self.assertEqual(audit["data_quality_status"], "")
            self.assertEqual(audit["risk_status"], "")
            self.assertEqual(audit["package_id"], "")
            self.assertEqual(audit["package_timeframes"], "")
            self.assertEqual(audit["data_provider"], "")
            self.assertEqual(audit["data_source_files"], "")
            self.assertEqual(audit["tentative_bias"], "")
            self.assertEqual(audit["tentative_strategies"], "")
            self.assertEqual(audit["first_missing_evidence"], "")
            self.assertEqual(audit["first_blocker"], "")

    def test_report_audit_payload_with_invalid_counts_uses_zeroes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = JournalRepository(Path(directory) / "journal.db")
            repository.record_report_audit(
                symbol="SPY",
                data_as_of="2026-06-24",
                decision="NO_OPERAR",
                readiness="INCOMPLETO",
                learning_ready=False,
                missing_evidence=[],
                blockers=[],
                detected_strategies=[],
                payload={
                    "evaluated_count": "n/a",
                    "detected_count": None,
                    "missing_gate_count": "dos",
                    "blocker_detector_count": [],
                },
            )

            audit = repository.list_recent_report_audits()[0]

            self.assertEqual(audit["evaluated_count"], 0)
            self.assertEqual(audit["detected_count"], 0)
            self.assertEqual(audit["missing_gate_count"], 0)
            self.assertEqual(audit["blocker_detector_count"], 0)

    def test_corrupt_analysis_strategies_json_uses_empty_list(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = JournalRepository(Path(directory) / "journal.db")
            analysis_id = repository.record_analysis(
                symbol="SPY",
                data_as_of="2026-06-24",
                methodology_version="draft",
                decision="NO_OPERAR",
                confidence="NO_CALIBRADA",
                strategies=["TEST"],
                payload={},
            )
            with repository._connect() as connection:
                connection.execute(
                    "UPDATE analyses SET strategies_json = ? WHERE id = ?",
                    ("{bad", analysis_id),
                )

            analysis = repository.list_recent_analyses()[0]

            self.assertEqual(analysis["strategies"], [])

    def test_corrupt_closed_trade_strategies_json_does_not_break_learning(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = JournalRepository(Path(directory) / "journal.db")
            analysis_id = repository.record_analysis(
                symbol="SPY",
                data_as_of="2026-06-24",
                methodology_version="draft",
                decision="CALL",
                confidence="NO_CALIBRADA",
                strategies=["TEST"],
                payload={},
            )
            trade_id = repository.record_trade(
                analysis_id=analysis_id,
                action="CALL",
                contracts=1,
                entry_price=1.0,
            )
            repository.close_trade(trade_id, exit_price=1.2)
            self.assertEqual(repository.learning_records()[0]["decision"], "CALL")
            with repository._connect() as connection:
                connection.execute(
                    "UPDATE analyses SET strategies_json = ? WHERE id = ?",
                    ("{bad", analysis_id),
                )

            self.assertEqual(repository.strategy_statistics(), [])
            self.assertEqual(repository.learning_records()[0]["strategies"], [])

    def test_corrupt_report_audit_json_fields_use_empty_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = JournalRepository(Path(directory) / "journal.db")
            audit_id = repository.record_report_audit(
                symbol="SPY",
                data_as_of="2026-06-24",
                decision="NO_OPERAR",
                readiness="INCOMPLETO",
                learning_ready=False,
                missing_evidence=["riesgo: NO_DISPONIBLE"],
                blockers=["bloqueo"],
                detected_strategies=["TEST"],
                payload={"evaluated_count": 8, "detected_count": 1},
            )
            with repository._connect() as connection:
                connection.execute(
                    """
                    UPDATE report_audits
                    SET missing_evidence_json = ?,
                        blockers_json = ?,
                        detected_strategies_json = ?,
                        payload_json = ?
                    WHERE id = ?
                    """,
                    ("{bad", "{bad", "{bad", "{bad", audit_id),
                )

            audit = repository.list_recent_report_audits()[0]

            self.assertEqual(audit["missing_evidence"], [])
            self.assertEqual(audit["blockers"], [])
            self.assertEqual(audit["detected_strategies"], [])
            self.assertEqual(audit["evaluated_count"], 0)
            self.assertEqual(audit["detected_count"], 0)


if __name__ == "__main__":
    unittest.main()
