"""Small helpers: Kubernetes quantity parsing, formatting and selectors."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

_QUANTITY_RE = re.compile(r"^([+-]?[0-9]*\.?[0-9]+(?:[eE][+-]?[0-9]+)?)([a-zA-Z]{0,2})$")
_SUFFIX = {
    "": 1.0,
    "n": 1e-9,
    "u": 1e-6,
    "m": 1e-3,
    "k": 1e3,
    "K": 1e3,
    "M": 1e6,
    "G": 1e9,
    "T": 1e12,
    "P": 1e15,
    "E": 1e18,
    "Ki": 2.0**10,
    "Mi": 2.0**20,
    "Gi": 2.0**30,
    "Ti": 2.0**40,
    "Pi": 2.0**50,
    "Ei": 2.0**60,
}


def parse_quantity(value: Any) -> float | None:
    """Parse a Kubernetes resource quantity ("500m", "1Gi", "2") into a float of base units."""
    if value is None or value == "":
        return None
    if isinstance(value, int | float):
        return float(value)
    match = _QUANTITY_RE.match(str(value).strip())
    if not match or match.group(2) not in _SUFFIX:
        return None
    return float(match.group(1)) * _SUFFIX[match.group(2)]


def parse_cpu(value: Any) -> float | None:
    """CPU quantity in cores."""
    return parse_quantity(value)


def parse_memory(value: Any) -> float | None:
    """Memory quantity in bytes."""
    return parse_quantity(value)


def fmt_bytes(value: float | None) -> str:
    if value is None:
        return "-"
    for unit, size in (("Gi", 2**30), ("Mi", 2**20), ("Ki", 2**10)):
        if abs(value) >= size:
            return f"{value / size:.1f}{unit}"
    return f"{value:.0f}B"


def fmt_cpu(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value * 1000:.0f}m"


def fmt_pct(value: float | None) -> str:
    return "-" if value is None else f"{value * 100:.0f}%"


def label_selector(selector: dict | None) -> str:
    """Convert a LabelSelector object into the string form accepted by the API server."""
    if not selector:
        return ""
    parts = [f"{k}={v}" for k, v in sorted((selector.get("matchLabels") or {}).items())]
    for expr in selector.get("matchExpressions") or []:
        key, op, values = expr.get("key"), expr.get("operator"), expr.get("values") or []
        if op == "In":
            parts.append(f"{key} in ({','.join(values)})")
        elif op == "NotIn":
            parts.append(f"{key} notin ({','.join(values)})")
        elif op == "Exists":
            parts.append(key)
        elif op == "DoesNotExist":
            parts.append(f"!{key}")
    return ",".join(parts)


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def event_time(event: dict) -> datetime | None:
    return parse_time(
        event.get("lastTimestamp")
        or event.get("eventTime")
        or (event.get("series") or {}).get("lastObservedTime")
        or event.get("firstTimestamp")
        or (event.get("metadata") or {}).get("creationTimestamp")
    )


def to_json(data: Any, limit: int | None = None) -> str:
    text = json.dumps(data, default=str, indent=1)
    if limit and len(text) > limit:
        return text[:limit] + f"\n... [truncated {len(text) - limit} chars]"
    return text


_SECRET_PATTERNS = [
    (re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}"), r"\1 [REDACTED]"),
    (
        re.compile(
            r"(?i)\b(password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key|authorization)"
            r"([\"']?\s*[:=]\s*[\"']?)(?!\[REDACTED)[^\s\"',;&]+"
        ),
        r"\1\2[REDACTED]",
    ),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}"), "[REDACTED_JWT]"),
    (re.compile(r"\bsha256~[A-Za-z0-9_-]{20,}"), "[REDACTED_TOKEN]"),
    (re.compile(r"\b(?:sk-[A-Za-z0-9_-]{16,}|AKIA[0-9A-Z]{16})\b"), "[REDACTED_KEY]"),
]


def redact(value: Any) -> Any:
    """Mask credentials/tokens in strings, recursively through dicts and lists."""
    if isinstance(value, str):
        for rx, repl in _SECRET_PATTERNS:
            value = rx.sub(repl, value)
        return value
    if isinstance(value, dict):
        return {k: redact(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [redact(v) for v in value]
    return value
