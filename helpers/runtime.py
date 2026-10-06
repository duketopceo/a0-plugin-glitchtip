"""Plugin facade — configure, capture, status. Every public function is
guaranteed not to raise: error reporting must never break the host app."""

from __future__ import annotations

import logging
import os
import threading
from typing import Any, Mapping

from usr.plugins.glitchtip.helpers import breadcrumbs as _crumbs
from usr.plugins.glitchtip.helpers import trace_context as _trace
from usr.plugins.glitchtip.helpers.client import Client
from usr.plugins.glitchtip.helpers.dsn import parse_dsn
from usr.plugins.glitchtip.helpers.event import build_event

log = logging.getLogger("a0.glitchtip")

ENV_DSN = "GLITCHTIP_DSN"
ENV_ENVIRONMENT = "GLITCHTIP_ENV"
ENV_RELEASE = "GLITCHTIP_RELEASE"

_lock = threading.RLock()
_client: Client | None = None
_environment = "local"
_release: str | None = None
_configured = False


def _redactor():
    """Best-effort secret redactor: omaseal's mask registry when that plugin
    is installed, else identity. Hard dependency deliberately avoided."""
    try:
        from usr.plugins.omaseal.helpers import resolve as _omaseal  # type: ignore

        return _omaseal.mask_text
    except Exception:
        return lambda s: s


def configure(cfg: Mapping[str, Any] | None = None) -> bool:
    """Build the client from plugin config + env overrides. Idempotent.

    Env wins over config fields: GLITCHTIP_DSN > cfg.dsn, etc.
    Returns True when the plugin became active."""
    global _client, _environment, _release, _configured
    with _lock:
        if _configured:
            return is_active()
        _configured = True
        cfg = cfg or {}
        if not _truthy(cfg.get("enabled", True)):
            log.debug("glitchtip disabled by config")
            return False
        dsn = parse_dsn(os.getenv(ENV_DSN) or cfg.get("dsn") or "")
        if dsn is None:
            log.debug("glitchtip inactive: no DSN (env %s or config dsn)", ENV_DSN)
            return False
        _environment = (
            os.getenv(ENV_ENVIRONMENT) or cfg.get("environment") or "local"
        ).strip() or "local"
        _release = (os.getenv(ENV_RELEASE) or cfg.get("release") or "").strip() or None
        _client = Client(dsn, timeout_s=float(cfg.get("send_timeout_s", 5)))
        _crumbs.configure(int(cfg.get("breadcrumbs_max", 50) or 50))
        log.info("glitchtip configured env=%s project=%s", _environment, dsn.project_id)
        return True


def is_active() -> bool:
    return _client is not None


def _truthy(v: Any) -> bool:
    if isinstance(v, str):
        return v.strip().lower() in {"1", "true", "yes", "on"}
    return bool(v)


def _tags(extra: dict[str, Any] | None) -> dict[str, str]:
    tid, _sid = _trace.current()
    tags = {k: str(v) for k, v in (extra or {}).items() if v is not None}
    if tid:
        tags["trace_id"] = tid
    return tags


def capture_exception(exc: BaseException, tags: dict[str, Any] | None = None) -> str | None:
    try:
        if _client is None:
            return None
        tid, sid = _trace.current()
        event = build_event(
            exc=exc,
            tags=_tags(tags),
            breadcrumbs=_crumbs.snapshot(),
            trace_id=tid,
            span_id=sid,
            environment=_environment,
            release=_release,
            redact=_redactor(),
        )
        return _client.send_event(event)
    except Exception as e:
        log.warning("glitchtip capture_exception failed: %s", e)
        return None


def capture_message(
    message: str, *, level: str = "info", tags: dict[str, Any] | None = None,
    request: dict[str, Any] | None = None,
) -> str | None:
    try:
        if _client is None:
            return None
        tid, sid = _trace.current()
        event = build_event(
            message=message,
            level=level,
            tags=_tags(tags),
            request=request,
            breadcrumbs=_crumbs.snapshot(),
            trace_id=tid,
            span_id=sid,
            environment=_environment,
            release=_release,
            redact=_redactor(),
        )
        return _client.send_event(event)
    except Exception as e:
        log.warning("glitchtip capture_message failed: %s", e)
        return None


def reset() -> None:
    """Test/reload hook: drop client + configured flag (does not undo the
    ApiHandler patch — that is intentionally one-way for the process)."""
    global _client, _configured
    with _lock:
        _client = None
        _configured = False
    _crumbs.clear()
