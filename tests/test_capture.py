"""Facade + extension-layer tests: activation rules, ordering-safe capture,
breadcrumb hygiene, ApiHandler patch behavior, send cooldown."""

import asyncio
import importlib
import json
import sys

import pytest

from conftest import FakeAgent, FakeContext, FakeRequest, run
from usr.plugins.glitchtip.helpers import breadcrumbs, runtime, trace_context


def _load_init_ext():
    return importlib.import_module(
        "usr.plugins.glitchtip.extensions.python.startup_migration._20_glitchtip_init"
    )


def _load_agent_capture():
    return importlib.import_module(
        "usr.plugins.glitchtip.extensions.python._functions.agent.Agent.handle_exception.end._85_glitchtip_capture"
    )


def _wrap_marker():
    from helpers.api import ApiHandler

    return getattr(ApiHandler, "_glitchtip_original", None)


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


def test_configure_disable_after_active_tears_down(live_dsn, monkeypatch):
    # enabled:false on a later configure must win over the configured latch —
    # otherwise "disable" can never take effect without a process restart.
    dsn, _ = live_dsn
    monkeypatch.setenv("GLITCHTIP_DSN", dsn)
    assert runtime.configure({"enabled": True}) is True
    assert runtime.is_active()
    assert runtime.configure({"enabled": False}) is False
    assert runtime.is_active() is False
    assert runtime.configure({"enabled": True}) is True  # re-arms cleanly
    assert runtime.is_active()


def test_configure_from_config_and_capture(live_dsn, monkeypatch):
    monkeypatch.delenv("GLITCHTIP_DSN", raising=False)
    dsn, events = live_dsn
    assert runtime.configure({"dsn": dsn, "environment": "ci"}) is True
    eid = run(runtime.acapture_exception(ValueError("boom"), tags={"surface": "t"}))
    assert eid == "ok"
    ev = events[-1]["body"]
    assert ev["exception"]["values"][0]["type"] == "ValueError"
    assert ev["environment"] == "ci"
    assert ev["tags"]["surface"] == "t"
    assert len(ev["tags"]["trace_id"]) == 32  # minted — no inbound traceparent


def test_env_dsn_overrides_config(live_dsn, monkeypatch):
    dsn, events = live_dsn
    monkeypatch.setenv("GLITCHTIP_DSN", dsn)
    assert runtime.configure({"dsn": "http://wrong@127.0.0.1:1/1"}) is True
    assert run(runtime.acapture_message("hi")) == "ok"


def test_configure_idempotent_and_retryable(live_dsn, monkeypatch):
    dsn, _events = live_dsn
    monkeypatch.delenv("GLITCHTIP_DSN", raising=False)
    assert runtime.configure({}) is False  # no latch on failure
    monkeypatch.setenv("GLITCHTIP_DSN", dsn)
    assert runtime.configure() is True   # later call can still activate
    assert runtime.configure() is True   # second success no-ops


def test_send_failure_cooldown(monkeypatch):
    # Unreachable host: first send fails; inside the cooldown window the
    # transport must not even be attempted (no repeated connect+timeout).
    monkeypatch.setenv("GLITCHTIP_DSN", "http://k@127.0.0.1:1/9")
    runtime.configure()
    assert runtime.capture_message("one") is None

    calls = []
    runtime._client.send_event = lambda *a, **kw: calls.append(1) or "x"  # type: ignore[union-attr]
    assert runtime.capture_message("two") is None
    assert calls == []


def test_unserializable_event_does_not_arm_cooldown(live_dsn, monkeypatch):
    # A poison event (non-JSON value in the request block) is dropped at the
    # serialization step — it is NOT a transport failure and must not latch
    # the send cooldown.
    dsn, events = live_dsn
    monkeypatch.setenv("GLITCHTIP_DSN", dsn)
    runtime.configure()
    assert runtime.capture_message(
        "poison", request={"url": "/x", "weird": object()}
    ) is None
    assert run(runtime.acapture_message("healthy")) == "ok"  # transport still live


def test_bad_numeric_config_never_raises(live_dsn, monkeypatch):
    dsn, _events = live_dsn
    monkeypatch.delenv("GLITCHTIP_DSN", raising=False)
    for cfg in (
        {"dsn": dsn, "send_timeout_s": "banana", "breadcrumbs_max": "x"},
        {"dsn": dsn, "send_timeout_s": float("nan")},
        {"dsn": dsn, "send_timeout_s": float("inf"), "breadcrumbs_max": -5},
        {"dsn": dsn, "send_timeout_s": -1},
    ):
        runtime._reset()
        assert runtime.configure(cfg) is True


