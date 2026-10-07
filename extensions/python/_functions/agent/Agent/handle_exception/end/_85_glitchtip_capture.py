"""Capture still-fatal agent-loop exceptions to GlitchTip.

Ordering: `_40_` clears InterventionException, `_50_` clears
RepairableException; `_90_` wraps the remainder as HandledException. At `_85_`
`data["exception"]` is still the RAW exception with a real traceback — the
exact set of unhandled errors. `_90_` then logs/wraps as usual.

The whole body is guarded: call_extensions_async has no per-extension try,
so a raise here would mask the exception the host is handling.
"""

from __future__ import annotations

from helpers.extension import Extension


class GlitchtipCapture(Extension):
    async def execute(self, data: dict | None = None, **kwargs):
        del kwargs
        try:
            from usr.plugins.glitchtip.helpers import runtime

            await runtime.report_loop_exception(
                data, agent=self.agent, surface="agent_loop"
            )
        except Exception:
            pass
