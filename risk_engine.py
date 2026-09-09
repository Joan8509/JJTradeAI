"""Evaluación configurable de liquidez, contrato y capital para opciones."""

from dataclasses import dataclass
from datetime import date

from analysis_models import CriterionEvaluation, EvaluationStatus, GateStatus


@dataclass(frozen=True)
class OptionQuote:
    """Cotización mínima necesaria para evaluar un contrato."""

    symbol: str
    option_type: str
    spot: float
    strike: float
    bid: float
    ask: float
    expiration: date
    contracts: int = 1


@dataclass(frozen=True)
class RiskLimits:
    """Límites aprobados; ninguno se infiere automáticamente."""

    max_spread_absolute: float | None = None
    max_spread_pct: float | None = None
    max_spot_strike_distance_pct: float | None = None
    min_days_to_expiration: int | None = None
    max_position_cost: float | None = None


@dataclass(frozen=True)
class RiskEvaluation:
    """Resultado auditable de la compuerta de riesgo."""

    status: GateStatus
    criteria: tuple[CriterionEvaluation, ...]
    spread: float
    spread_pct: float
    spot_strike_distance_pct: float
    days_to_expiration: int
    position_cost: float


def evaluate_option_risk(
    quote: OptionQuote,
    limits: RiskLimits,
    *,
    as_of: date | None = None,
) -> RiskEvaluation:
    """Evalúa una opción y rechaza límites ausentes o incumplidos."""
    option_type = quote.option_type.strip().upper()
    if option_type not in {"CALL", "PUT"}:
        raise ValueError("option_type debe ser CALL o PUT.")
    if min(quote.spot, quote.strike, quote.bid, quote.ask) < 0:
        raise ValueError("Los precios no pueden ser negativos.")
    if quote.spot == 0 or quote.strike == 0 or quote.ask == 0:
        raise ValueError("Spot, strike y ask deben ser mayores que cero.")
    if quote.ask < quote.bid:
        raise ValueError("Ask no puede ser menor que bid.")
    if quote.contracts <= 0:
        raise ValueError("La cantidad de contratos debe ser positiva.")
    numeric_limits = (
        limits.max_spread_absolute,
        limits.max_spread_pct,
        limits.max_spot_strike_distance_pct,
        limits.max_position_cost,
    )
    if any(value is not None and value < 0 for value in numeric_limits):
        raise ValueError("Los límites de riesgo no pueden ser negativos.")
    if limits.min_days_to_expiration is not None and limits.min_days_to_expiration < 0:
        raise ValueError("El mínimo de días al vencimiento no puede ser negativo.")

    evaluation_date = as_of or date.today()
    spread = quote.ask - quote.bid
    spread_pct = spread / quote.ask * 100
    distance_pct = abs(quote.strike - quote.spot) / quote.spot * 100
    days_to_expiration = (quote.expiration - evaluation_date).days
    position_cost = quote.ask * 100 * quote.contracts

    criteria: list[CriterionEvaluation] = [
        CriterionEvaluation(
            criterion_id="contract_not_expired",
            name="Contrato no expirado",
            status=(
                EvaluationStatus.CUMPLE
                if days_to_expiration >= 0
                else EvaluationStatus.NO_CUMPLE
            ),
            required=True,
            detail=f"Días={days_to_expiration}.",
            source="docs/strategies/OPCIONES_COMPRA_VENTA.md",
        )
    ]
    specs = (
        ("spread_absolute", "Spread absoluto", spread, limits.max_spread_absolute),
        ("spread_pct", "Spread porcentual", spread_pct, limits.max_spread_pct),
        (
            "spot_strike_distance",
            "Distancia spot/strike porcentual",
            distance_pct,
            limits.max_spot_strike_distance_pct,
        ),
        (
            "position_cost",
            "Costo total de posición",
            position_cost,
            limits.max_position_cost,
        ),
    )
    for criterion_id, name, value, maximum in specs:
        status = (
            EvaluationStatus.NO_DISPONIBLE
            if maximum is None
            else EvaluationStatus.CUMPLE
            if value <= maximum
            else EvaluationStatus.NO_CUMPLE
        )
        criteria.append(
            CriterionEvaluation(
                criterion_id=criterion_id,
                name=name,
                status=status,
                required=True,
                detail=(
                    f"Valor={value:.2f}; máximo="
                    f"{maximum if maximum is not None else 'no configurado'}"
                ),
                source="docs/strategies/OPCIONES_COMPRA_VENTA.md",
            )
        )

    dte_limit = limits.min_days_to_expiration
    dte_status = (
        EvaluationStatus.NO_DISPONIBLE
        if dte_limit is None
        else EvaluationStatus.CUMPLE
        if days_to_expiration >= dte_limit
        else EvaluationStatus.NO_CUMPLE
    )
    criteria.append(
        CriterionEvaluation(
            criterion_id="days_to_expiration",
            name="Días al vencimiento",
            status=dte_status,
            required=True,
            detail=(
                f"Días={days_to_expiration}; mínimo="
                f"{dte_limit if dte_limit is not None else 'no configurado'}"
            ),
            source="docs/strategies/OPCIONES_COMPRA_VENTA.md",
        )
    )

    statuses = {criterion.status for criterion in criteria}
    if EvaluationStatus.NO_CUMPLE in statuses:
        gate_status = GateStatus.RECHAZADO
    elif EvaluationStatus.NO_DISPONIBLE in statuses:
        gate_status = GateStatus.NO_DISPONIBLE
    elif EvaluationStatus.REQUIERE_REVISION in statuses:
        gate_status = GateStatus.REQUIERE_REVISION
    else:
        gate_status = GateStatus.APROBADO

    return RiskEvaluation(
        status=gate_status,
        criteria=tuple(criteria),
        spread=round(spread, 4),
        spread_pct=round(spread_pct, 4),
        spot_strike_distance_pct=round(distance_pct, 4),
        days_to_expiration=days_to_expiration,
        position_cost=round(position_cost, 2),
    )
