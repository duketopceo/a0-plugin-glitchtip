"""GlitchTip plugin init — runs in initialize.py's startup_migration sweep.

IMPORTANT: `call_extensions_sync` raises on a returned awaitable, so
`execute` here is SYNC — not async. It also has NO per-extension guard, so
every line runs under try/except: a raise here aborts the whole sweep and
breaks a0 boot. Runs before the web app exists.

Configures the transport from plugin config + env, then installs the
ApiHandler.handle_request wrapper — always when active (it owns inbound
`traceparent` adoption + outbound stamping); `api_error_events` gates only
the >=500 emission. The wrapper is additive post-inspection: handle_request
swallows exceptions into 500 responses, so we observe the *response*, not
the stack — API events are message-level by design (see AGENTS.md
"conventions"). Agent-loop exceptions carry real stacks via the `_85_`
capture extensions.
"""

from __future__ import annotations

import inspect
import logging
import threading
from collections.abc import Mapping

from helpers.extension import Extension

_WRAP_LOCK = threading.Lock()  # check-then-act on _wrap_handle_request

# hoisted at module scope is deliberate for helpers.extension only — the
# usr.plugins.glitchtip imports stay inside functions so a broken/partial
# plugin install can't abort the extension-file sweep (import_module has no
# guard upstream).


def _request_meta(request) -> dict:
    return {
        "path": str(getattr(request, "path", "?"))[:500],
        "method": str(getattr(request, "method", "?"))[:20],
    }


async def _emit_api_error(request, resp) -> None:
    """Message-level event for a >=500 API response. `get_data` may be a
    coroutine on async response flavors — skip the body rather than await.
    Streamed/passthrough bodies are skipped (get_data would buffer them
    fully into memory)."""
    from usr.plugins.glitchtip.helpers import runtime

    body = ""
    try:
        streamed = bool(
            getattr(resp, "is_streamed", False)
            or getattr(resp, "direct_passthrough", False)
        )
        if not streamed:
            raw = resp.get_data(as_text=True)
            if inspect.isawaitable(raw):
                raw.close()  # unawaited coroutine → avoid RuntimeWarning spam
            elif isinstance(raw, str):
                # first line only — a0's 500 body is format_error(e) = full
                # traceback text; the headline carries the diagnostic value
                body = raw.split("\n", 1)[0][:200]
    except Exception:
        pass
    meta = _request_meta(request)
    await runtime.acapture_message(
        f"API {getattr(resp, 'status_code', '?')} {meta['method']} {meta['path']}: {body}",
        level="error",
        tags={"surface": "api", **meta},
    )


def _wrap_handle_request(*, emit_api_errors: bool) -> None:
    """Patch ApiHandler.handle_request once (process-global, one-way).
    Stamps the response `traceparent`, emits an event on >=500 (when
    enabled), and reports exceptions that propagate. Every observation block
    is individually guarded: the wrapper must never change what the handler
    returns or raises."""
    try:
        from helpers.api import ApiHandler  # type: ignore
    except Exception:
        return
    with _WRAP_LOCK:
        original = getattr(ApiHandler, "_glitchtip_original", None)
        if original is not None:
            return  # already installed
        original = getattr(ApiHandler, "handle_request", None)
        if original is None:
            return

        async def wrapped(self, request):
            from usr.plugins.glitchtip.helpers import runtime, trace_context

            if not runtime.is_active():
                # plugin disabled mid-process — patch is one-way, so make
                # the inactive path a pure passthrough (no headers, no
                # context writes, no events)
                return await original(self, request)
            try:
                headers = getattr(request, "headers", None)
                tp_in = headers.get("traceparent") if isinstance(headers, Mapping) else None
                trace_context.ensure(tp_in)
            except Exception:
                pass
            try:
                resp = await original(self, request)
            except Exception as exc:
                # fire-and-forget: capture must never delay or mask the
                # original exception's propagation (spawn is never-raise)
                meta = _request_meta(request)
                runtime.spawn(
                    runtime.acapture_exception(exc, tags={"surface": "api", **meta})
                )
                raise
            try:
                tp = trace_context.traceparent()
                if tp:
                    resp.headers["traceparent"] = tp
            except Exception:
                pass
            try:
                code = int(getattr(resp, "status_code", 200) or 200)
            except Exception:
                code = 200
            if emit_api_errors and code >= 500:
                runtime.spawn(_emit_api_error(request, resp))
            return resp

        ApiHandler._glitchtip_original = original  # type: ignore[attr-defined]
        ApiHandler.handle_request = wrapped


class GlitchtipInit(Extension):
    def execute(self, **kwargs):
        del kwargs
        try:
            from usr.plugins.glitchtip.helpers import runtime
            from usr.plugins.glitchtip.helpers.config import get_config, truthy

            cfg = get_config()
            active = runtime.configure(cfg)
            if active:
                _wrap_handle_request(
                    emit_api_errors=truthy(cfg.get("api_error_events", True))
                )
        except Exception:
            # call_extensions_sync has no per-extension guard — a raise here
            # aborts the whole startup sweep and breaks a0 boot
            try:
                logging.getLogger("a0.glitchtip").exception(
                    "glitchtip init failed"
                )
            except Exception:
                pass
