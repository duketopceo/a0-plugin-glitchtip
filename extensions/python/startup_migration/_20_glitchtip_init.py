"""GlitchTip plugin init — runs in initialize.py's startup_migration sweep
(sync, agent=None, before the web app exists). Configures the transport from
plugin config + env, and installs the ApiHandler.handle_request wrapper for
API-level error events when `api_error_events` is on.

The wrapper is additive post-inspection: ApiHandler.handle_request swallows
exceptions into 500 responses, so we observe the *response*, not the stack —
API events are message-level by design (see docs/backends-style note in
AGENTS.md). Agent-loop exceptions carry real stacks via the _85_ extension.
"""

from __future__ import annotations

import logging

from helpers.extension import Extension

log = logging.getLogger("a0.glitchtip")


def _load_plugin_config() -> dict:
    try:
        from helpers.plugins import get_plugin_config  # type: ignore

        cfg = get_plugin_config("glitchtip")
        if isinstance(cfg, dict):
            return cfg
    except Exception:
        pass
    # Fall back to the shipped defaults file.
    try:
        import yaml  # type: ignore
        from usr.plugins.glitchtip.helpers.paths import plugin_root  # type: ignore

        with open(plugin_root() / "default_config.yaml") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def _wrap_handle_request() -> None:
    """Patch ApiHandler.handle_request once: emit an event for >=500
    responses and for exceptions that somehow propagate."""
    try:
        from helpers.api import ApiHandler  # type: ignore
    except Exception:
        return
    original = ApiHandler.handle_request
    if getattr(original, "_glitchtip_wrapped", False):
        return
    if getattr(ApiHandler, "_glitchtip_original", None) is not None:
        return

    async def wrapped(self, request):
        from usr.plugins.glitchtip.helpers import runtime, trace_context

        trace_context.ensure(getattr(request, "headers", {}).get("traceparent"))
        try:
            resp = await original(self, request)
        except Exception as exc:
            runtime.capture_exception(
                exc, tags={"surface": "api", "path": getattr(request, "path", "?")}
            )
            raise
        if getattr(resp, "status_code", 200) >= 500:
            body = ""
            try:
                body = resp.get_data(as_text=True)[:500]
            except Exception:
                pass
            runtime.capture_message(
                f"API 500 {getattr(request, 'method', '?')} "
                f"{getattr(request, 'path', '?')}: {body}",
                level="error",
                tags={"surface": "api", "path": getattr(request, "path", "?")},
            )
        return resp

    wrapped._glitchtip_wrapped = True  # type: ignore[attr-defined]
    ApiHandler._glitchtip_original = original  # type: ignore[attr-defined]
    ApiHandler.handle_request = wrapped


class GlitchtipInit(Extension):
    async def execute(self, **kwargs):
        del kwargs
        from usr.plugins.glitchtip.helpers import runtime

        cfg = _load_plugin_config()
        active = runtime.configure(cfg)
        if active and cfg.get("api_error_events", True):
            _wrap_handle_request()
