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
    """Parse ``00-<32hex>-<16hex>-<flags>``. Returns (trace_id, span_id)|None.

    Version and flags must be 2-hex fields; version ``ff`` is forbidden per
    the W3C spec (it would make the header indistinguishable from a random
    opaque string)."""
    if not header:
        return None
    parts = header.strip().split("-")
    if len(parts) != 4:
        return None
    ver, tid, sid, flags = parts
    if len(ver) != 2 or len(flags) != 2 or len(tid) != 32 or len(sid) != 16:
        return None
    try:
        if int(ver, 16) == 0xFF:
            return None
        int(tid, 16)
        int(sid, 16)
        int(flags, 16)
    except ValueError:
        return None
    if tid == "0" * 32 or sid == "0" * 16:  # all-zero IDs are invalid per spec
        return None
    return tid.lower(), sid.lower()


def ensure(traceparent: str | None = None) -> tuple[str, str]:
    """Adopt the inbound traceparent (new child span) or keep/generate the
    current context. Returns (trace_id, span_id)."""
    tid: str | None = None
    if traceparent:
        parsed = parse_traceparent(traceparent)
        if parsed:
            tid = parsed[0]
    if tid is None:
        tid = _trace_id.get() or new_trace_id()
    sid = new_span_id()
    _trace_id.set(tid)
    _span_id.set(sid)
    return tid, sid


def current() -> tuple[str | None, str | None]:
    return _trace_id.get(), _span_id.get()


def traceparent() -> str | None:
    """Current context as an outbound ``traceparent`` header value — used by
    the ApiHandler wrapper to stamp responses, and available to any future
    outbound-propagation caller."""
    tid, sid = current()
    if not tid or not sid:
        return None
    return f"00-{tid}-{sid}-01"


def reset() -> None:
    _trace_id.set(None)
    _span_id.set(None)