def test_nonstring_config_values_never_raise(live_dsn, monkeypatch):
    dsn, _events = live_dsn
    monkeypatch.delenv("GLITCHTIP_DSN", raising=False)
    # yaml can hand back ints/dicts for environment/release — must not .strip() crash
    assert runtime.configure(
        {"dsn": dsn, "environment": 42, "release": {"v": 1}}
    ) is True


def test_capture_mints_trace_id_without_api_context(live_dsn, monkeypatch):
    # Agent-loop threads never see an inbound traceparent — the capture path
    # must mint a trace so every event carries trace_id.
    dsn, events = live_dsn
    monkeypatch.setenv("GLITCHTIP_DSN", dsn)
    runtime.configure()
    assert trace_context.current() == (None, None)
    assert run(runtime.acapture_exception(RuntimeError("loop boom"))) == "ok"
    ev = events[-1]["body"]
    assert len(ev["tags"]["trace_id"]) == 32
    assert ev["contexts"]["trace"]["type"] == "trace"
    assert len(ev["contexts"]["trace"]["span_id"]) == 16


# --- _85_ capture extension -------------------------------------------------


def test_capture_extension_reports_unhandled(live_dsn, monkeypatch):
    dsn, events = live_dsn
    monkeypatch.setenv("GLITCHTIP_DSN", dsn)
    runtime.configure()
    mod = _load_agent_capture()
    agent = FakeAgent(context=FakeContext("ctx-9"), agent_name="agent0")
    # Real a0 handle_exception args: (self, location, exception)
    exc = RuntimeError("tool exploded")
    data = {"exception": exc, "args": ("self", "message_loop", exc)}
    run(mod.GlitchtipCapture(agent).execute(data=data))
    ev = events[-1]["body"]
    assert ev["exception"]["values"][0]["type"] == "RuntimeError"
    assert ev["tags"]["location"] == "message_loop"
    assert ev["tags"]["agent_name"] == "agent0"
    assert ev["tags"]["context_id"] == "ctx-9"
    assert ev["tags"]["surface"] == "agent_loop"
    assert len(ev["tags"]["trace_id"]) == 32


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
    run(mod.GlitchtipCapture(agent).execute(data=None))   # missing data dict
    run(mod.GlitchtipCapture(agent).execute())            # no kwargs at all
    assert events == []


def test_capture_extension_never_raises(monkeypatch):
    # Broken-plugin tolerance: extension must swallow even when data/args
    # are hostile — an extension raise would mask the host's exception.
    monkeypatch.delenv("GLITCHTIP_DSN", raising=False)
    mod = _load_agent_capture()
    agent = FakeAgent()
    run(mod.GlitchtipCapture(agent).execute(data={"exception": ValueError("x"),
                                                "args": 42}))
    run(mod.GlitchtipCapture(agent).execute(data=object()))


def test_context_extension_reports_via_args0(live_dsn, monkeypatch):
    # AgentContext level: self.agent is always None; context id comes from
    # args[0] (the AgentContext object in the exception call args).
    dsn, events = live_dsn
    monkeypatch.setenv("GLITCHTIP_DSN", dsn)
    runtime.configure()
    mod = importlib.import_module(
        "usr.plugins.glitchtip.extensions.python._functions.agent.AgentContext.handle_exception.end._85_glitchtip_capture"
    )
    exc = ValueError("chain boom")
    ctx = FakeContext("ctx-from-args")
    data = {"exception": exc, "args": (ctx, "process_chain", exc)}
    run(mod.GlitchtipCapture(None).execute(data=data))
    assert len(events) == 1
    ev = events[-1]["body"]
    assert ev["tags"]["surface"] == "agent_context"
    assert ev["tags"]["context_id"] == "ctx-from-args"
    assert ev["tags"]["location"] == "process_chain"


