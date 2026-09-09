"""Saneamiento comun para diagnosticos persistidos o mostrados al operador."""

from __future__ import annotations

from collections.abc import Mapping
import re
from typing import Any


_LONG_SECRET = re.compile(
    r"(?<![A-Za-z0-9])[A-Za-z0-9_./+=-]{24,}(?![A-Za-z0-9])"
)
_LABELED_SECRET = re.compile(
    r"(?i)(api[_ -]?key|api[_ -]?secret|secret|authorization|token|password)"
    r"\s*[:=]\s*\S+"
)
_SENSITIVE_KEY = re.compile(
    r"(?i)(?:^|[_ -])"
    r"(?:api.?key|api.?secret|secret|authorization|token|password|credentials?)"
    r"(?:$|[_ -])"
)
_SAFE_SECURITY_METADATA = {"secrets_exposed", "error_recorded"}


def sanitize_diagnostic_detail(value: Any, *, limit: int = 500) -> str:
    """Conserva contexto breve sin copiar patrones habituales de secretos."""
    if limit <= 0:
        raise ValueError("El limite debe ser mayor que cero.")
    detail = _LABELED_SECRET.sub(r"\1=[REDACTED]", str(value))
    detail = _LONG_SECRET.sub("[REDACTED]", detail)
    detail = " ".join(detail.split())
    return (detail or "Sin detalle disponible.")[:limit]


def sanitize_diagnostic_payload(value: Any) -> Any:
    """Sanea estructuras JSON y elimina valores de claves sensibles."""
    if isinstance(value, Mapping):
        return {
            str(key): (
                "[REDACTED]"
                if (
                    str(key).strip().lower() not in _SAFE_SECURITY_METADATA
                    and _SENSITIVE_KEY.search(str(key))
                )
                else sanitize_diagnostic_payload(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [sanitize_diagnostic_payload(item) for item in value]
    if isinstance(value, str):
        return sanitize_diagnostic_detail(value, limit=2000)
    return value
