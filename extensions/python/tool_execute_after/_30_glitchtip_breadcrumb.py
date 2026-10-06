"""Breadcrumb per tool call — name and ok/err status only.

Tool args and output text can carry secrets; the crumb deliberately records
neither (helpers/breadcrumbs.py also strips forbidden keys defensively).
"""

from __future__ import annotations

from helpers.extension import Extension


class GlitchtipToolBreadcrumb(Extension):
    async def execute(self, tool_name: str | None = None, response=None, **kwargs):
        del kwargs
        try:
            from usr.plugins.glitchtip.helpers import breadcrumbs, runtime

            if not runtime.is_active():
                return
            ok = bool(response is not None and not getattr(response, "break_loop", False))
            breadcrumbs.crumb(
                "tool", str(tool_name or "unknown"), {"ok": ok}
            )
        except Exception:
            pass
