"""In-memory breadcrumb ring buffer.

Breadcrumbs give GlitchTip events minimal diagnostic context (which tool or
API route ran before the error). Entries carry names/status only — never
tool args, output text, or anything that could hold a secret value.
"""

from __future__ import annotations

import time
from collections import deque
from typing import Any

DEFAULT_MAX = 50

_buf: deque[dict[str, Any]] = deque(maxlen=DEFAULT_MAX)

# Substrings that must never appear in crumb keys — belt-and-suspenders for
# the "names and statuses only" contract. Any data key containing one of
# these is dropped (substring match, so `api_key`/`session_id`/... all die).
_FORBIDDEN = (
    "value", "secret", "token", "password", "key", "auth", "cookie",
    "session", "credential", "arg", "output", "content", "data", "body",
    "payload", "response", "result", "text", "input", "message",
)

_SCALARS = (str, int, float, bool, type(None))


def configure(max_entries: int) -> None:
    global _buf
    _buf = deque(_buf, maxlen=max(1, int(max_entries)))


def _safe_data(data: Any) -> dict[str, Any]:
    """Drop forbidden-keyed entries and coerce values to JSON-safe scalars.
    Never raises — a poison crumb must not break callers (never-raise
    contract) or brick event serialization (poisons every snapshot until
    evicted)."""
    if not isinstance(data, dict):
        return {}
    safe: dict[str, Any] = {}
    for k, v in data.items():
        if not isinstance(k, str):
            continue
        kl = k.lower()
        if any(forbidden in kl for forbidden in _FORBIDDEN):
            continue
        safe[k] = v if isinstance(v, _SCALARS) else str(v)[:200]
        if isinstance(safe[k], str):
            safe[k] = safe[k][:200]
    return safe


def crumb(category: str, message: str, data: dict[str, Any] | None = None) -> None:
    """Public helper — never raises (AGENTS.md contract)."""
    try:
        _buf.append(
            {
                "timestamp": time.time(),
                "category": str(category)[:50],
                "message": str(message)[:200],
                "level": "info",
                "data": _safe_data(data),
            }
        )
    except Exception:
        pass


def snapshot() -> list[dict[str, Any]]:
    return list(_buf)


def reset() -> None:
    """Contents AND configured capacity back to defaults (test/reload hook)."""
    configure(DEFAULT_MAX)
    _buf.clear()
