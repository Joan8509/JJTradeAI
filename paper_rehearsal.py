"""Ensayo PAPER sintetico de la infraestructura local de JJTrade AI."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Sequence

import pandas as pd

from live_market import MarketBar
from live_strategy_service import AlertRepository, ContinuousStrategyScanner
from market_reconciliation import MarketDataReconciler, MarketReconciliationRepository
from market_store import MarketBarStore, MarketContinuityService
from version import METHODOLOGY_VERSION


REHEARSAL_START = datetime(2026, 7, 23, 13, 30, tzinfo=timezone.utc)
DISCLAIMER = (
    "Ensayo sintetico de infraestructura: no valida estrategias, mercado real, "
    "rentabilidad ni ejecucion de ordenes."
)


class _NoBackfillProvider:
    def fetch_minute_bars(
        self, symbol: str, *, start: datetime, end: datetime
    ) -> pd.DataFrame:
        raise AssertionError("El ensayo no debe solicitar backfill externo.")


class _SyntheticRestProvider:
    def __init__(self, frame: pd.DataFrame) -> None:
        self.frame = frame

    def fetch_minute_bars(
        self, symbol: str, *, start: datetime, end: datetime
    ) -> pd.DataFrame:
        return self.frame[
            (self.frame["date"] >= start) & (self.frame["date"] < end)
        ].copy()


def _synthetic_bars(symbol: str = "SPY") -> list[MarketBar]:
    bars = []
    for minute in range(15):
        open_price = 550.0 + minute * 0.1
        close_price = open_price + 0.05
        bars.append(
            MarketBar(
                symbol=symbol,
                timestamp=REHEARSAL_START + timedelta(minutes=minute),
                open=open_price,
                high=close_price + 0.05,
                low=open_price - 0.05,
                close=close_price,
                volume=1_000 + minute * 10,
            )
        )
    return bars


def _frame_from_bars(bars: list[MarketBar]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "date": bar.timestamp,
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
                "volume": bar.volume,
            }
            for bar in bars
        ]
    )


def _rehearsal_report(symbol: str, bundle: Any) -> dict[str, Any]:
    data_as_of = bundle.datasets["15m"].iloc[-1]["date"]
    return {
        "symbol": symbol,
        "data_as_of": data_as_of.isoformat(),
        "methodology_version": METHODOLOGY_VERSION,
        "decision": {
            "decision": "NO_OPERAR",
            "reason": "Evento sintetico exclusivo para comprobar infraestructura.",
        },
        "strategy_summary": {"detected": 1, "confirmed": 1},
        "strategies": {
            "evaluations": [
                {
                    "strategy_id": "REHEARSAL_ONLY",
                    "detected": True,
                    "confirmed": True,
                }
            ]
        },
        "rehearsal": {
            "synthetic": True,
            "methodology_validated": False,
            "real_market_validated": False,
            "order_execution": False,
        },
    }


def run_paper_rehearsal(database: str | Path) -> dict[str, Any]:
    """Recorre el pipeline local sobre una base nueva y devuelve evidencia."""
    database_path = Path(database)
    if database_path.exists():
        raise ValueError("El ensayo requiere una base de datos nueva.")

    bars = _synthetic_bars()
    source_frame = _frame_from_bars(bars)
    store = MarketBarStore(database_path)
    continuity = MarketContinuityService(
        store,
        _NoBackfillProvider(),
        provider_name="REHEARSAL",
        feed="iex",
    )
    alerts = AlertRepository(database_path)
    reconciliations = MarketReconciliationRepository(database_path)
    scanner = ContinuousStrategyScanner(
        continuity,
        alerts,
        feed="iex",
        evaluator=_rehearsal_report,
        now=lambda: bars[-1].timestamp + timedelta(seconds=30),
        reconciler=MarketDataReconciler(_SyntheticRestProvider(source_frame)),
        reconciliation_repository=reconciliations,
    )

    result = None
    for bar in bars:
        current = scanner.on_bar(bar)
        if current is not None:
            result = current
    if result is None or result["alert_id"] is None:
        raise RuntimeError("El scanner no genero la alerta sintetica esperada.")

    alert_id = int(result["alert_id"])
    acknowledgement_id = alerts.record_acknowledgement(
        alert_id,
        status="VISTA",
        notes="Acuse automatico del ensayo PAPER sintetico.",
    )
    stored_alert = alerts.recent(limit=1)[0]
    stored_reconciliation = reconciliations.recent(limit=1)[0]
    stored_acknowledgement = alerts.acknowledgements(alert_id)[0]
    persisted = store.load_frame(
        symbol="SPY",
        provider="REHEARSAL",
        feed="iex",
    )

    checks = {
        "minute_bars_persisted": len(persisted) == 15,
        "single_alert_persisted": len(alerts.recent()) == 1,
        "reconciliation_approved": stored_reconciliation["status"] == "APROBADO",
        "setup_event_classified": stored_alert["event_type"] == "SETUP_CONFIRMADO",
        "acknowledgement_saved": stored_acknowledgement["status"] == "VISTA",
        "no_pending_acknowledgements": alerts.unacknowledged_count() == 0,
        "decision_remains_non_operational": stored_alert["decision"] == "NO_OPERAR",
    }
    return {
        "status": "OK" if all(checks.values()) else "BLOQUEADO",
        "mode": "PAPER_SYNTHETIC_REHEARSAL",
        "synthetic": True,
        "methodology_validated": False,
        "real_market_validated": False,
        "order_execution": False,
        "database": str(database_path),
        "alert_id": alert_id,
        "acknowledgement_id": acknowledgement_id,
        "event_type": stored_alert["event_type"],
        "reconciliation_status": stored_reconciliation["status"],
        "persisted_bar_count": len(persisted),
        "pending_acknowledgement_count": alerts.unacknowledged_count(),
        "checks": checks,
        "disclaimer": DISCLAIMER,
    }


def _write_output(path: str | Path, payload: dict[str, Any]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database",
        help="Base SQLite nueva. Si se omite, se usa una carpeta temporal.",
    )
    parser.add_argument("--output", help="Ruta opcional para guardar el reporte JSON.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.database:
        payload = run_paper_rehearsal(args.database)
    else:
        with TemporaryDirectory(prefix="jjtrade-paper-") as directory:
            payload = run_paper_rehearsal(Path(directory) / "rehearsal.db")
            payload["database"] = "TEMPORAL_ELIMINADA"
    if args.output:
        _write_output(args.output, payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["status"] == "OK" else 1


if __name__ == "__main__":
    raise SystemExit(main())
