"""Plugin facade — configure, capture, status. Every public function is
guaranteed not to raise: error reporting must never break the host app.

`capture_*` are synchronous; the `acapture_*` variants offload the blocking
POST via ``asyncio.to_thread`` for async callers (extensions, ApiHandler
wrapper). ContextVars propagate through to_thread, so trace context survives
the handoff.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import threading
import time
from typing import Any, Mapping

from usr.plugins.glitchtip.helpers import (
    ENV_DSN,
    ENV_ENVIRONMENT,
    ENV_RELEASE,
    LOG_NAME,
)
from usr.plugins.glitchtip.helpers import breadcrumbs as _crumbs
from usr.plugins.glitchtip.helpers import trace_context as _trace
from usr.plugins.glitchtip.helpers.client import Client
from usr.plugins.glitchtip.helpers.config import num, truthy
from usr.plugins.glitchtip.helpers.dsn import parse_dsn
from usr.plugins.glitchtip.helpers.event import build_event

log = logging.getLogger(LOG_NAME)

# A failed send disables sending briefly — an unreachable GlitchTip plus an
# exception storm must not compound into repeated connect+timeout work.
_SEND_COOLDOWN_S = 60.0

# Cap concurrent in-flight POSTs — acapture_* schedules onto the default
# executor whose work queue is unbounded; sustained errors would pile up
# worker threads (memory, then a thundering herd when GlitchTip recovers).
_MAX_IN_FLIGHT = 20

_lock = threading.RLock()
_client: Client | None = None
_environment = "local"
_release: str | None = None
_configured = False
_send_disabled_until = 0.0
_in_flight = 0
_tasks: set[asyncio.Task] = set()
_redact = lambda s: s  # noqa: E731 — replaced at configure()

# Always-on secret scrubbing — exception text and source context lines are
# exactly where tokens/connection strings live, and they ship verbatim when
# omaseal isn't installed. OmaSeal's mask_text layers ON TOP at configure()
# time; these patterns are the floor, not the ceiling.
_BASELINE_PATTERNS = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"Bearer\s+[A-Za-z0-9._~+/=-]{8,}",
        r"sk-[A-Za-z0-9_-]{8,}",
        r"gh[pousr]_[A-Za-z0-9]{20,}",
        r"AKIA[0-9A-Z]{16}",
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
        r"(?:password|passwd|api[_-]?key|secret|token)['\"\s]*[=:]\s*['\"]?[^\s'\",;}]{6,}",
    )
)


def _baseline_redact(s: str) -> str:
    for p in _BASELINE_PATTERNS:
        s = p.sub("[redacted]", s)
    return s


def _resolve_redactor():
    """Baseline pattern scrubber always runs; omaseal's mask registry layers
    on top when that plugin is installed (soft dep — see AGENTS.md)."""
    try:
        from usr.plugins.omaseal.helpers import resolve as _omaseal  # type: ignore

        mask = _omaseal.mask_text
        return lambda s: mask(_baseline_redact(s))
    except Exception:
        return _baseline_redact


def configure(cfg: Mapping[str, Any] | None = None) -> bool:
    """Build the client from plugin config + env overrides. Idempotent.

    Env wins over config fields: GLITCHTIP_DSN > cfg.dsn, etc. The configured
    latch is only set on success — a missing/invalid DSN leaves the plugin
    inactive but a later configure() can still activate it. Never raises:
    a raise here would propagate out of the startup_migration sweep and
    abort a0 boot."""
    global _client, _environment, _release, _configured, _redact
    try:
        with _lock:
            if _configured:
                return is_active()
            cfg = cfg if isinstance(cfg, Mapping) else {}
            if not truthy(cfg.get("enabled", True)):
                log.debug("glitchtip disabled by config")
                return False
            dsn = parse_dsn(os.getenv(ENV_DSN) or cfg.get("dsn"))
            if dsn is None:
                log.debug("glitchtip inactive: no DSN (env %s or config dsn)", ENV_DSN)
                return False
            _environment = (
                str(os.getenv(ENV_ENVIRONMENT) or cfg.get("environment") or "local")
                .strip()
                or "local"
            )
            _release = (
                str(os.getenv(ENV_RELEASE) or cfg.get("release") or "").strip()
                or None
            )
            if dsn.scheme == "http" and not _is_loopback(dsn.base):
                log.warning(
                    "glitchtip: http:// DSN — event payloads (which may carry "
                    "secrets) traverse the network in cleartext; use https"
                )
            timeout = min(max(num(cfg.get("send_timeout_s"), 5), 0.5), 30.0)
            _client = Client(dsn, timeout_s=timeout)
            _crumbs.configure(min(max(int(num(cfg.get("breadcrumbs_max"), 50)), 1), 500))
            _redact = _resolve_redactor()
            _configured = True
            log.info(
                "glitchtip configured env=%s project=%s", _environment, dsn.project_id
            )
            return True
    except Exception as e:
        log.warning("glitchtip configure failed: %s", e)
        return False


def _is_loopback(base: str) -> bool:
    return any(h in base for h in ("localhost", "127.", "::1", "0.0.0.0"))


def is_active() -> bool:
    return _client is not None


def _clean_tags(tags: dict[str, Any] | None) -> dict[str, str]:
    if not isinstance(tags, dict):
        return {}
    return {
        str(k): str(v)[:200]
        for k, v in tags.items()
        if isinstance(k, str) and v is not None
    }


def _capture(**event_kwargs) -> str | None:
    """Shared never-raise envelope for both public capture paths."""
    global _send_disabled_until, _in_flight
    try:
        if _client is None or time.monotonic() < _send_disabled_until:
            return None
        tid, sid = _trace.current()
        if not tid:
            tid, sid = _trace.ensure()  # mint a trace per context — every
            # event carries trace_id (agent loops live on DeferredTask
            # threads where no inbound traceparent ever arrives)
        event_kwargs["tags"] = _clean_tags(event_kwargs.get("tags"))
        event = build_event(
            breadcrumbs=_crumbs.snapshot(),
            trace_id=tid,
            span_id=sid,
            environment=_environment,
            release=_release,
            redact=_redact,
            **event_kwargs,
        )
        try:
            body = json.dumps(event).encode("utf-8")
        except Exception:
            # Poison event (non-serializable value) — drop it. NOT a
            # transport failure, so it must not arm the send cooldown.
            log.warning("glitchtip: event not serializable — dropped")
            return None
        with _lock:
            if _in_flight >= _MAX_IN_FLIGHT:
                return None
            _in_flight += 1
        try:
            sent = _client.send_event(body, event.get("event_id"))
        finally:
            with _lock:
                _in_flight -= 1
        if sent is None:
            _send_disabled_until = time.monotonic() + _SEND_COOLDOWN_S
        return sent
    except Exception as e:
        log.warning("glitchtip capture failed: %s", e)
        return None


def capture_exception(exc: BaseException, tags: dict[str, Any] | None = None) -> str | None:
    return _capture(exc=exc, tags=tags)


def capture_message(
    message: str, *, level: str = "info", tags: dict[str, Any] | None = None,
    request: dict[str, Any] | None = None,
) -> str | None:
    return _capture(
        message=message, level=level, tags=tags, request=request
    )


async def acapture_exception(exc: BaseException, tags: dict[str, Any] | None = None) -> str | None:
    """Async variant: the blocking POST runs on a worker thread so the event
    loop is never stalled by a slow/unreachable GlitchTip."""
    try:
        return await asyncio.to_thread(capture_exception, exc, tags)
    except Exception:
        return None  # to_thread can raise during loop/executor shutdown


async def acapture_message(
    message: str, *, level: str = "info", tags: dict[str, Any] | None = None,
    request: dict[str, Any] | None = None,
) -> str | None:
    try:
        return await asyncio.to_thread(
            capture_message, message, level=level, tags=tags, request=request
        )
    except Exception:
        return None


def spawn(coro) -> None:
    """Fire-and-forget a capture coroutine — error reporting must not delay
    the response/raise path it's observing. Task refs are held until done so
    the GC can't collect an in-flight task."""
    try:
        task = asyncio.get_running_loop().create_task(coro)
        _tasks.add(task)
        task.add_done_callback(_tasks.discard)
    except Exception:
        pass


