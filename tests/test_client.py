"""Transport tests against the shared loopback store fixture — offline, no
external network. The fixture encodes the Sentry store contract the plan
specifies (POST /api/<project>/store/ + X-Sentry-Auth) plus a /redirect path
to pin the no-redirect transport policy."""

import json

from usr.plugins.glitchtip.helpers.client import Client
from usr.plugins.glitchtip.helpers.dsn import parse_dsn


def test_store_post_contract(live_dsn):
    dsn, events = live_dsn
    c = Client(parse_dsn(dsn), timeout_s=2)
    eid = c.send_event(json.dumps({"event_id": "e" * 32, "message": "hi"}).encode(), "e" * 32)
    assert eid == "ok"
    hit = events[-1]
    assert hit["path"] == "/api/9/store/"
    assert "sentry_key=pubkey" in hit["auth"]
    assert "a0-plugin-glitchtip/" in hit["auth"]
    assert hit["body"]["message"] == "hi"


def test_success_returns_event_id_when_response_has_none(live_dsn):
    # /api/7/store/ answers 200 with no id — fall back to the local event id
    dsn, _events = live_dsn
    c = Client(parse_dsn(dsn.replace("/9", "/7")), timeout_s=2)
    assert c.send_event(b'{"message": "x"}', "f" * 32) == "f" * 32


def test_non_2xx_returns_none(live_dsn):
    dsn, _events = live_dsn
    bad = parse_dsn(dsn.replace("/9", "/99"))  # fixture 404s other projects
    c = Client(bad, timeout_s=2)
    assert c.send_event(b'{"message": "x"}') is None


def test_redirect_refused(live_dsn):
    # /api/8/store/ 302s to /api/9/store/ — urllib's default opener would
    # follow it and forward X-Sentry-Auth to the target. Our client must not.
    dsn, _events = live_dsn
    redir = parse_dsn(dsn.replace("/9", "/8"))
    c = Client(redir, timeout_s=2)
    assert c.send_event(b'{"message": "x"}') is None


def test_unreachable_returns_none_never_raises():
    dsn = parse_dsn("http://k@127.0.0.1:1/9")  # port 1 refuses
    c = Client(dsn, timeout_s=1)
    assert c.send_event(b'{"message": "x"}') is None
