"""Política externa y enriquecimiento de alertas con opciones candidatas."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import date, timedelta
import json
from pathlib import Path
from typing import Any, Mapping

from option_market_data import (
    AlpacaOptionDataProvider,
    OptionCandidate,
    OptionSelectionPolicy,
    select_option_candidates,
)
from risk_engine import RiskLimits


POLICY_FIELDS = {
    "option_feed",
    "max_search_dte",
    "max_spread_absolute",
    "max_spread_pct",
    "max_spot_strike_distance_pct",
    "min_days_to_expiration",
    "max_position_cost",
    "min_bid_size",
    "min_ask_size",
    "min_delta",
    "max_delta",
    "max_results",
}


@dataclass(frozen=True)
class OptionOpportunityPolicy:
    """Configuración completa aprobada fuera del motor metodológico."""

    option_feed: str
    max_search_dte: int
    selection: OptionSelectionPolicy

    def __post_init__(self) -> None:
        if self.option_feed not in {"indicative", "opra"}:
            raise ValueError("option_feed debe ser indicative u opra.")
        minimum = self.selection.risk_limits.min_days_to_expiration
        if minimum is None:
            raise ValueError("min_days_to_expiration es obligatorio.")
        if self.max_search_dte < minimum:
            raise ValueError("max_search_dte no puede ser menor que el DTE mínimo.")


def load_option_opportunity_policy(path: str | Path) -> OptionOpportunityPolicy:
    """Carga JSON estricto: campos ausentes o desconocidos se rechazan."""
    policy_path = Path(path)
    try:
        payload = json.loads(policy_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"No se pudo leer la política de opciones: {policy_path}") from error
    if not isinstance(payload, dict):
        raise ValueError("La política de opciones debe ser un objeto JSON.")
    missing = sorted(POLICY_FIELDS.difference(payload))
    unknown = sorted(set(payload).difference(POLICY_FIELDS))
    if missing:
        raise ValueError("Faltan campos de política: " + ", ".join(missing))
    if unknown:
        raise ValueError("Campos de política desconocidos: " + ", ".join(unknown))
    try:
        limits = RiskLimits(
            max_spread_absolute=float(payload["max_spread_absolute"]),
            max_spread_pct=float(payload["max_spread_pct"]),
            max_spot_strike_distance_pct=float(payload["max_spot_strike_distance_pct"]),
            min_days_to_expiration=int(payload["min_days_to_expiration"]),
            max_position_cost=float(payload["max_position_cost"]),
        )
        selection = OptionSelectionPolicy(
            risk_limits=limits,
            min_bid_size=int(payload["min_bid_size"]),
            min_ask_size=int(payload["min_ask_size"]),
            min_delta=float(payload["min_delta"]),
            max_delta=float(payload["max_delta"]),
            max_results=int(payload["max_results"]),
        )
        return OptionOpportunityPolicy(
            option_feed=str(payload["option_feed"]).strip().lower(),
            max_search_dte=int(payload["max_search_dte"]),
            selection=selection,
        )
    except (TypeError, ValueError) as error:
        raise ValueError("La política de opciones contiene valores inválidos.") from error


class OptionOpportunityService:
    """Busca contratos únicamente cuando el reporte contiene sesgo CALL/PUT."""

    def __init__(
        self,
        provider: AlpacaOptionDataProvider,
        policy: OptionOpportunityPolicy,
    ) -> None:
        if provider.option_feed != policy.option_feed:
            raise ValueError("El feed del proveedor no coincide con la política.")
        self.provider = provider
        self.policy = policy

    def enrich(self, symbol: str, bundle: Any, report: Mapping[str, Any]) -> dict[str, Any]:
        enriched = deepcopy(dict(report))
        bias = _report_bias(enriched)
        if bias is None:
            enriched["option_selection"] = {
                "status": "SIN_SESGO",
                "reason": "El reporte no contiene sesgo CALL o PUT.",
                "candidates": [],
            }
            return enriched
        spot = _latest_spot(bundle)
        as_of = _report_date(enriched)
        limits = self.policy.selection.risk_limits
        distance = float(limits.max_spot_strike_distance_pct) / 100
        min_dte = int(limits.min_days_to_expiration)
        chain = self.provider.fetch_chain(
            symbol,
            option_type=bias.lower(),
            expiration_date_gte=as_of + timedelta(days=min_dte),
            expiration_date_lte=as_of + timedelta(days=self.policy.max_search_dte),
            strike_price_gte=spot * (1 - distance),
            strike_price_lte=spot * (1 + distance),
        )
        candidates = select_option_candidates(
            chain, spot=spot, policy=self.policy.selection, as_of=as_of
        )
        enriched["option_selection"] = {
            "status": "CANDIDATOS" if candidates else "SIN_CONTRATOS",
            "bias": bias,
            "spot": spot,
            "feed": self.policy.option_feed,
            "eligible_count": sum(item.eligible for item in candidates),
            "candidates": [_candidate_payload(item) for item in candidates],
        }
        return enriched


def _report_bias(report: Mapping[str, Any]) -> str | None:
    decision = report.get("decision", {})
    if not isinstance(decision, Mapping):
        return None
    final = str(decision.get("decision", "")).upper()
    tentative = str(decision.get("tentative_bias", "")).upper()
    return final if final in {"CALL", "PUT"} else tentative if tentative in {"CALL", "PUT"} else None


def _latest_spot(bundle: Any) -> float:
    frame = bundle.datasets.get("15m")
    if frame is None or frame.empty:
        raise ValueError("No existe una vela 15m para obtener el spot.")
    spot = float(frame.iloc[-1]["close"])
    if spot <= 0:
        raise ValueError("El spot del reporte debe ser mayor que cero.")
    return spot


def _report_date(report: Mapping[str, Any]) -> date:
    raw = str(report.get("data_as_of", ""))
    try:
        return date.fromisoformat(raw[:10])
    except ValueError as error:
        raise ValueError("data_as_of no contiene una fecha válida.") from error


def _candidate_payload(candidate: OptionCandidate) -> dict[str, Any]:
    snapshot = candidate.snapshot
    return {
        "symbol": snapshot.symbol,
        "option_type": snapshot.option_type,
        "strike": snapshot.strike,
        "expiration": snapshot.expiration.isoformat(),
        "bid": snapshot.bid,
        "ask": snapshot.ask,
        "bid_size": snapshot.bid_size,
        "ask_size": snapshot.ask_size,
        "delta": snapshot.delta,
        "implied_volatility": snapshot.implied_volatility,
        "spread_pct": candidate.risk.spread_pct,
        "position_cost": candidate.risk.position_cost,
        "risk_status": candidate.risk.status.value,
        "liquidity_approved": candidate.liquidity_approved,
        "delta_approved": candidate.delta_approved,
        "eligible": candidate.eligible,
        "feed": snapshot.feed,
        "quote_timestamp": snapshot.quote_timestamp.isoformat() if snapshot.quote_timestamp else None,
    }
