"""W3C traceparent / OTel-compatible trace context.

Adopts an inbound ``traceparent`` header when present (cross-system
correlation), otherwise generates a fresh trace/span pair. Stored in a
ContextVar so concurrent agent contexts don't share IDs. The trace ID format
matches what Langfuse/OTel emit — correlate by searching the ID in both tools.
"""

from __future__ import annotations

import secrets
from contextvars import ContextVar

_trace_id: ContextVar[str | None] = ContextVar("glitchtip_trace_id", default=None)
_span_id: ContextVar[str | None] = ContextVar("glitchtip_span_id", default=None)


def new_trace_id() -> str:
    return secrets.token_hex(16)  # 32 hex chars


def new_span_id() -> str:
    return secrets.token_hex(8)  # 16 hex chars


def parse_traceparent(header: str | None) -> tuple[str, str] | None:
    """Parse ``00-<32hex>-<16hex>-<flags>``. Returns (trace_id, span_id)|None."""
    if not header:
        return None
    parts = header.strip().split("-")
    if len(parts) != 4:
        return None
    _ver, tid, sid, _flags = parts
    if len(tid) != 32 or len(sid) != 16:
        return None
    try:
        int(tid, 16)
        int(sid, 16)
    except ValueError:
        return None
    if tid == "0" * 32 or sid == "0" * 16:  # all-zero IDs are invalid per spec
        return None
    return tid.lower(), sid.lower()


def ensure(traceparent: str | None = None) -> tuple[str, str]:
    """Adopt the inbound traceparent or keep/generate the current context."""
    if traceparent:
        parsed = parse_traceparent(traceparent)
        if parsed:
            tid, _parent_span = parsed
            _trace_id.set(tid)
            _span_id.set(new_span_id())
            return tid, _span_id.get()  # type: ignore[return-value]
    if _trace_id.get() is None:
        _trace_id.set(new_trace_id())
        _span_id.set(new_span_id())
    return _trace_id.get(), _span_id.get()  # type: ignore[return-value]


def current() -> tuple[str | None, str | None]:
    return _trace_id.get(), _span_id.get()


def traceparent() -> str | None:
    tid, sid = current()
    if not tid or not sid:
        return None
    return f"00-{tid}-{sid}-01"


def reset() -> None:
    _trace_id.set(None)
    _span_id.set(None)
