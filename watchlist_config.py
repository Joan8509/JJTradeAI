"""Lista de vigilancia compartida por la app y el scanner."""

from __future__ import annotations

import json
from pathlib import Path


DEFAULT_WATCHLIST_PATH = Path("config/watchlist.json")
FALLBACK_SYMBOLS = ("SPY", "QQQ")
FALLBACK_BENCHMARKS = ("SPY", "QQQ", "IWM", "DIA")


def load_watchlist(path: str | Path = DEFAULT_WATCHLIST_PATH) -> dict[str, tuple[str, ...]]:
    """Carga y normaliza simbolos; usa valores seguros si falta el archivo."""
    target = Path(path)
    if not target.exists():
        return {"symbols": FALLBACK_SYMBOLS, "benchmarks": FALLBACK_BENCHMARKS}
    payload = json.loads(target.read_text(encoding="utf-8"))

    def normalized(name: str, fallback: tuple[str, ...]) -> tuple[str, ...]:
        values = payload.get(name, ())
        if not isinstance(values, list):
            raise ValueError(f"{name} debe ser una lista en {target}.")
        result = tuple(dict.fromkeys(str(item).strip().upper() for item in values if str(item).strip()))
        return result or fallback

    return {
        "symbols": normalized("symbols", FALLBACK_SYMBOLS),
        "benchmarks": normalized("benchmarks", FALLBACK_BENCHMARKS),
    }


WATCHLIST = load_watchlist()
DEFAULT_SYMBOLS_TEXT = ",".join(WATCHLIST["symbols"])
DEFAULT_BENCHMARKS_TEXT = ",".join(WATCHLIST["benchmarks"])
