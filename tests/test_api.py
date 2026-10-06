"""api/glitchtip_test handler."""

from conftest import FakeRequest, run
from usr.plugins.glitchtip.api.glitchtip_test import GlitchtipTest
from usr.plugins.glitchtip.helpers import runtime


def test_test_event_inactive(monkeypatch):
    monkeypatch.delenv("GLITCHTIP_DSN", raising=False)
    out = run(GlitchtipTest().process({}, FakeRequest()))
    assert out["ok"] is False
    assert "not configured" in out["error"]


def test_test_event_active(monkeypatch):
    # Point at a loopback server is covered in test_client; here just stub send.
    monkeypatch.setenv("GLITCHTIP_DSN", "http://k@127.0.0.1:1/9")
    runtime.configure()

    def fake_send(event):
        return "evt-fixed"

    runtime._client.send_event = fake_send  # type: ignore[union-attr]
    out = run(GlitchtipTest().process({}, FakeRequest()))
    assert out == {"ok": True, "event_id": "evt-fixed"}


def test_send_failure_reports(monkeypatch):
    monkeypatch.setenv("GLITCHTIP_DSN", "http://k@127.0.0.1:1/9")  # refused
    runtime.configure()
    out = run(GlitchtipTest().process({}, FakeRequest()))
    assert out["ok"] is False
    assert "send failed" in out["error"]
