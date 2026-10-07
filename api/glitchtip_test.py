"""Ops endpoint: emit a GlitchTip test event.

POST /api/plugins/glitchtip/glitchtip_test — inherits auth + CSRF defaults
from helpers.api.ApiHandler. Returns the event id so the operator can find it
in the GlitchTip project feed.
"""

from __future__ import annotations

from helpers.api import ApiHandler


class GlitchtipTest(ApiHandler):
    @classmethod
    def get_methods(cls):
        return ["POST"]

    async def process(self, input, request):
        from usr.plugins.glitchtip.helpers import runtime

        if not runtime.is_active():
            return {
                "ok": False,
                "error": "glitchtip inactive (disabled or no valid DSN)",
            }
        event_id = await runtime.acapture_message(
            "GlitchTip test event from a0-plugin-glitchtip",
            level="info",
            tags={"surface": "api_test"},
        )
        if event_id is None:
            return {"ok": False, "error": "send failed — see server logs"}
        return {"ok": True, "event_id": event_id}
