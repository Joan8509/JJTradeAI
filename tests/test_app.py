"""Prueba mínima de renderizado para la interfaz Streamlit."""

from pathlib import Path
from datetime import datetime, timezone
import unittest

from streamlit.testing.v1 import AppTest

from analysis_models import (
    CriterionEvaluation,
    DirectionBias,
    EvaluationStatus,
    StrategyEvaluation,
)
from app import (
    _analysis_requires_override_reason,
    _audit_summary_table,
    _closed_trade_comparison_table,
    _compact_operational_card,
    _current_strategy_certainty,
    _current_live_previews,
    _alert_live_certainty_rank,
    _lead_live_signal,
    _live_direction_guidance,
    _operating_signal_status,
    _closed_trades_table,
    _data_source_table,
    _effective_common_news_review,
    _filtered_closed_trades,
    _filtered_recent_analyses,
    _filtered_report_audits,
    _first_text_or_na,
    _feed_comparison_summary,
    _live_alerts_table,
    _market_event_local_time,
    _case_intake_upload_table,
    _recent_analyses_table,
    _record_common_news_review,
    _filtered_review_queue,
    _operator_board_upload_table,
    _operational_notification,
    _paper_evidence_checks_table,
    _preview_confidence_badge,
    _reevaluation_outcome_mode,
    _report_audits_table,
    _review_queue_upload_table,
    _review_queue_table,
    _strategy_radar_table,
    _strategy_scan_table,
    _service_health_table,
    _simple_alert_summary,
    _simple_moment_status,
    _alert_reviews_table,
)
from report_auditor import ReportAudit


