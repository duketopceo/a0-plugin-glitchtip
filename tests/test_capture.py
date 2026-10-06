"""Facade + extension-layer tests: activation rules, ordering-safe capture,
breadcrumb hygiene, ApiHandler patch behavior."""

import asyncio
import importlib
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from conftest import FakeAgent, FakeContext, FakeRequest, run
from usr.plugins.glitchtip.helpers import breadcrumbs, runtime, trace_context


class _Store(BaseHTTPRequestHandler):
    events = []

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        type(self).events.append(json.loads(self.rfile.read(length) or b"{}"))
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"id": "ok"}')

    def log_message(self, *a):
        pass


@pytest.fixture()
def live_dsn():
    _Store.events = []
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Store)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    dsn = f"http://pubkey@127.0.0.1:{srv.server_port}/9"
    yield dsn, _Store.events
    srv.shutdown()
    srv.server_close()


def _load_init_ext():
    return importlib.import_module(
        "usr.plugins.glitchtip.extensions.python.startup_migration._20_glitchtip_init"
    )


def _load_agent_capture():
    return importlib.import_module(
        "usr.plugins.glitchtip.extensions.python._functions.agent.Agent.handle_exception.end._85_glitchtip_capture"
    )


# --- runtime facade ---------------------------------------------------------


def test_inactive_without_dsn(monkeypatch):
    monkeypatch.delenv("GLITCHTIP_DSN", raising=False)
    assert runtime.configure({}) is False
    assert runtime.is_active() is False
    assert runtime.capture_exception(ValueError("x")) is None  # no socket work


def test_disabled_flag(monkeypatch):
    monkeypatch.delenv("GLITCHTIP_DSN", raising=False)
    assert runtime.configure({"enabled": False, "dsn": "http://k@h/1"}) is False
    assert runtime.is_active() is False


def test_configure_from_config_and_capture(live_dsn, monkeypatch):
    monkeypatch.delenv("GLITCHTIP_DSN", raising=False)
    dsn, events = live_dsn
    assert runtime.configure({"dsn": dsn, "environment": "ci"}) is True
    trace_context.ensure()
    eid = runtime.capture_exception(ValueError("boom"), tags={"surface": "t"})
    assert eid == "ok"
    ev = events[-1]
    assert ev["exception"]["values"][0]["type"] == "ValueError"
    assert ev["environment"] == "ci"
    assert ev["tags"]["surface"] == "t"
    assert len(ev["tags"]["trace_id"]) == 32


def test_env_dsn_overrides_config(live_dsn, monkeypatch):
    dsn, events = live_dsn
    monkeypatch.setenv("GLITCHTIP_DSN", dsn)
    assert runtime.configure({"dsn": "http://wrong@127.0.0.1:1/1"}) is True
    assert runtime.capture_message("hi") == "ok"


def test_configure_idempotent(live_dsn, monkeypatch):
    dsn, events = live_dsn
    monkeypatch.setenv("GLITCHTIP_DSN", dsn)
    assert runtime.configure() is True
    assert runtime.configure() is True  # second call no-ops, still active


# --- _85_ capture extension -------------------------------------------------


def test_capture_extension_reports_unhandled(live_dsn, monkeypatch):
    dsn, events = live_dsn
    monkeypatch.setenv("GLITCHTIP_DSN", dsn)
    runtime.configure()
    mod = _load_agent_capture()
    agent = FakeAgent(context=FakeContext("ctx-9"), agent_name="agent0")
    data = {"exception": RuntimeError("tool exploded"), "args": ("self", "message_loop")}
    run(mod.GlitchtipCapture(agent).execute(data=data))
    ev = events[-1]
    assert ev["exception"]["values"][0]["type"] == "RuntimeError"
    assert ev["tags"]["location"] == "message_loop"
    assert ev["tags"]["agent_name"] == "agent0"
    assert ev["tags"]["context_id"] == "ctx-9"
    assert ev["tags"]["surface"] == "agent_loop"


def test_capture_extension_skips_noise(live_dsn, monkeypatch):
    dsn, events = live_dsn
    monkeypatch.setenv("GLITCHTIP_DSN", dsn)
    runtime.configure()
    mod = _load_agent_capture()
    agent = FakeAgent(context=FakeContext())
    from conftest import HandledException, InterventionException, RepairableException

    for noise in (
        HandledException("h"),
        RepairableException("r"),
        InterventionException("i"),
        asyncio.CancelledError(),
        KeyboardInterrupt(),
        None,
        "not-an-exception",
    ):
        run(mod.GlitchtipCapture(agent).execute(data={"exception": noise}))
    assert events == []


