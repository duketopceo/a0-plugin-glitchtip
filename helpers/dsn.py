"""Sentry DSN parsing (stdlib-only).

GlitchTip is Sentry-protocol compatible; a DSN looks like
``https://<public_key>@<host>[:port]/<project_id>``. Only the public key and
project id are used for ingestion auth — a DSN is semi-secret, never logged.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass(frozen=True)
class Dsn:
    base: str           # scheme://host[:port] — no trailing slash
    project_id: str
    public_key: str

    @property
    def store_url(self) -> str:
        return f"{self.base}/api/{self.project_id}/store/"

    @property
    def auth_header(self) -> str:
        return (
            "Sentry sentry_version=7, "
            "sentry_client=a0-plugin-glitchtip/0.1, "
            f"sentry_key={self.public_key}"
        )


def parse_dsn(raw: str | None) -> Dsn | None:
    """Parse a Sentry DSN. Returns None on empty/malformed input."""
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        u = urlparse(raw)
        if u.scheme not in ("http", "https") or not u.hostname:
            return None
        public_key = u.username or ""
        project_id = (u.path or "").strip("/").split("/")[-1]
        if not public_key or not project_id:
            return None
        port = f":{u.port}" if u.port else ""
        return Dsn(
            base=f"{u.scheme}://{u.hostname}{port}",
            project_id=project_id,
            public_key=public_key,
        )
    except Exception:
        return None