def test_capture_extension_dedupes_agent_and_context(live_dsn, monkeypatch):
    # One exception traversing both hook levels must produce one event.
    dsn, events = live_dsn
    monkeypatch.setenv("GLITCHTIP_DSN", dsn)
    runtime.configure()
    agent_mod = _load_agent_capture()
    ctx_mod = importlib.import_module(
        "usr.plugins.glitchtip.extensions.python._functions.agent.AgentContext.handle_exception.end._85_glitchtip_capture"
    )
    exc = RuntimeError("seen twice")
    data = {"exception": exc, "args": ("self", "loc", exc)}
    agent = FakeAgent(context=FakeContext())
    run(agent_mod.GlitchtipCapture(agent).execute(data=data))
    run(ctx_mod.GlitchtipCapture(None).execute(data=data))
    assert len(events) == 1


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
    assert snap[-1]["data"] == {"break_loop": False}
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


def test_crumb_never_raises_on_hostile_input():
    breadcrumbs.crumb("t", "m", data=object())           # non-dict data
    breadcrumbs.crumb("t", "m", data={42: "int key", "ok": object()})
    snap = breadcrumbs.snapshot()[-1]
    assert snap["data"]["ok"] is not None  # object() coerced to str


# --- startup init + ApiHandler patch ----------------------------------------


def test_init_configures_and_patches(live_dsn, monkeypatch):
    dsn, events = live_dsn
    monkeypatch.setenv("GLITCHTIP_DSN", dsn)
    mod = _load_init_ext()
    mod.GlitchtipInit().execute()  # sync — call_extensions_sync contract
    assert runtime.is_active()
    assert _wrap_marker() is not None


def test_init_never_raises_on_broken_config(monkeypatch):
    # call_extensions_sync has no per-extension guard — execute() must
    # swallow everything or a0 boot aborts.
    monkeypatch.setenv("GLITCHTIP_DSN", "http://k@h/1")
    mod = _load_init_ext()
    import usr.plugins.glitchtip.helpers.config as cfgmod

    orig = cfgmod.get_config
    cfgmod.get_config = lambda: (_ for _ in ()).throw(RuntimeError("cfg boom"))
    try:
        mod.GlitchtipInit().execute()  # must not raise
    finally:
        cfgmod.get_config = orig


def test_double_init_no_double_wrap(live_dsn, monkeypatch):
    dsn, _events = live_dsn
    monkeypatch.setenv("GLITCHTIP_DSN", dsn)
    mod = _load_init_ext()
    mod.GlitchtipInit().execute()
    from helpers.api import ApiHandler

    first = ApiHandler.handle_request
    orig = _wrap_marker()
    mod.GlitchtipInit().execute()
    assert ApiHandler.handle_request is first
    assert _wrap_marker() is orig


def test_api_500_emits_message_event(live_dsn, monkeypatch):
    dsn, events = live_dsn
    monkeypatch.setenv("GLITCHTIP_DSN", dsn)
    mod = _load_init_ext()
    mod.GlitchtipInit().execute()

    from helpers.api import ApiHandler

    class BrokenHandler(ApiHandler):
        async def process(self, input, request):
            raise RuntimeError("db gone")

    resp = run(BrokenHandler().handle_request(FakeRequest(path="/api/x")))
    assert resp.status_code == 500
    ev = events[-1]["body"]
    assert "message" in ev and "db gone" in ev["message"]
    assert ev["tags"]["surface"] == "api"
    assert ev["tags"]["path"] == "/api/x"
    assert len(ev["tags"]["trace_id"]) == 32


def test_api_500_event_adopts_traceparent(live_dsn, monkeypatch):
    dsn, events = live_dsn
    monkeypatch.setenv("GLITCHTIP_DSN", dsn)
    mod = _load_init_ext()
    mod.GlitchtipInit().execute()
    from helpers.api import ApiHandler

    class BrokenHandler(ApiHandler):
        async def process(self, input, request):
            raise RuntimeError("x")

    req = FakeRequest(headers={"traceparent": "00-" + "ab" * 16 + "-" + "cd" * 8 + "-01"})
    run(BrokenHandler().handle_request(req))
    assert events[-1]["body"]["tags"]["trace_id"] == "ab" * 16


def test_api_response_carries_traceparent(live_dsn, monkeypatch):
    dsn, events = live_dsn
    monkeypatch.setenv("GLITCHTIP_DSN", dsn)
    mod = _load_init_ext()
    mod.GlitchtipInit().execute()
    from helpers.api import ApiHandler

    class OkHandler(ApiHandler):
        async def process(self, input, request):
            return {"ok": True}

    resp = run(OkHandler().handle_request(FakeRequest()))
    assert resp.headers.get("traceparent", "").startswith("00-")
    assert events == []