def test_capture_extension_noop_when_no_agent(live_dsn, monkeypatch):
    dsn, events = live_dsn
    monkeypatch.setenv("GLITCHTIP_DSN", dsn)
    runtime.configure()
    mod = _load_agent_capture()
    run(mod.GlitchtipCapture(None).execute(data={"exception": ValueError("x")}))
    assert events == []


# --- breadcrumb extension ---------------------------------------------------


def test_tool_breadcrumb_never_carries_content(live_dsn, monkeypatch):
    dsn, events = live_dsn
    monkeypatch.setenv("GLITCHTIP_DSN", dsn)
    runtime.configure()
    mod = importlib.import_module(
        "usr.plugins.glitchtip.extensions.python.tool_execute_after._30_glitchtip_breadcrumb"
    )

    class Resp:
        break_loop = False
        message = "secret output sk-live-999"

    agent = FakeAgent(context=FakeContext())
    run(mod.GlitchtipToolBreadcrumb(agent).execute(
        tool_name="code_exec", response=Resp()))
    snap = breadcrumbs.snapshot()
    assert snap[-1]["data"] == {"ok": True}
    assert "sk-live-999" not in json.dumps(snap)

    # forbidden keys stripped even if a caller passes them
    breadcrumbs.crumb("tool", "x", {"value": "sekret", "args": "sekret", "ok": 1})
    assert breadcrumbs.snapshot()[-1]["data"] == {"ok": 1}


def test_breadcrumb_noop_when_inactive(monkeypatch):
    monkeypatch.delenv("GLITCHTIP_DSN", raising=False)
    mod = importlib.import_module(
        "usr.plugins.glitchtip.extensions.python.tool_execute_after._30_glitchtip_breadcrumb"
    )
    run(mod.GlitchtipToolBreadcrumb(FakeAgent()).execute(tool_name="t", response=None))
    assert breadcrumbs.snapshot() == []


# --- startup init + ApiHandler patch ----------------------------------------


def test_init_configures_and_patches(live_dsn, monkeypatch):
    dsn, events = live_dsn
    monkeypatch.setenv("GLITCHTIP_DSN", dsn)
    mod = _load_init_ext()
    run(mod.GlitchtipInit().execute())
    assert runtime.is_active()
    from helpers.api import ApiHandler  # stubbed module

    assert getattr(ApiHandler.handle_request, "_glitchtip_wrapped", False)


def test_api_500_emits_message_event(live_dsn, monkeypatch):
    dsn, events = live_dsn
    monkeypatch.setenv("GLITCHTIP_DSN", dsn)
    mod = _load_init_ext()
    run(mod.GlitchtipInit().execute())

    from helpers.api import ApiHandler

    class BrokenHandler(ApiHandler):
        async def process(self, input, request):
            raise RuntimeError("db gone")

    resp = run(BrokenHandler().handle_request(FakeRequest(path="/api/x")))
    assert resp.status_code == 500
    ev = events[-1]
    assert "message" in ev and "db gone" in ev["message"]
    assert ev["tags"]["surface"] == "api"
    assert ev["tags"]["path"] == "/api/x"
    assert len(ev["tags"]["trace_id"]) == 32


def test_api_500_event_adopts_traceparent(live_dsn, monkeypatch):
    dsn, events = live_dsn
    monkeypatch.setenv("GLITCHTIP_DSN", dsn)
    mod = _load_init_ext()
    run(mod.GlitchtipInit().execute())
    from helpers.api import ApiHandler

    class BrokenHandler(ApiHandler):
        async def process(self, input, request):
            raise RuntimeError("x")

    req = FakeRequest(headers={"traceparent": "00-" + "ab" * 16 + "-" + "cd" * 8 + "-01"})
    run(BrokenHandler().handle_request(req))
    assert events[-1]["tags"]["trace_id"] == "ab" * 16


def test_api_ok_response_no_event(live_dsn, monkeypatch):
    dsn, events = live_dsn
    monkeypatch.setenv("GLITCHTIP_DSN", dsn)
    mod = _load_init_ext()
    run(mod.GlitchtipInit().execute())
    from helpers.api import ApiHandler

    class OkHandler(ApiHandler):
        async def process(self, input, request):
            return {"ok": True}

    resp = run(OkHandler().handle_request(FakeRequest()))
    assert resp.status_code == 200
    assert events == []


def test_patch_not_applied_when_inactive(monkeypatch):
    monkeypatch.delenv("GLITCHTIP_DSN", raising=False)
    mod = _load_init_ext()
    run(mod.GlitchtipInit().execute())
    from helpers.api import ApiHandler

    assert not getattr(ApiHandler.handle_request, "_glitchtip_wrapped", False)
