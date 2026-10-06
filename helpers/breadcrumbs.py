"""In-memory breadcrumb ring buffer.

Breadcrumbs give GlitchTip events minimal diagnostic context (which tool or
API route ran before the error). Entries carry names/status only — never
tool args, output text, or anything that could hold a secret value.
"""

from __future__ import annotations

import time
from collections import deque
from typing import Any

_max = 50
_buf: deque[dict[str, Any]] = deque(maxlen=_max)

# Keys that must never appear in crumb payloads — belt-and-suspenders for the
# "names and statuses only" contract.
_FORBIDDEN = frozenset({"value", "secret", "token", "password", "args", "output", "content"})


def configure(max_entries: int) -> None:
    global _max, _buf
    _max = max(1, int(max_entries))
    _buf = deque(_buf, maxlen=_max)


def crumb(category: str, message: str, data: dict[str, Any] | None = None) -> None:
    safe = {
        k: v for k, v in (data or {}).items() if k.lower() not in _FORBIDDEN
    }
    _buf.append(
        {
            "timestamp": time.time(),
            "category": category,
            "message": str(message)[:200],
            "level": "info",
            "data": safe,
        }
    )


def snapshot() -> list[dict[str, Any]]:
    return list(_buf)


def clear() -> None:
    _buf.clear()
