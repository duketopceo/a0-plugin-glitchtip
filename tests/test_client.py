"""Transport tests against a loopback http.server — offline, no external
network. The fixture encodes the Sentry store contract the plan specifies."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from usr.plugins.glitchtip.helpers.client import Client
from usr.plugins.glitchtip.helpers.dsn import parse_dsn


class _StoreHandler(BaseHTTPRequestHandler):
    received = []

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length)
        type(self).received.append(
            {"path": self.path, "auth": self.headers.get("X-Sentry-Auth"),
             "body": json.loads(body or b"{}")}
        )
        status = 200 if "/api/9/store/" in self.path else 404
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"id": "evt-abc-123"}')

    def log_message(self, *a):
        pass


@pytest.fixture()
def server():
    _StoreHandler.received = []
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _StoreHandler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()
    srv.server_close()


def _client_for(port) -> Client:
    dsn = parse_dsn(f"http://pubkey@127.0.0.1:{port}/9")
    assert dsn is not None
    return Client(dsn, timeout_s=2)


def test_store_post_contract(server):
    c = _client_for(server.server_port)
    eid = c.send_event({"event_id": "e" * 32, "message": "hi"})
    assert eid == "evt-abc-123"
    hit = _StoreHandler.received[-1]
    assert hit["path"] == "/api/9/store/"
    assert "sentry_key=pubkey" in hit["auth"]
    assert hit["body"]["message"] == "hi"


def test_non_2xx_returns_none(server):
    dsn = parse_dsn(f"http://pubkey@127.0.0.1:{server.server_port}/99")  # →404
    c = Client(dsn, timeout_s=2)
    assert c.send_event({"message": "x"}) is None


def test_unreachable_returns_none_never_raises():
    dsn = parse_dsn("http://k@127.0.0.1:1/9")  # port 1 refuses
    c = Client(dsn, timeout_s=1)
    assert c.send_event({"message": "x"}) is None
