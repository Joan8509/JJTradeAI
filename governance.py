"""Controles operativos que rodean al motor de análisis de JJTrade AI.

Este módulo no detecta estrategias ni decide CALL/PUT. Evalúa si el flujo de
trabajo respeta límites educativos y si existe un plan antes de operar.
"""

from dataclasses import dataclass, field
from enum import Enum

from analysis_models import GateStatus


class TradingMode(str, Enum):
    """Entorno en el que el usuario documenta una posible operación."""

    PAPER = "PAPER"
    REAL = "REAL"


class OperationWorkflow(str, Enum):
    """Diferencia una entrada nueva de la gestión de una posición existente."""

    NUEVA_ENTRADA = "NUEVA_ENTRADA"
    GESTION_POSICION = "GESTION_POSICION"
    REFUERZO = "REFUERZO"


@dataclass(frozen=True)
class GovernanceLimits:
    """Límites iniciales extraídos de la capacitación y sujetos a revisión."""

    max_watchlist_symbols: int = 3
    max_new_trades_per_week: int = 3


@dataclass(frozen=True)
class GovernanceRequest:
    """Datos necesarios para revisar disciplina antes de una nueva entrada."""

    mode: TradingMode = TradingMode.PAPER
    workflow: OperationWorkflow = OperationWorkflow.NUEVA_ENTRADA
    watchlist_symbols: tuple[str, ...] = ()
    new_trades_this_week: int = 0
    entry_plan: str = ""
    exit_plan: str = ""
    real_mode_acknowledged: bool = False
    symbol: str = ""


@dataclass(frozen=True)
class GovernanceEvaluation:
    """Resultado explicable de la compuerta de gobierno operativo."""

    status: GateStatus
    reasons: tuple[str, ...] = field(default_factory=tuple)


def evaluate_governance(
    request: GovernanceRequest,
    limits: GovernanceLimits = GovernanceLimits(),
) -> GovernanceEvaluation:
    """Aprueba o rechaza el flujo sin interpretar la dirección del mercado."""
    if limits.max_watchlist_symbols <= 0 or limits.max_new_trades_per_week <= 0:
        raise ValueError("Los límites de gobierno deben ser mayores que cero.")
    if request.new_trades_this_week < 0:
        raise ValueError("El número de operaciones semanales no puede ser negativo.")

    reasons: list[str] = []
    unique_symbols = {
        symbol.strip().upper() for symbol in request.watchlist_symbols if symbol.strip()
    }
    requested_symbol = request.symbol.strip().upper()
    if requested_symbol and requested_symbol not in unique_symbols:
        reasons.append(
            f"{requested_symbol} no pertenece a la lista autorizada para esta revisi\u00f3n."
        )
    if len(unique_symbols) > limits.max_watchlist_symbols:
        reasons.append(
            f"El radar contiene {len(unique_symbols)} símbolos; el límite inicial "
            f"es {limits.max_watchlist_symbols}."
        )

    if request.workflow is OperationWorkflow.REFUERZO:
        reasons.append("REFUERZO no está habilitado en la primera versión.")

    if request.workflow is OperationWorkflow.NUEVA_ENTRADA:
        if request.new_trades_this_week >= limits.max_new_trades_per_week:
            reasons.append(
                "Se alcanzó el límite educativo de operaciones nuevas de la semana."
            )
        if not request.entry_plan.strip():
            reasons.append("Falta el plan escrito de entrada.")
        if not request.exit_plan.strip():
            reasons.append("Falta el plan escrito de salida.")

    if request.mode is TradingMode.REAL and not request.real_mode_acknowledged:
        reasons.append(
            "El modo REAL requiere aceptación humana explícita; nunca se desbloquea "
            "por rendimiento simulado."
        )

    status = GateStatus.RECHAZADO if reasons else GateStatus.APROBADO
    return GovernanceEvaluation(status=status, reasons=tuple(reasons))
