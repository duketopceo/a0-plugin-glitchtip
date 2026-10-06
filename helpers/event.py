"""Sentry store-event construction from Python exceptions (stdlib-only)."""

from __future__ import annotations

import linecache
import os
import time
import traceback
import uuid
from typing import Any, Callable

_SENSITIVE_HEADERS = frozenset({"authorization", "cookie", "x-api-key"})

Redactor = Callable[[str], str]


def _frames(exc: BaseException) -> list[dict[str, Any]]:
    tb = exc.__traceback__
    frames: list[dict[str, Any]] = []
    for fr in traceback.extract_tb(tb):
        lineno = fr.lineno
        line = fr.line
        if line is None:
            line = (linecache.getline(fr.filename, lineno) or "").strip() or None
        frames.append(
            {
                "filename": fr.filename,
                "function": fr.name,
                "lineno": lineno,
                "context_line": line,
                "in_app": f"{os.sep}usr{os.sep}plugins{os.sep}" in fr.filename,
            }
        )
    frames.reverse()  # Sentry wants oldest call first
    return frames


def _redact_headers(event: dict[str, Any]) -> None:
    req = event.get("request") or {}
    headers = req.get("headers") or {}
    for key in list(headers.keys()):
        if key.lower() in _SENSITIVE_HEADERS:
            headers[key] = "[redacted]"


def _scrub(obj: Any, redact: Redactor) -> Any:
    if isinstance(obj, str):
        return redact(obj)
    if isinstance(obj, dict):
        return {k: _scrub(v, redact) for k, v in obj.items()}
    if isinstance(obj, list):
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
    mutually exclusive — exc for real exceptions, message for message-level."""
    event: dict[str, Any] = {
        "event_id": uuid.uuid4().hex,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
        "platform": "python",
        "level": level,
        "logger": "a0.glitchtip",
        "environment": environment,
        "tags": {k: str(v)[:200] for k, v in (tags or {}).items()},
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
        event["request"] = request
    if breadcrumbs:
        event["breadcrumbs"] = {"values": breadcrumbs[-50:]}
    if trace_id:
        ctx: dict[str, Any] = {"trace_id": trace_id}
        if span_id:
            ctx["span_id"] = span_id
        event["contexts"] = {"trace": ctx}
        event["tags"]["trace_id"] = trace_id

    _redact_headers(event)
    if redact is not None:
        try:
            event = _scrub(event, redact)
        except Exception:
            pass  # a broken redactor must never break error reporting
    return event
