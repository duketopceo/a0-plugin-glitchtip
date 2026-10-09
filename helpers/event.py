"""Sentry store-event construction from Python exceptions (stdlib-only)."""

from __future__ import annotations

import os
import traceback
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from usr.plugins.glitchtip.helpers import LOG_NAME

# Header names that must never leave the process in an event payload.
_SENSITIVE_HEADERS = frozenset({
    "authorization", "proxy-authorization", "x-forwarded-authorization",
    "cookie", "set-cookie", "x-api-key", "api-key", "apikey",
    "x-auth-token", "x-csrf-token", "x-xsrf-token", "x-session-id",
    "www-authenticate",
})
_MAX_FRAMES = 100  # cap traceback depth — a RecursionError yields ~1000 frames
_MAX_LINE = 300    # context_line can be megabytes on minified/generated files

Redactor = Callable[[str], str]


def _frames(exc: BaseException) -> list[dict[str, Any]]:
    # extract_tb yields oldest→newest (caller → raise site), which is exactly
    # the Sentry stacktrace contract: "ordered from caller to callee; the
    # last frame is the one creating the exception." No reversal.
    return [
        {
            "filename": fr.filename,
            "function": fr.name,
            "lineno": fr.lineno,
            "context_line": (fr.line or "")[:_MAX_LINE] or None,
            "in_app": f"{os.sep}usr{os.sep}plugins{os.sep}" in fr.filename,
        }
        for fr in traceback.extract_tb(exc.__traceback__)[-_MAX_FRAMES:]
    ]


def _redact_headers(event: dict[str, Any]) -> None:
    req = event.get("request") or {}
    headers = req.get("headers") or {}
    for key in list(headers.keys()):
        if str(key).lower() in _SENSITIVE_HEADERS:
            headers[key] = "[redacted]"


def _scrub(obj: Any, redact: Redactor) -> Any:
    """Fail closed per field: a throwing redactor yields "[redacted]" for
    that string, never the unredacted event."""
    if isinstance(obj, str):
        try:
            return redact(obj)
        except Exception:
            return "[redacted]"
    if isinstance(obj, dict):
        # Values only — keys are structural field names; the user-controlled
        # key namespaces (request headers, crumb data) are already filtered
        # by _SENSITIVE_HEADERS / _FORBIDDEN upstream.
        return {k: _scrub(v, redact) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [_scrub(v, redact) for v in obj]
    return obj


def build_event(
    *,
    exc: BaseException | None = None,
    message: str | None = None,
    level: str = "error",
    tags: dict[str, str] | None = None,
    request: dict[str, Any] | None = None,
    breadcrumbs: list[dict[str, Any]] | None = None,
    trace_id: str | None = None,
    span_id: str | None = None,
    environment: str = "local",
    release: str | None = None,
    redact: Redactor | None = None,
) -> dict[str, Any]:
    """Build a Sentry store-endpoint event. ``exc`` and ``message`` are
    mutually exclusive — exc for real exceptions, message for message-level.
    Breadcrumb count is owned by the ring buffer's configured maxlen — the
    list passed in is already the right size."""
    event: dict[str, Any] = {
        "event_id": uuid.uuid4().hex,
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "platform": "python",
        "level": level,
        "logger": LOG_NAME,
        "environment": environment,
        "tags": {k: str(v)[:200] for k, v in (tags or {}).items() if v is not None},
    }
    if release:
        event["release"] = release
    if exc is not None:
        event["exception"] = {
            "values": [
                {
                    "type": type(exc).__name__,
                    "value": str(exc)[:2000],
                    "stacktrace": {"frames": _frames(exc)},
                }
            ]
        }
    elif message is not None:
        event["message"] = str(message)[:2000]
    if request:
        # shallow-copy with fresh headers so _redact_headers never mutates
        # the caller's dict
        req = dict(request)
        req["headers"] = dict(request.get("headers") or {})
        event["request"] = req
    if breadcrumbs:
        event["breadcrumbs"] = {"values": list(breadcrumbs)}
    if trace_id:
        ctx: dict[str, Any] = {"type": "trace", "trace_id": trace_id}
        if span_id:
            ctx["span_id"] = span_id
        event["contexts"] = {"trace": ctx}
        event["tags"]["trace_id"] = trace_id

    _redact_headers(event)
    if redact is not None:
        event = _scrub(event, redact)
    return event
