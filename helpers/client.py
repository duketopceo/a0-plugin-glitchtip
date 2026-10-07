"""GlitchTip store-endpoint transport — stdlib urllib, never raises."""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
import uuid

from usr.plugins.glitchtip.helpers import LOG_NAME, USER_AGENT
from usr.plugins.glitchtip.helpers.dsn import Dsn

log = logging.getLogger(LOG_NAME)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse redirects: 30x surfaces as HTTPError (a send failure). Following
    them would re-POST the event — and forward X-Sentry-Auth — to whatever
    the Location header names. A Sentry store endpoint never legitimately
    redirects."""

    def redirect_request(self, *args, **kwargs):
        return None


class Client:
    def __init__(self, dsn: Dsn, *, timeout_s: float = 5.0) -> None:
        self.dsn = dsn
        self.timeout_s = timeout_s
        self._opener = urllib.request.build_opener(_NoRedirect)

    def send_event(self, body: bytes, event_id: str | None = None) -> str | None:
        """POST one serialized event to the store endpoint. Returns event_id
        or None. Serialization is the caller's job (helpers/event.py +
        runtime._capture) so a non-serializable event is distinguishable from
        a transport failure — only the latter arms the send cooldown.

        Never raises — every failure path (DNS, TLS, non-2xx incl. redirects,
        malformed response) logs and returns None.
        """
        try:
            req = urllib.request.Request(
                self.dsn.store_url,
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Sentry-Auth": self.dsn.auth_header,
                    "User-Agent": USER_AGENT,
                },
                method="POST",
            )
            with self._opener.open(req, timeout=self.timeout_s) as resp:
                try:
                    payload = json.loads(resp.read(65536) or b"{}")
                    return payload.get("id") or event_id or uuid.uuid4().hex
                except Exception:
                    # response body is advisory; the POST already landed
                    return event_id or uuid.uuid4().hex
        except urllib.error.HTTPError as e:
            log.warning("GlitchTip store rejected event: HTTP %s", e.code)
            return None
        except Exception as e:
            log.warning("GlitchTip send failed: %s", e)
            return None
