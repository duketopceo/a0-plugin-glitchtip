"""GlitchTip store-endpoint transport — stdlib urllib, never raises."""

from __future__ import annotations

import json
import logging
import urllib.request
from typing import Any

from usr.plugins.glitchtip.helpers.dsn import Dsn

log = logging.getLogger("a0.glitchtip")


class Client:
    def __init__(self, dsn: Dsn, *, timeout_s: float = 5.0) -> None:
        self.dsn = dsn
        self.timeout_s = timeout_s

    def send_event(self, event: dict[str, Any]) -> str | None:
        """POST one event to the store endpoint. Returns event_id or None.

        Error reporting must never break the host app: every failure path
        (DNS, TLS, non-2xx, malformed response) logs and returns None.
        """
        event_id = str(event.get("event_id") or "") or None
        try:
            body = json.dumps(event).encode("utf-8")
            req = urllib.request.Request(
                self.dsn.store_url,
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Sentry-Auth": self.dsn.auth_header,
                    "User-Agent": "a0-plugin-glitchtip/0.1",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                if resp.status >= 400:
                    log.warning("GlitchTip store rejected event: HTTP %s", resp.status)
                    return None
                try:
                    payload = json.loads(resp.read() or b"{}")
                    event_id = payload.get("id") or event_id
                except Exception:
                    pass  # response body is advisory; the POST already landed
            return event_id
        except Exception as e:
            log.warning("GlitchTip send failed: %s", e)
            return None
