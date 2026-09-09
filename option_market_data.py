"""Cadena de opciones Alpaca y selección auditable de contratos líquidos."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import re
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request

from alpaca_market_data import AlpacaMarketConfig, Transport, _default_transport
from analysis_models import GateStatus
from risk_engine import OptionQuote, RiskEvaluation, RiskLimits, evaluate_option_risk


_OCC_SYMBOL = re.compile(r"^([A-Z0-9.]{1,8})(\d{6})([CP])(\d{8})$")


@dataclass(frozen=True)
class OptionSnapshot:
    """Snapshot canónico de un contrato de opción."""

    symbol: str
    underlying_symbol: str
    option_type: str
    strike: float
    expiration: date
    bid: float
    ask: float
    bid_size: int
    ask_size: int
    quote_timestamp: datetime | None
    latest_trade: float | None
    implied_volatility: float | None
    delta: float | None
    gamma: float | None
    theta: float | None
    vega: float | None
    feed: str


@dataclass(frozen=True)
class OptionSelectionPolicy:
    """Política explícita; no contiene umbrales metodológicos ocultos."""

    risk_limits: RiskLimits
    min_bid_size: int
    min_ask_size: int
    min_delta: float
    max_delta: float
    max_results: int = 5

    def __post_init__(self) -> None:
        if min(self.min_bid_size, self.min_ask_size) < 0:
            raise ValueError("Los tamaños mínimos no pueden ser negativos.")
        if not 0 <= self.min_delta <= self.max_delta <= 1:
            raise ValueError("El rango de delta debe estar entre 0 y 1.")
        if self.max_results <= 0:
            raise ValueError("max_results debe ser mayor que cero.")


@dataclass(frozen=True)
class OptionCandidate:
    snapshot: OptionSnapshot
    risk: RiskEvaluation
    liquidity_approved: bool
    delta_approved: bool

    @property
    def eligible(self) -> bool:
        return (
            self.risk.status is GateStatus.APROBADO
            and self.liquidity_approved
            and self.delta_approved
            and self.snapshot.feed == "opra"
        )


class AlpacaOptionDataProvider:
    """Cliente de solo lectura para snapshots de cadenas de opciones."""

    def __init__(
        self,
        config: AlpacaMarketConfig,
        *,
        option_feed: str = "indicative",
        transport: Transport = _default_transport,
    ) -> None:
        if option_feed not in {"indicative", "opra"}:
            raise ValueError("El feed de opciones debe ser indicative u opra.")
        self.config = config
        self.option_feed = option_feed
        self._transport = transport

    def fetch_chain(
        self,
        underlying_symbol: str,
        *,
        option_type: str,
        expiration_date_gte: date,
        expiration_date_lte: date,
        strike_price_gte: float | None = None,
        strike_price_lte: float | None = None,
    ) -> tuple[OptionSnapshot, ...]:
        underlying = underlying_symbol.strip().upper()
        normalized_type = option_type.strip().lower()
        if not underlying:
            raise ValueError("El símbolo subyacente es obligatorio.")
        if normalized_type not in {"call", "put"}:
            raise ValueError("option_type debe ser call o put.")
        if expiration_date_lte < expiration_date_gte:
            raise ValueError("El rango de vencimiento está invertido.")
        params: dict[str, Any] = {
            "feed": self.option_feed,
            "type": normalized_type,
            "expiration_date_gte": expiration_date_gte.isoformat(),
            "expiration_date_lte": expiration_date_lte.isoformat(),
            "limit": 1000,
        }
        if strike_price_gte is not None:
            params["strike_price_gte"] = strike_price_gte
        if strike_price_lte is not None:
            params["strike_price_lte"] = strike_price_lte

        snapshots: list[OptionSnapshot] = []
        page_token: str | None = None
        while True:
            page_params = dict(params)
            if page_token:
                page_params["page_token"] = page_token
            request = Request(
                f"{self.config.base_url}/v1beta1/options/snapshots/{underlying}?"
                f"{urlencode(page_params)}",
                headers={
                    "APCA-API-KEY-ID": self.config.api_key,
                    "APCA-API-SECRET-KEY": self.config.api_secret,
                    "Accept": "application/json",
                },
            )
            payload = self._transport(request)
            raw_snapshots = payload.get("snapshots") or {}
            if not isinstance(raw_snapshots, dict):
                raise ValueError("Respuesta de cadena Alpaca inválida.")
            snapshots.extend(
                _parse_snapshot(symbol, raw, underlying, self.option_feed)
                for symbol, raw in raw_snapshots.items()
            )
            page_token = payload.get("next_page_token")
            if not page_token:
                break
        return tuple(snapshots)


def select_option_candidates(
    snapshots: tuple[OptionSnapshot, ...],
    *,
    spot: float,
    policy: OptionSelectionPolicy,
    as_of: date,
) -> tuple[OptionCandidate, ...]:
    """Evalúa y ordena contratos; `eligible` exige cotización OPRA."""
    candidates = []
    for snapshot in snapshots:
        if snapshot.ask <= 0 or snapshot.bid < 0 or snapshot.ask < snapshot.bid:
            continue
        risk = evaluate_option_risk(
            OptionQuote(
                symbol=snapshot.symbol,
                option_type=snapshot.option_type,
                spot=spot,
                strike=snapshot.strike,
                bid=snapshot.bid,
                ask=snapshot.ask,
                expiration=snapshot.expiration,
            ),
            policy.risk_limits,
            as_of=as_of,
        )
        abs_delta = abs(snapshot.delta) if snapshot.delta is not None else None
        candidates.append(
            OptionCandidate(
                snapshot=snapshot,
                risk=risk,
                liquidity_approved=(
                    snapshot.bid_size >= policy.min_bid_size
                    and snapshot.ask_size >= policy.min_ask_size
                ),
                delta_approved=(
                    abs_delta is not None
                    and policy.min_delta <= abs_delta <= policy.max_delta
                ),
            )
        )
    candidates.sort(
        key=lambda item: (
            not item.eligible,
            item.risk.spread_pct,
            item.risk.spot_strike_distance_pct,
            item.snapshot.expiration,
        )
    )
    return tuple(candidates[: policy.max_results])


def _parse_snapshot(
    symbol: str, payload: Any, underlying: str, feed: str
) -> OptionSnapshot:
    if not isinstance(payload, dict):
        raise ValueError(f"Snapshot inválido para {symbol}.")
    parsed = _parse_occ_symbol(symbol)
    quote = payload.get("latestQuote") or {}
    trade = payload.get("latestTrade") or {}
    greeks = payload.get("greeks") or {}
    quote_time = quote.get("t")
    return OptionSnapshot(
        symbol=symbol,
        underlying_symbol=underlying,
        option_type=parsed[0],
        strike=parsed[1],
        expiration=parsed[2],
        bid=float(quote.get("bp") or 0),
        ask=float(quote.get("ap") or 0),
        bid_size=int(quote.get("bs") or 0),
        ask_size=int(quote.get("as") or 0),
        quote_timestamp=(
            datetime.fromisoformat(str(quote_time).replace("Z", "+00:00"))
            if quote_time
            else None
        ),
        latest_trade=float(trade["p"]) if trade.get("p") is not None else None,
        implied_volatility=(
            float(payload["impliedVolatility"])
            if payload.get("impliedVolatility") is not None
            else None
        ),
        delta=float(greeks["delta"]) if greeks.get("delta") is not None else None,
        gamma=float(greeks["gamma"]) if greeks.get("gamma") is not None else None,
        theta=float(greeks["theta"]) if greeks.get("theta") is not None else None,
        vega=float(greeks["vega"]) if greeks.get("vega") is not None else None,
        feed=feed,
    )


def _parse_occ_symbol(symbol: str) -> tuple[str, float, date]:
    match = _OCC_SYMBOL.fullmatch(symbol)
    if not match:
        raise ValueError(f"Símbolo OCC no reconocido: {symbol}")
    expiration = datetime.strptime(match.group(2), "%y%m%d").date()
    option_type = "CALL" if match.group(3) == "C" else "PUT"
    strike = int(match.group(4)) / 1000
    return option_type, strike, expiration
