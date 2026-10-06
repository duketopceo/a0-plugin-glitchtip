"""Capture still-fatal process_chain exceptions to GlitchTip — AgentContext
twin of the Agent-level `_85_` capture (see that file for ordering notes)."""

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
        exc = data.get("exception")
        if not isinstance(exc, BaseException) or _is_noise(exc):
            return
        from usr.plugins.glitchtip.helpers import runtime

        location = None
        args = data.get("args")
        if isinstance(args, tuple) and len(args) > 1:
            location = args[1]
        runtime.capture_exception(exc, tags={"surface": "agent_context", "location": location})