def is_noise_exception(exc: BaseException) -> bool:
    """Exceptions the agent loop already handles — never worth an event.

    At Agent level, core `_40_`/`_50_`/`_90_` extensions clear Intervention/
    Repairable and wrap the rest. At AgentContext level there are NO core
    clearing extensions (Khan tree) — this filter is load-bearing there, not
    merely defensive."""
    try:
        from helpers.errors import (  # type: ignore
            HandledException,
            InterventionException,
            RepairableException,
        )

        if isinstance(exc, (HandledException, InterventionException, RepairableException)):
            return True
    except Exception:
        pass
    return isinstance(exc, (asyncio.CancelledError, KeyboardInterrupt))


def _exception_location(data: dict | None) -> Any:
    """handle_exception's args are (self, location, exception) — find the
    exception element defensively and take its predecessor as the location."""
    args = (data or {}).get("args")
    if not isinstance(args, tuple):
        return None
    for i, a in enumerate(args):
        if isinstance(a, BaseException) and i > 0:
            return args[i - 1]
    return None


async def report_loop_exception(
    data: dict | None, *, agent: Any = None, surface: str
) -> str | None:
    """Shared core for the two `_85_` handle_exception end-extensions.
    Never raises — a raise would propagate out of call_extensions_async and
    mask the exception the host is trying to handle."""
    try:
        exc = (data or {}).get("exception")
        if not isinstance(exc, BaseException) or is_noise_exception(exc):
            return None
        if getattr(exc, "_glitchtip_reported", False):
            return None  # Agent + AgentContext hooks can both see one exc
        try:
            exc._glitchtip_reported = True  # type: ignore[attr-defined]
        except Exception:
            pass  # slotted exception: skip dedup, still capture
        # agent is None at AgentContext level (a0's _get_agent only matches
        # Agent instances) — the AgentContext object sits at args[0] and
        # carries .id, so pull context metadata from there.
        ctx = getattr(agent, "context", None)
        if ctx is None:
            args = (data or {}).get("args")
            if isinstance(args, tuple) and args:
                ctx = args[0]
        tags = {
            "surface": surface,
            "location": _exception_location(data),
            "agent_name": getattr(agent, "agent_name", None),
            "context_id": getattr(ctx, "id", None),
        }
        return await acapture_exception(exc, tags=tags)
    except Exception:
        return None


def _reset() -> None:
    """Test/reload hook: drop client, config latch, cooldown, cached
    redactor, breadcrumbs, and trace context. Does not undo the ApiHandler
    patch — that is intentionally one-way for the process."""
    global _client, _configured, _environment, _release
    global _send_disabled_until, _redact, _in_flight
    with _lock:
        _client = None
        _configured = False
        _environment = "local"
        _release = None
        _send_disabled_until = 0.0
        _in_flight = 0
        _redact = lambda s: s  # noqa: E731
    _crumbs.reset()
    _trace.reset()
