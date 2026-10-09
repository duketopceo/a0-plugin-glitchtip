"""Sentry DSN parsing (stdlib-only).

GlitchTip is Sentry-protocol compatible; a DSN looks like
``https://<public_key>@<host>[:port][/path-prefix]/<project_id>``. Only the
public key and project id are used for ingestion auth — a DSN is semi-secret,
never logged. The Dsn repr deliberately omits the public key.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

from usr.plugins.glitchtip.helpers import SENTRY_CLIENT

_PROJECT_ID_RE = re.compile(r"[A-Za-z0-9_-]+")


@dataclass(frozen=True)
class Dsn:
    base: str           # scheme://host[:port][/path-prefix] — no trailing slash
    project_id: str
    public_key: str = field(repr=False)  # semi-secret — keep out of reprs/logs
    scheme: str = "https"

    @property
    def store_url(self) -> str:
        return f"{self.base}/api/{self.project_id}/store/"

    @property
    def auth_header(self) -> str:
        return (
            "Sentry sentry_version=7, "
            f"sentry_client={SENTRY_CLIENT}, "
            f"sentry_key={self.public_key}"
        )


def parse_dsn(raw: str | None) -> Dsn | None:
    """Parse a Sentry DSN. Returns None on empty/malformed input.

    The path before the project id is the instance's URL prefix
    (self-hosted GlitchTip is often reverse-proxied under a sub-path) — it is
    part of ``base``, never dropped.
    """
    try:
        raw = str(raw or "").strip()
        if not raw:
            return None
        u = urlparse(raw)
        if u.scheme not in ("http", "https") or not u.hostname or not u.username:
            return None
        parts = (u.path or "").strip("/").split("/")
        project_id = parts[-1] if parts else ""
        if not _PROJECT_ID_RE.fullmatch(project_id):
            return None
        prefix_parts = parts[:-1]
        if any(p in ("", ".", "..") for p in prefix_parts):
            return None  # degenerate/traversal segments must not reach the wire
        host = f"[{u.hostname}]" if ":" in u.hostname else u.hostname  # IPv6
        port = f":{u.port}" if u.port else ""
        prefix = "/".join(prefix_parts)
        return Dsn(
            base=f"{u.scheme}://{host}{port}" + (f"/{prefix}" if prefix else ""),
            project_id=project_id,
            public_key=u.username,
            scheme=u.scheme,
        )
    except Exception:
        return None