class StreamlitAppTests(unittest.TestCase):
    def test_current_live_previews_excludes_previous_session_and_stale_rows(self) -> None:
        previews = [
            {"symbol": "SPY", "as_of": "2026-08-13T13:29:00+00:00"},
            {"symbol": "QQQ", "as_of": "2026-08-13T13:20:00+00:00"},
            {"symbol": "MU", "as_of": "2026-08-12T19:59:00+00:00"},
        ]

        current = _current_live_previews(
            previews, now=datetime(2026, 8, 13, 13, 30, tzinfo=timezone.utc)
        )

        self.assertEqual([item["symbol"] for item in current], ["SPY"])

    def test_operational_notifications_are_differentiated_and_fresh_only(self) -> None:
        base = {
            "symbol": "QQQ", "strategy": "Momentum", "direction": "CALL",
            "setup_status": "CONFIRMADA", "can_operate": True,
            "next_requirement": "Lista para PAPER.",
        }
        call = _operational_notification(base, {"status": "SIMULAR"})
        put = _operational_notification(
            {**base, "direction": "PUT"}, {"status": "SIMULAR"}
        )
        waiting = _operational_notification(
            {**base, "setup_status": "EN_FORMACION", "can_operate": False},
            {"status": "ESPERAR"},
        )
        blocked = _operational_notification(
            {**base, "can_operate": False}, {"status": "REVISAR"}
        )

        self.assertEqual(call["level"], "CALL")
        self.assertEqual(put["level"], "PUT")
        self.assertEqual(waiting["level"], "ESPERAR")
        self.assertEqual(blocked["level"], "NO_OPERAR")
        self.assertIsNone(_operational_notification(base, {"status": "HISTORICA"}))

    def test_market_event_time_uses_effective_quarter_hour_close(self) -> None:
        self.assertEqual(
            _market_event_local_time("2026-08-11T19:59:00+00:00"),
            "2026-08-11 04:00 PM ET",
        )
        self.assertEqual(
            _market_event_local_time("2026-08-11T19:45:00+00:00"),
            "2026-08-11 03:45 PM ET",
        )

    def test_compact_card_removes_conflicting_expired_labels(self) -> None:
        card = _compact_operational_card(
            {
                "symbol": "QQQ",
                "strategy": "Cambio de Tendencia en 15 Alcista",
                "setup_status": "EN_FORMACION",
                "timing_status": "VENCIDA",
                "direction": "CALL",
                "next_requirement": "CT15 solo es valido en la primera vela.",
            },
            {"status": "HISTORICA", "label": "SESION FINALIZADA"},
        )

        self.assertEqual(card["state"], "VENCIDA")
        self.assertEqual(card["action"], "NO OPERAR")
        self.assertEqual(card["direction"], "CALL")

    def test_compact_card_identifies_strategy_timeframe(self) -> None:
        card = _compact_operational_card(
            {
                "symbol": "MU",
                "strategy": "Expuesto Bollinger Superior",
                "timeframe": "1H",
                "setup_status": "EN_FORMACION",
                "direction": "PUT",
                "next_requirement": "Confirmacion posterior a la exposicion",
            },
            {"status": "ESPERAR", "label": "ESPERAR CONFIRMACION"},
        )

        self.assertIn("1H", card["title"])

    def test_preview_confidence_badge_prioritizes_strongest_signal(self) -> None:
        badge = _preview_confidence_badge({
            "directional_learning_signal": {
                "status": "APRENDIZAJE_ALINEADO",
                "rows": [{
                    "strategy_id": "BOLLINGER_FIJO_CALL",
                    "confidence_score": 91.0,
                    "priority": "ALTA",
                    "historical_direction": "CALL",
                }],
            },
        })

        self.assertEqual(badge["label"], "ALTA")
        self.assertEqual(badge["priority"], "ALTA")
        self.assertEqual(badge["confidence_pct"], 91)
        self.assertEqual(badge["tone"], "high")

    def test_current_strategy_certainty_prefers_automatic_learning_when_stronger(self) -> None:
        signal = _current_strategy_certainty({
            "directional_learning_signal": {
                "status": "APRENDIZAJE_ALINEADO",
                "rows": [{
                    "strategy_id": "CT15_ALCISTA",
                    "confidence_score": 58.0,
                    "priority": "MEDIA",
                    "historical_direction": "CALL",
                }],
            },
            "automatic_learning_signal": {
                "status": "APRENDIZAJE_ALINEADO",
                "summary_score": 88.0,
                "priority": "ALTA",
                "recommended_direction": "CALL",
                "rows": [{
                    "strategy_id": "CT15_ALCISTA",
                    "confidence_score": 88.0,
                    "priority": "ALTA",
                    "historical_direction": "CALL",
                }],
            },
        })

        self.assertEqual(signal["strategy"], "CT15_ALCISTA")
        self.assertEqual(signal["confidence"], 88.0)
        self.assertEqual(signal["priority"], "ALTA")
        self.assertEqual(signal["status"], "APRENDIZAJE_ALINEADO")

    def test_live_direction_guidance_uses_automatic_signal_when_confirmed(self) -> None:
        guidance = _live_direction_guidance({
            "decision": {"decision": "PUT"},
            "automatic_learning_signal": {
                "status": "APRENDIZAJE_ALINEADO",
                "recommended_direction": "PUT",
                "summary_score": 87.0,
            },
            "directional_learning_signal": {
                "status": "APRENDIZAJE_ALINEADO",
                "recommended_direction": "PUT",
                "rows": [{"confidence_score": 71.0, "priority": "MEDIA"}],
            },
        })

        self.assertEqual(guidance["direction"], "PUT")
        self.assertEqual(guidance["status"], "CONFIRMADA")
        self.assertGreaterEqual(guidance["confidence_pct"], 80)

    def test_alert_live_certainty_rank_prefers_automatic_learning_signal(self) -> None:
        item = {
            "id": 8,
            "report": {
                "automatic_learning_signal": {
                    "status": "APRENDIZAJE_ALINEADO",
                    "summary_score": 88.0,
                    "rows": [{"strategy_id": "CT15_ALCISTA", "confidence_score": 88.0, "priority": "ALTA"}],
                },
                "directional_learning_signal": {
                    "status": "APRENDIZAJE_ALINEADO",
                    "rows": [{"strategy_id": "CT15_ALCISTA", "confidence_score": 55.0, "priority": "MEDIA"}],
                },
            },
        }

        ranking = _alert_live_certainty_rank(item)
        self.assertEqual(ranking[0], 88.0)
        self.assertEqual(ranking[1], 3)

    def test_lead_live_signal_prioritizes_strongest_direction(self) -> None:
        lead = _lead_live_signal([
            {"report": {"automatic_learning_signal": {"status": "APRENDIZAJE_ALINEADO", "recommended_direction": "PUT", "summary_score": 61.0}}},
            {"report": {"automatic_learning_signal": {"status": "APRENDIZAJE_ALINEADO", "recommended_direction": "CALL", "summary_score": 90.0}}},
        ])

        self.assertEqual(lead["direction"], "CALL")
        self.assertEqual(lead["status"], "CONFIRMADA")
        self.assertEqual(lead["confidence_pct"], 90)

    def test_lead_live_signal_downgrades_contrary_movement_even_if_score_is_high(self) -> None:
        lead = _lead_live_signal([
            {"report": {"automatic_learning_signal": {"status": "APRENDIZAJE_CONTRARIO", "recommended_direction": "PUT", "summary_score": 92.0}}},
            {"report": {"automatic_learning_signal": {"status": "APRENDIZAJE_ALINEADO", "recommended_direction": "CALL", "summary_score": 72.0}}},
        ])

        self.assertEqual(lead["direction"], "CALL")
        self.assertEqual(lead["status"], "PROBABLE")
        self.assertEqual(lead["confidence_pct"], 72)

    def test_operating_signal_waits_for_automatic_confirmation(self) -> None:
        result = _operating_signal_status({
            "decision": {"decision": "CALL"},
            "automatic_learning_signal": {
                "status": "MUESTRA_INSUFICIENTE",
                "summary_score": 0,
            },
        })

        self.assertEqual(result["status"], "ESPERAR_VALIDACION")
        self.assertTrue(result["paper_only"])
        self.assertFalse(result["real_trading_authorized"])

    def test_operating_signal_allows_only_paper_review_after_strong_alignment(self) -> None:
        result = _operating_signal_status({
            "decision": {"decision": "CALL"},
            "live_data_freshness": {"status": "APROBADO"},
            "market_data_reconciliation": {"status": "APROBADO"},
            "automatic_learning_signal": {
                "status": "APRENDIZAJE_ALINEADO",
                "recommended_direction": "CALL",
                "summary_score": 84,
            },
        })

        self.assertEqual(result["status"], "PAPER_APTA_REVISION")
        self.assertFalse(result["real_trading_authorized"])

    def test_operating_signal_blocks_contrary_direction(self) -> None:
        result = _operating_signal_status({
            "decision": {"decision": "CALL"},
            "automatic_learning_signal": {
                "status": "APRENDIZAJE_CONTRARIO",
                "recommended_direction": "PUT",
                "summary_score": 90,
            },
        })

        self.assertEqual(result["status"], "BLOQUEADA")

    def test_feed_comparison_summary_distinguishes_match_and_divergence(self) -> None:
        matching = _feed_comparison_summary({
            "evaluated_at": "2026-08-10T20:30:00+00:00",
            "results": [
                {"symbol": "SPY", "detector_difference_count": 0},
                {"symbol": "QQQ", "detector_difference_count": 0},
            ],
        })
        divergent = _feed_comparison_summary({
            "results": [{"symbol": "QQQ", "detector_difference_count": 2}],
        })

        self.assertEqual(matching["status"], "COINCIDE")
        self.assertEqual(matching["label"], "ULTIMA EVALUACION COINCIDE")
        self.assertEqual(divergent["status"], "DIVERGE")
        self.assertEqual(divergent["detector_difference_count"], 2)

    def test_feed_comparison_summary_is_pending_without_report(self) -> None:
        summary = _feed_comparison_summary(None)

        self.assertEqual(summary["status"], "PENDIENTE")
        self.assertEqual(summary["rows"], [])

    def test_feed_comparison_summary_uses_historical_replay(self) -> None:
        summary = _feed_comparison_summary({"results": [{
            "symbol": "QQQ",
            "detector_difference_count": 0,
            "historical_replay": {
                "evaluated_close_count": 130,
                "divergent_close_count": 3,
                "divergence_rate_pct": 2.3077,
                "unique_divergence_episode_count": 1,
            },
        }]})

        self.assertEqual(summary["status"], "DIVERGE")
        self.assertEqual(summary["label"], "DIVERGENCIA HISTORICA")
        self.assertEqual(summary["historical_divergent_close_count"], 3)
        self.assertEqual(summary["historical_unique_episode_count"], 1)

    def test_simple_alert_summary_explains_confirmed_but_blocked_setup(self) -> None:
        alert = {
            "id": 47,
            "symbol": "QQQ",
            "trigger_timestamp": "2026-08-07T19:45:00+00:00",
            "decision": "NO_OPERAR",
            "report": {
                "decision": {
                    "decision": "NO_OPERAR",
                    "supporting_strategies": ["CT15_ALCISTA@15m"],
                    "reasons": ["El panorama general no esta aprobado."],
                },
                "strategies": {"evaluations": [{
                    "strategy_id": "CT15_ALCISTA",
                    "name": "Cambio de Tendencia en 15 Alcista",
                    "bias": "CALL",
                    "detected": True,
                }]},
            },
        }

        summary = _simple_alert_summary(alert)

        self.assertEqual(summary["setup_status"], "CONFIRMADA")
        self.assertEqual(summary["strategy"], "Cambio de Tendencia en 15 Alcista")
        self.assertEqual(summary["direction"], "CALL")
        self.assertFalse(summary["can_operate"])
        self.assertEqual(summary["main_reason"], "El panorama general no esta aprobado.")

    def test_simple_alert_summary_marks_unconfirmed_setup_as_forming(self) -> None:
        summary = _simple_alert_summary({
            "id": 48,
            "symbol": "SPY",
            "decision": "NO_OPERAR",
            "report": {
                "decision": {"decision": "NO_OPERAR", "reasons": ["Falta confirmacion."]},
                "strategies": {"evaluations": [{
                    "strategy_id": "PRIMER_SALTO_RESPETADO_ALCISTA",
                    "name": "Primer Salto",
                    "bias": "CALL",
                    "detected": True,
                }]},
            },
        })

        self.assertEqual(summary["setup_status"], "EN_FORMACION")
        self.assertEqual(summary["direction"], "CALL")
        self.assertFalse(summary["can_operate"])

    def test_simple_summary_labels_non_consolidated_feeds(self) -> None:
        base = {
            "id": 1,
            "symbol": "SPY",
            "decision": "CALL",
            "report": {
                "decision": {"decision": "CALL", "reasons": []},
                "strategies": {"evaluations": []},
            },
        }

        iex = _simple_alert_summary({**base, "feed": "iex"})
        delayed = _simple_alert_summary({**base, "feed": "delayed_sip"})

        self.assertEqual(iex["feed_scope"], "RADAR_PARCIAL")
        self.assertEqual(delayed["feed_scope"], "RETRASADO")
        self.assertTrue(iex["paper_only"])
        self.assertTrue(delayed["paper_only"])

    def test_simple_summary_exposes_first_required_technical_gap(self) -> None:
        summary = _simple_alert_summary({
            "id": 50,
            "symbol": "SPY",
            "feed": "iex",
            "decision": "NO_OPERAR",
            "report": {
                "decision": {"decision": "NO_OPERAR", "reasons": ["Faltan requisitos."]},
                "strategies": {"evaluations": [{
                    "strategy_id": "RETORNO_BOLLINGER_LATERAL_BAJISTA",
                    "name": "Retorno Bajista a Bollinger",
                    "bias": "PUT",
                    "detected": True,
                    "criteria": [{
                        "criterion_id": "exceptional_gap",
                        "name": "Distancia excepcional para el activo",
                        "required": True,
                        "status": "NO_CUMPLE",
                    }],
                }]},
            },
        })

        self.assertEqual(summary["setup_status"], "EN_FORMACION")
        self.assertEqual(summary["next_requirement"], "Distancia excepcional para el activo")

    def test_simple_moment_status_distinguishes_now_from_history(self) -> None:
        summary = {
            "trigger_timestamp": "2026-08-07T14:45:00+00:00",
            "setup_status": "CONFIRMADA",
            "can_operate": False,
            "decision": "NO_OPERAR",
        }
        now = datetime(2026, 8, 7, 14, 46, tzinfo=timezone.utc)

        active = _simple_moment_status(summary, scanner_active=True, now=now)
        stopped = _simple_moment_status(summary, scanner_active=False, now=now)

        self.assertEqual(active["status"], "REVISAR")
        self.assertEqual(active["label"], "REVISAR AHORA")
        self.assertEqual(active["local_time"], "2026-08-07 10:45 AM ET")
        self.assertEqual(stopped["status"], "HISTORICA")

    def test_closed_session_blocks_fresh_actionable_signal_with_scanner_running(self) -> None:
        now = datetime(2026, 10, 8, 20, 1, tzinfo=timezone.utc)
        summary = {"trigger_timestamp": "2026-10-08T19:59:00+00:00", "can_operate": True,
                   "paper_only": True, "decision": "CALL", "setup_status": "CONFIRMADA"}
        result = _simple_moment_status(summary, scanner_active=True, market_open=False, now=now)
        self.assertEqual(result["status"], "HISTORICA")
        self.assertEqual(result["label"], "SESION FINALIZADA")

    def test_simple_moment_status_expires_old_signal(self) -> None:
        summary = {
            "trigger_timestamp": "2026-08-07T14:15:00+00:00",
            "setup_status": "CONFIRMADA",
            "can_operate": True,
            "decision": "CALL",
        }

        result = _simple_moment_status(
            summary,
            scanner_active=True,
            now=datetime(2026, 8, 7, 14, 46, tzinfo=timezone.utc),
        )

        self.assertEqual(result["status"], "VENCIDA")
        self.assertEqual(result["label"], "SENAL VENCIDA")

    def test_simple_moment_status_never_labels_beta_signal_as_real_operation(self) -> None:
        result = _simple_moment_status(
            {
                "trigger_timestamp": "2026-08-07T14:45:00+00:00",
                "setup_status": "CONFIRMADA",
                "can_operate": True,
                "paper_only": True,
                "decision": "CALL",
            },
            scanner_active=True,
            now=datetime(2026, 8, 7, 14, 46, tzinfo=timezone.utc),
        )

        self.assertEqual(result["status"], "SIMULAR")
        self.assertEqual(result["label"], "SIMULAR CALL EN PAPER")

    def test_simple_moment_status_blocks_documented_expired_setup(self) -> None:
        result = _simple_moment_status(
            {
                "trigger_timestamp": "2026-08-07T19:45:00+00:00",
                "setup_status": "CONFIRMADA",
                "can_operate": True,
                "paper_only": True,
                "decision": "CALL",
                "timing_status": "VENCIDA",
            },
            scanner_active=True,
            now=datetime(2026, 8, 7, 19, 46, tzinfo=timezone.utc),
        )

        self.assertEqual(result["status"], "FUERA_DE_VENTANA")
        self.assertEqual(result["label"], "ESTRATEGIA VENCIDA")

    def test_reevaluation_outcome_mode_is_derived_from_governance(self) -> None:
        reviews = [
            {"id": 7, "mode": "REAL"},
            {"id": 6, "mode": "PAPER"},
        ]

        self.assertEqual(
            _reevaluation_outcome_mode(
                {"governance_review_id": 7},
                reviews,
            ),
            "REAL",
        )
        self.assertEqual(
            _reevaluation_outcome_mode(
                {"governance_review_id": 0},
                reviews,
            ),
            "PAPER",
        )
        with self.assertRaisesRegex(ValueError, "no esta disponible"):
            _reevaluation_outcome_mode(
                {"governance_review_id": 99},
                reviews,
            )

    def test_paper_evidence_checks_table_preserves_safe_contract(self) -> None:
        table = _paper_evidence_checks_table(
            {
                "checks": [
                    {
                        "name": "remote_preflight",
                        "status": "ERROR",
                        "detail": "No existe preflight remoto LISTO.",
                        "unexpected": "ignored",
                    }
                ]
            }
        )

        self.assertEqual(
            list(table.columns),
            ["Check", "Estado", "Detalle"],
        )
        self.assertEqual(table.iloc[0]["Check"], "remote_preflight")
        self.assertEqual(table.iloc[0]["Estado"], "ERROR")

    def test_alert_reviews_table_distinguishes_pending_and_rejected(self) -> None:
        table = _alert_reviews_table(
            [{
                "id": 1,
                "created_at": "2026-07-21T15:00:00Z",
                "path_clear": True,
                "news_clear": None,
                "panorama_approved": False,
                "notes": "Conflicto",
            }]
        )
        self.assertEqual(table.iloc[0]["Noticias revisadas"], "PENDIENTE")
        self.assertEqual(table.iloc[0]["Panorama aprobado"], "NO")
    def test_service_health_table_shows_reconnections_and_freshness(self) -> None:
        table = _service_health_table(
            {
                "status": "CONECTADO",
                "provider": "ALPACA",
                "feed": "sip",
                "symbols": ["QQQ", "SPY"],
                "last_connected_at": "2026-07-21T14:00:00Z",
                "last_bar_at": "2026-07-21T14:01:00Z",
                "reconnect_count": 2,
                "last_error": "",
            }
        )

        self.assertEqual(table.iloc[0]["Estado"], "CONECTADO")
        self.assertEqual(table.iloc[0]["Reconexiones"], 2)
        self.assertEqual(table.iloc[0]["Símbolos"], "QQQ, SPY")

    def test_live_alerts_table_exposes_auditable_counts(self) -> None:
        table = _live_alerts_table(
            [{
                "id": 3,
                "created_at": "2026-07-20T14:00:00Z",
                "symbol": "SPY",
                "trigger_timestamp": "2026-07-20T13:44:00Z",
                "feed": "sip",
                "decision": "NO_OPERAR",
                "detected_count": 2,
                "confirmed_count": 1,
            }]
        )

        self.assertEqual(table.iloc[0]["ID"], 3)
        self.assertEqual(table.iloc[0]["Confirmadas"], 1)

    def test_strategy_scan_table_orders_actionable_states(self) -> None:
        base = {
            "symbol": "SPY",
            "data_as_of": "2026-07-20",
            "strategy_name": "CT15",
            "strategy_id": "CT15_ALCISTA",
            "timeframe": "15m",
            "bias": "CALL",
            "compliance_percentage": 50.0,
            "required_count": 2,
            "pending_count": 1,
            "failed_count": 0,
            "next_required": "Confirmacion",
            "final_decision": "NO_OPERAR",
            "readiness": "INCOMPLETO",
        }
        rows = [
            {**base, "state": "CANDIDATA"},
            {
                **base,
                "symbol": "QQQ",
                "state": "CONFIRMADA",
                "compliance_percentage": 100.0,
            },
        ]

        table = _strategy_scan_table(rows)

        self.assertEqual(list(table["Estado"]), ["CONFIRMADA", "CANDIDATA"])
        self.assertEqual(table.iloc[0]["Simbolo"], "QQQ")

    def test_analysis_requires_override_reason_for_incomplete_or_blocked(self) -> None:
        self.assertTrue(_analysis_requires_override_reason({"audit_readiness": "INCOMPLETO"}))
        self.assertTrue(_analysis_requires_override_reason({"audit_readiness": "BLOQUEADO"}))
        self.assertFalse(_analysis_requires_override_reason({"audit_readiness": "LISTO_REVISION"}))
        self.assertFalse(_analysis_requires_override_reason({}))

    def test_first_text_or_na_extracts_actionable_text(self) -> None:
        self.assertEqual(_first_text_or_na(["", "calidad_datos_issue"]), "calidad_datos_issue")
        self.assertEqual(_first_text_or_na([]), "N/D")
        self.assertEqual(_first_text_or_na("riesgo: NO_DISPONIBLE"), "riesgo: NO_DISPONIBLE")

    def test_recent_analyses_table_summarizes_audit_and_source(self) -> None:
        table = _recent_analyses_table(
            [
                {
                    "id": 7,
                    "symbol": "SPY",
                    "data_as_of": "2026-06-24",
                    "decision": "NO_OPERAR",
                    "confidence": "NO_CALIBRADA",
                    "audit_readiness": "INCOMPLETO",
                    "audit_learning_ready": False,
                    "audit_missing_gate_count": 2,
                    "audit_missing_strategy_count": 1,
                    "audit_missing_invalidation_count": 0,
                    "audit_blocker_gate_count": 0,
                    "audit_blocker_invalidation_count": 1,
                    "audit_blocker_detector_count": 1,
                    "data_provider": "TC2000_UPLOAD",
                    "data_source_timeframes": "15m|1H",
                    "tentative_bias": "CALL",
                    "tentative_strategies": "TEST_PENDING",
                }
            ]
        )

        self.assertEqual(table.iloc[0]["ID"], 7)
        self.assertEqual(table.iloc[0]["Auditoria"], "INCOMPLETO")
        self.assertEqual(table.iloc[0]["Learning ready"], "NO")
        self.assertEqual(table.iloc[0]["Faltantes"], 3)
        self.assertEqual(table.iloc[0]["Bloqueos"], 2)
        self.assertEqual(table.iloc[0]["Fuente datos"], "TC2000_UPLOAD")

    def test_filtered_recent_analyses_uses_session_dimensions(self) -> None:
        import pandas as pd

        table = pd.DataFrame(
            [
                {
                    "ID": 1,
                    "Simbolo": "SPY",
                    "Decision": "NO_OPERAR",
                    "Auditoria": "INCOMPLETO",
                },
                {
                    "ID": 2,
                    "Simbolo": "QQQ",
                    "Decision": "CALL",
                    "Auditoria": "LISTO_REVISION",
                },
            ]
        )

        filtered = _filtered_recent_analyses(
            table,
            symbols=["QQQ"],
            decisions=["CALL"],
            audit_states=["LISTO_REVISION"],
        )

        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered.iloc[0]["ID"], 2)

    def test_report_audits_table_shows_primary_pending_and_blocker(self) -> None:
        table = _report_audits_table(
            [
                {
                    "id": 9,
                    "created_at": "2026-06-24T10:00:00",
                    "symbol": "SPY",
                    "data_as_of": "2026-06-24",
                    "decision": "NO_OPERAR",
                    "readiness": "INCOMPLETO",
                    "learning_ready": False,
                    "app_version": "0.2.1-beta",
                    "methodology_version": "investep-draft-0.1",
                    "package_id": "SPY_2026-06-24",
                    "package_session": "2026-06-24",
                    "package_timeframes": "15m|1H|1D",
                    "data_provider": "TC2000_TXT",
                    "data_source_timeframes": "15m|1H|1D",
                    "data_quality_status": "APROBADO",
                    "panorama_status": "REQUIERE_REVISION",
                    "risk_status": "NO_DISPONIBLE",
                    "governance_status": "APROBADO",
                    "tentative_bias": "CALL",
                    "tentative_strategies": "TEST_PENDING",
                    "evaluated_count": 8,
                    "detected_count": 1,
                    "confirmed_count": 0,
                    "skipped_count": 0,
                    "error_count": 0,
                    "detected_strategies": ["TEST_PENDING"],
                    "missing_evidence": ["riesgo: NO_DISPONIBLE"],
                    "first_missing_evidence": "",
                    "missing_gate_count": 1,
                    "missing_strategy_count": 0,
                    "missing_invalidation_count": 0,
                    "blockers": ["detector_issue: OHLC"],
                    "first_blocker": "",
                    "blocker_gate_count": 0,
                    "blocker_invalidation_count": 0,
                    "blocker_detector_count": 1,
                }
            ]
        )

        self.assertEqual(table.iloc[0]["Simbolo"], "SPY")
        self.assertEqual(table.iloc[0]["Primer pendiente"], "riesgo: NO_DISPONIBLE")
        self.assertEqual(table.iloc[0]["Primer bloqueo"], "detector_issue: OHLC")
        self.assertEqual(table.iloc[0]["Pendientes"], 1)
        self.assertEqual(table.iloc[0]["Bloqueos"], 1)

    def test_filtered_report_audits_uses_review_dimensions(self) -> None:
        import pandas as pd

        table = pd.DataFrame(
            [
                {
                    "ID": 1,
                    "Simbolo": "SPY",
                    "Estado": "INCOMPLETO",
                    "Paquete": "SPY_2026-06-24",
                },
                {
                    "ID": 2,
                    "Simbolo": "QQQ",
                    "Estado": "LISTO_REVISION",
                    "Paquete": "QQQ_2026-06-24",
                },
            ]
        )

        filtered = _filtered_report_audits(
            table,
            symbols=["SPY"],
            readiness=["INCOMPLETO"],
            packages=["SPY_2026-06-24"],
        )

        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered.iloc[0]["ID"], 1)

    def test_closed_trades_table_preserves_mode_and_decision_context(self) -> None:
        table = _closed_trades_table(
            [
                {
                    "id": 5,
                    "analysis_id": 2,
                    "symbol": "SPY",
                    "data_as_of": "2026-06-24",
                    "decision": "CALL",
                    "action": "CALL",
                    "mode": "PAPER",
                    "workflow": "NUEVA_ENTRADA",
                    "opened_at": "2026-06-24T14:00:00",
                    "closed_at": "2026-06-24T15:00:00",
                    "contracts": 1,
                    "entry_price": 1.0,
                    "exit_price": 1.5,
                    "fees": 1.0,
                    "pnl": 49.0,
                    "decision_followed": 1,
                    "override_reason": "",
                    "strategies": ["TEST_CALL"],
                }
            ]
        )

        self.assertEqual(table.iloc[0]["Modo"], "PAPER")
        self.assertEqual(table.iloc[0]["Decision analisis"], "CALL")
        self.assertEqual(table.iloc[0]["Resultado"], "GANADORA")
        self.assertEqual(table.iloc[0]["Siguio decision"], "SI")

    def test_filtered_closed_trades_uses_mode_symbol_and_decision(self) -> None:
        import pandas as pd

        table = pd.DataFrame(
            [
                {
                    "ID": 1,
                    "Modo": "PAPER",
                    "Simbolo": "SPY",
                    "Decision analisis": "CALL",
                },
                {
                    "ID": 2,
                    "Modo": "REAL",
                    "Simbolo": "QQQ",
                    "Decision analisis": "PUT",
                },
            ]
        )

        filtered = _filtered_closed_trades(
            table,
            modes=["PAPER"],
            symbols=["SPY"],
            decisions=["CALL"],
        )

        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered.iloc[0]["ID"], 1)

    def test_closed_trade_comparison_table_groups_by_mode_and_followed_decision(self) -> None:
        import pandas as pd

        comparison = _closed_trade_comparison_table(
            pd.DataFrame(
                [
                    {"Modo": "PAPER", "Siguio decision": "SI", "PnL": 50.0},
                    {"Modo": "PAPER", "Siguio decision": "SI", "PnL": -10.0},
                    {"Modo": "PAPER", "Siguio decision": "NO", "PnL": 20.0},
                ]
            )
        )

        followed = comparison[comparison["Siguio decision"] == "SI"].iloc[0]
        self.assertEqual(followed["Operaciones"], 2)
        self.assertEqual(followed["Ganadoras"], 1)
        self.assertEqual(followed["Win rate"], 50.0)
        self.assertEqual(followed["PnL total"], 40.0)

    def test_audit_summary_table_counts_missing_and_blockers(self) -> None:
        audit = ReportAudit(
            symbol="SPY",
            data_as_of="2026-06-21",
            decision="NO_OPERAR",
            data_quality_status="APROBADO",
            panorama_status="REQUIERE_REVISION",
            risk_status="NO_DISPONIBLE",
            governance_status="NO_DISPONIBLE",
            readiness="INCOMPLETO",
            learning_ready=False,
            missing_evidence=("riesgo",),
            blockers=("detector",),
            detected_strategies=("CT15",),
            missing_gate_count=2,
            missing_strategy_count=1,
            missing_invalidation_count=0,
            blocker_gate_count=0,
            blocker_invalidation_count=1,
            blocker_detector_count=1,
            detected_count=1,
            confirmed_count=0,
        )

        table = _audit_summary_table(audit)

        self.assertEqual(table.iloc[0]["Preparacion"], "INCOMPLETO")
        self.assertEqual(table.iloc[0]["Aprendizaje PAPER"], "NO")
        self.assertEqual(table.iloc[0]["Faltantes"], 3)
        self.assertEqual(table.iloc[0]["Bloqueos"], 2)

    def test_review_queue_table_expands_audit_items(self) -> None:
        audit = ReportAudit(
            symbol="SPY",
            data_as_of="2026-06-21",
            decision="NO_OPERAR",
            data_quality_status="APROBADO",
            panorama_status="REQUIERE_REVISION",
            risk_status="NO_DISPONIBLE",
            governance_status="NO_DISPONIBLE",
            readiness="BLOQUEADO",
            learning_ready=False,
            missing_evidence=("panorama: REQUIERE_REVISION",),
            blockers=("invalidacion_activa: Noticia",),
            detected_strategies=("CT15",),
            package_id="SPY_2026-06-21",
            tentative_bias="CALL",
            report_path="report.json",
        )

        table = _review_queue_table(audit)

        self.assertEqual(list(table["Prioridad"]), ["1_BLOQUEO", "2_FALTANTE"])
        self.assertEqual(table.iloc[0]["Tipo"], "INVALIDACION")
        self.assertEqual(table.iloc[1]["Tipo"], "COMPUERTA")
        self.assertEqual(table.iloc[0]["Paquete"], "SPY_2026-06-21")
        self.assertEqual(table.iloc[0]["Sesgo tentativo"], "CALL")

    def test_review_queue_upload_table_requires_contract_columns(self) -> None:
        import pandas as pd

        with self.assertRaises(ValueError):
            _review_queue_upload_table(pd.DataFrame({"symbol": ["SPY"]}))

    def test_review_queue_upload_table_normalizes_batch_csv(self) -> None:
        import pandas as pd

        table = _review_queue_upload_table(
            pd.DataFrame(
                [
                    {
                        "priority": "2_FALTANTE",
                        "symbol": "SPY",
                        "data_as_of": "2026-06-21",
                        "package_id": "SPY_2026-06-21",
                        "readiness": "INCOMPLETO",
                        "decision": "NO_OPERAR",
                        "review_type": "COMPUERTA",
                        "source": "panorama",
                        "evidence": "panorama: REQUIERE_REVISION",
                        "tentative_bias": "CALL",
                        "detected_strategies": "EXPUESTO",
                        "report_path": "report.json",
                    }
                ]
            )
        )

        self.assertEqual(table.iloc[0]["Prioridad"], "2_FALTANTE")
        self.assertEqual(table.iloc[0]["Tipo"], "COMPUERTA")
        self.assertEqual(table.iloc[0]["Paquete"], "SPY_2026-06-21")
        self.assertEqual(table.iloc[0]["Reporte"], "report.json")

    def test_filtered_review_queue_uses_selected_dimensions(self) -> None:
        import pandas as pd

        queue = pd.DataFrame(
            [
                {
                    "Prioridad": "1_BLOQUEO",
                    "Tipo": "INVALIDACION",
                    "Paquete": "A",
                },
                {
                    "Prioridad": "2_FALTANTE",
                    "Tipo": "COMPUERTA",
                    "Paquete": "B",
                },
            ]
        )

        filtered = _filtered_review_queue(
            queue,
            priorities=["2_FALTANTE"],
            review_types=["COMPUERTA"],
            packages=["B"],
        )

        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered.iloc[0]["Paquete"], "B")

    def test_case_intake_upload_table_requires_contract_columns(self) -> None:
        import pandas as pd

        with self.assertRaises(ValueError):
            _case_intake_upload_table(pd.DataFrame({"symbol": ["SPY"]}))

    def test_case_intake_upload_table_counts_human_pending_fields(self) -> None:
        import pandas as pd

        table = _case_intake_upload_table(
            pd.DataFrame(
                [
                    {
                        "symbol": "SPY",
                        "session": "2026-06-21",
                        "timeframe_15m_file": "SPY_15m.txt",
                        "timeframe_1h_file": "SPY_1H.txt",
                        "timeframe_1d_file": "SPY_1D.txt",
                        "tc2000_export_checked": "PENDIENTE",
                        "chart_screenshot_or_note": "",
                        "primary_setup_to_review": "Expuesto",
                        "manual_reviews_pending": "panorama",
                        "risk_review_status": "NO_DISPONIBLE",
                        "governance_review_status": "NO_DISPONIBLE",
                        "paper_trade_taken": "NO",
                        "paper_trade_result": "",
                        "operator_notes": "",
                    }
                ]
            )
        )

        self.assertEqual(table.iloc[0]["Paquete"], "SPY_2026-06-21")
        self.assertEqual(table.iloc[0]["Setup a revisar"], "Expuesto")
        self.assertGreater(table.iloc[0]["Pendientes intake"], 0)
        self.assertIn("risk_review_status", table.iloc[0]["Campos pendientes"])

    def test_operator_board_upload_table_requires_contract_columns(self) -> None:
        import pandas as pd

        with self.assertRaises(ValueError):
            _operator_board_upload_table(pd.DataFrame({"package_id": ["SPY"]}))

    def test_operator_board_upload_table_normalizes_batch_board(self) -> None:
        import pandas as pd

        table = _operator_board_upload_table(
            pd.DataFrame(
                [
                    {
                        "package_id": "SPY_2026-06-21",
                        "symbol": "SPY",
                        "session": "2026-06-21",
                        "decision": "NO_OPERAR",
                        "readiness": "INCOMPLETO",
                        "learning_ready": "NO",
                        "tentative_bias": "CALL",
                        "detected_count": "3",
                        "confirmed_count": "0",
                        "missing_total": "8",
                        "blocker_total": "0",
                        "first_missing_evidence": "panorama: REQUIERE_REVISION",
                        "first_blocker": "",
                        "data_quality": "APROBADO",
                        "panorama": "REQUIERE_REVISION",
                        "risk": "NO_DISPONIBLE",
                        "governance": "NO_DISPONIBLE",
                        "timeframes": "15m,1H,1D",
                        "report_path": "report.json",
                    }
                ]
            )
        )

        self.assertEqual(table.iloc[0]["Paquete"], "SPY_2026-06-21")
        self.assertEqual(table.iloc[0]["Readiness"], "INCOMPLETO")
        self.assertEqual(table.iloc[0]["Primer pendiente"], "panorama: REQUIERE_REVISION")

    def test_data_source_table_summarizes_provider_timeframes_and_files(self) -> None:
        table = _data_source_table(
            {
                "provider": "TC2000_UPLOAD",
                "timeframes": ["15m", "1H"],
                "files": {"1H": "SPY_1H.txt", "15m": "SPY_15m.txt"},
            }
        )

        self.assertEqual(table.iloc[0]["Fuente"], "TC2000_UPLOAD")
        self.assertEqual(table.iloc[0]["Proveedor"], "N/D")
        self.assertEqual(table.iloc[0]["Temporalidades"], "15m, 1H")
        self.assertEqual(
            table.iloc[0]["Archivos"],
            "15m: SPY_15m.txt, 1H: SPY_1H.txt",
        )

    def test_strategy_radar_shows_next_required_item(self) -> None:
        evaluation = StrategyEvaluation(
            strategy_id="CT15_ALCISTA",
            name="Cambio de Tendencia en 15 Alcista",
            bias=DirectionBias.CALL,
            detected=True,
            criteria=(
                CriterionEvaluation(
                    "ok",
                    "Cumplido",
                    EvaluationStatus.CUMPLE,
                    True,
                    "",
                    "test",
                ),
                CriterionEvaluation(
                    "pending",
                    "Pendiente clave",
                    EvaluationStatus.NO_DISPONIBLE,
                    True,
                    "",
                    "test",
                ),
            ),
        )

        table = _strategy_radar_table((evaluation,))

        self.assertEqual(
            table.iloc[0]["Siguiente revision"],
            "Pendiente clave (NO_DISPONIBLE)",
        )
        self.assertEqual(table.iloc[0]["Categoria"], "CAMBIO_TENDENCIA")
        self.assertEqual(table.iloc[0]["Requiere confirmacion"], "SI")

    def test_strategy_radar_marks_non_detected_diagnostics(self) -> None:
        evaluation = StrategyEvaluation(
            strategy_id="SIN_CT15",
            name="Sin Cambio de Tendencia en 15",
            bias=DirectionBias.NEUTRAL,
            detected=False,
            criteria=(),
        )

        table = _strategy_radar_table((evaluation,))

        self.assertEqual(table.iloc[0]["Categoria"], "DIAGNOSTICO")
        self.assertEqual(table.iloc[0]["Detectada"], "NO")

    def test_strategy_radar_preserves_timeframe(self) -> None:
        evaluation = StrategyEvaluation(
            strategy_id="EXPUESTO_BOLLINGER_INFERIOR",
            name="Expuesto en Bollinger",
            bias=DirectionBias.CALL,
            detected=True,
            criteria=(),
            timeframe="15m",
        )

        table = _strategy_radar_table((evaluation,))

        self.assertEqual(table.iloc[0]["Temporalidad"], "15m")

    def test_pending_common_news_review_does_not_clear_existing_evidence(self) -> None:
        reviews = {"common.news_clear": True}

        _record_common_news_review(reviews, None)

        self.assertTrue(reviews["common.news_clear"])

    def test_explicit_common_news_review_overrides_previous_value(self) -> None:
        reviews = {"common.news_clear": True}

        _record_common_news_review(reviews, False)

        self.assertFalse(reviews["common.news_clear"])

    def test_effective_common_news_review_prefers_recorded_evidence(self) -> None:
        self.assertTrue(
            _effective_common_news_review({"common.news_clear": True}, None)
        )

    def test_effective_common_news_review_uses_fallback_when_missing(self) -> None:
        self.assertFalse(_effective_common_news_review({}, False))

    def test_bollinger_dashboard_excludes_stale_future_and_closed_session_states(self) -> None:
        from app import _bollinger_state_is_current
        now = datetime(2026, 10, 9, 14, 0, tzinfo=timezone.utc)
        current = {"source_timestamp": "2026-10-09T13:59:00+00:00"}
        self.assertTrue(_bollinger_state_is_current(current, now=now, market_open=True))
        self.assertFalse(_bollinger_state_is_current(current, now=now, market_open=False))
        self.assertFalse(_bollinger_state_is_current({"source_timestamp": "2026-10-09T13:55:00+00:00"}, now=now, market_open=True))
        self.assertFalse(_bollinger_state_is_current({"source_timestamp": "2026-10-09T14:01:00+00:00"}, now=now, market_open=True))

    def test_app_renders_without_exceptions(self) -> None:
        app_path = Path(__file__).resolve().parents[1] / "app.py"
        app = AppTest.from_file(str(app_path)).run(timeout=20)
        self.assertFalse(app.exception)

    def test_synthetic_demo_runs_full_analysis_without_exceptions(self) -> None:
        # The analysis module is retained internally, outside the simplified navigation.
        app = AppTest.from_string("from app import main, render_analysis\nmain()\nrender_analysis()").run(timeout=20)
        demo = next(
            item for item in app.checkbox if item.label == "Usar demostración sintética"
        )
        demo.set_value(True)
        app.run(timeout=30)

        self.assertFalse(app.exception)
        self.assertTrue(any("Radar de detectores" in item.value for item in app.markdown))
        self.assertTrue(
            any("Recomendación asistida: NO OPERAR" in item.value for item in app.warning)
        )


if __name__ == "__main__":
    unittest.main()
