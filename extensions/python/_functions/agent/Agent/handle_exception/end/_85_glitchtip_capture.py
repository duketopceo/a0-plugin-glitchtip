"""Capture still-fatal agent-loop exceptions to GlitchTip.

Ordering: `_40_` clears InterventionException, `_50_` clears
RepairableException; `_90_` wraps the remainder as HandledException. At `_85_`
`data["exception"]` is still the RAW exception with a real traceback — the
exact set of unhandled errors. Reported once here; `_90_` then logs/wraps as
usual. Skips HandledException / CancelledError defensively.
"""

from __future__ import annotations

import asyncio

from helpers.extension import Extension


def _is_noise(exc: BaseException) -> bool:
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


class GlitchtipCapture(Extension):
    async def execute(self, data: dict = {}, **kwargs):
        del kwargs
        if not self.agent:
            return
        exc = data.get("exception")
        if not isinstance(exc, BaseException) or _is_noise(exc):
            return
        from usr.plugins.glitchtip.helpers import runtime

        location = None
        args = data.get("args")
        if isinstance(args, tuple) and len(args) > 1:
            location = args[1]  # handle_exception(location, exception)
        tags = {
            "surface": "agent_loop",
            "location": location,
            "agent_name": getattr(self.agent, "agent_name", None),
            "context_id": getattr(getattr(self.agent, "context", None), "id", None),
        }
        runtime.capture_exception(exc, tags=tags)
