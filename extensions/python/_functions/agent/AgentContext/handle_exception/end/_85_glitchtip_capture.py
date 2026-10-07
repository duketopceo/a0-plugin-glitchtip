"""Capture still-fatal process_chain exceptions to GlitchTip — AgentContext
twin of the Agent-level `_85_` capture (see that file for ordering notes).

Here `self.agent` is ALWAYS None: a0's `_get_agent` only recognizes Agent
instances in args. There are also no core `_40_`/`_50_`/`_90_` clearing
extensions at this level — the noise filter in `runtime.is_noise_exception`
is load-bearing, not defensive. Context metadata comes from `args[0]` (the
AgentContext object) via `report_loop_exception`.

The whole body is guarded: an extension raise would mask the exception the
host is handling.
"""

from __future__ import annotations

from helpers.extension import Extension


class GlitchtipCapture(Extension):
    async def execute(self, data: dict | None = None, **kwargs):
        del kwargs
        try:
            from usr.plugins.glitchtip.helpers import runtime

            await runtime.report_loop_exception(
                data, agent=self.agent, surface="agent_context"
            )
        except Exception:
            pass