def test_api_ok_response_no_event(live_dsn, monkeypatch):
    dsn, events = live_dsn
    monkeypatch.setenv("GLITCHTIP_DSN", dsn)
    mod = _load_init_ext()
    mod.GlitchtipInit().execute()
    from helpers.api import ApiHandler

    class OkHandler(ApiHandler):
        async def process(self, input, request):
            return {"ok": True}

    resp = run(OkHandler().handle_request(FakeRequest()))
    assert resp.status_code == 200
    assert events == []


def test_api_error_events_false_still_stamps_traceparent(live_dsn, monkeypatch):
    # Flag gates only the >=500 emission; trace adoption/stamping stay on.
    dsn, events = live_dsn
    monkeypatch.setenv("GLITCHTIP_DSN", dsn)
    import usr.plugins.glitchtip.helpers.config as cfgmod

    orig = cfgmod.get_config
    cfgmod.get_config = lambda: {"api_error_events": False}
    try:
        mod = _load_init_ext()
        mod.GlitchtipInit().execute()
    finally:
        cfgmod.get_config = orig
    assert _wrap_marker() is not None
    from helpers.api import ApiHandler

    class BrokenHandler(ApiHandler):
        async def process(self, input, request):
            raise RuntimeError("quiet")

    resp = run(BrokenHandler().handle_request(FakeRequest()))
    assert resp.status_code == 500
    assert resp.headers.get("traceparent", "").startswith("00-")
    assert events == []


def test_wrapper_captures_and_reraises_propagating_exception(live_dsn, monkeypatch):
    dsn, events = live_dsn
    monkeypatch.setenv("GLITCHTIP_DSN", dsn)
    mod = _load_init_ext()
    mod.GlitchtipInit().execute()
    from helpers.api import ApiHandler

    class LeakyHandler(ApiHandler):
        _propagate = True

        async def process(self, input, request):
            raise RuntimeError("escaped the handler")

    with pytest.raises(RuntimeError, match="escaped the handler"):
        run(LeakyHandler().handle_request(FakeRequest(path="/api/y")))
    ev = events[-1]["body"]
    assert ev["exception"]["values"][0]["type"] == "RuntimeError"
    assert ev["tags"]["surface"] == "api"


def test_wrapper_pure_passthrough_when_inactive_mid_process(live_dsn, monkeypatch):
    # Patch is one-way; if the plugin is disabled after install the wrapper
    # must do nothing but delegate.
    dsn, events = live_dsn
    monkeypatch.setenv("GLITCHTIP_DSN", dsn)
    mod = _load_init_ext()
    mod.GlitchtipInit().execute()
    runtime._reset()  # disables mid-process
    from helpers.api import ApiHandler

    class OkHandler(ApiHandler):
        async def process(self, input, request):
            return {"ok": True}

    resp = run(OkHandler().handle_request(FakeRequest(
        headers={"traceparent": "00-" + "ab" * 16 + "-" + "cd" * 8 + "-01"})))
    assert resp.status_code == 200
    assert "traceparent" not in resp.headers
    assert events == []


def test_wrapper_passthrough_after_plugin_removal(live_dsn, monkeypatch):
    # Plugin files removed mid-process: the one-way patch survives, so its
    # in-wrapper import must degrade to passthrough — not 500 every request.
    dsn, events = live_dsn
    monkeypatch.setenv("GLITCHTIP_DSN", dsn)
    mod = _load_init_ext()
    mod.GlitchtipInit().execute()
    from helpers.api import ApiHandler

    class OkHandler(ApiHandler):
        async def process(self, input, request):
            return {"ok": True}

    # Poison the package entry only for the wrapped call — `run()`'s own
    # post-await import would hit the same ImportError otherwise.
    helpers_mod = sys.modules["usr.plugins.glitchtip.helpers"]

    async def drive():
        sys.modules["usr.plugins.glitchtip.helpers"] = None
        try:
            return await OkHandler().handle_request(FakeRequest())
        finally:
            sys.modules["usr.plugins.glitchtip.helpers"] = helpers_mod

    resp = run(drive())
    assert resp.status_code == 200
    assert "traceparent" not in resp.headers
    assert events == []


def test_patch_not_applied_when_inactive(monkeypatch):
    monkeypatch.delenv("GLITCHTIP_DSN", raising=False)
    mod = _load_init_ext()
    mod.GlitchtipInit().execute()
    assert _wrap_marker() is None
