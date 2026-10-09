"""Make `usr.plugins.glitchtip.*` imports resolvable under pytest — the same
qualified path the A0 runtime uses inside usr/plugins/glitchtip/ — and stub
the framework modules the plugin imports (helpers.extension,
helpers.plugins, helpers.api, helpers.errors) so everything runs standalone,
offline. No network except a loopback http.server fixture in test_client.py.
"""

import asyncio
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _pkg(name, path=None):
    mod = types.ModuleType(name)
    mod.__path__ = [str(path)] if path else []
    return mod


_usr = _pkg("usr")
_plugins = _pkg("usr.plugins")
_glitchtip = _pkg("usr.plugins.glitchtip", ROOT)
_usr.plugins = _plugins
_plugins.glitchtip = _glitchtip
sys.modules.setdefault("usr", _usr)
sys.modules.setdefault("usr.plugins", _plugins)
sys.modules["usr.plugins.glitchtip"] = _glitchtip


# --- minimal A0 framework stubs ---------------------------------------------


class Extension:
    def __init__(self, agent=None, **kw):
        self.agent = agent


class ApiHandler:
    def __init__(self, app=None, thread_lock=None):
        self.app = app
        self.thread_lock = thread_lock

    @classmethod
    def requires_auth(cls) -> bool:
        return True

    @classmethod
    def requires_csrf(cls) -> bool:
        return cls.requires_auth()

    @classmethod
    def get_methods(cls):
        return ["POST"]

    async def handle_request(self, request):
        """Mirrors upstream: wraps process(), swallows exceptions into a
        plain-text 500. The plugin's patch observes this response.
        `_propagate=True` models handler flavors that re-raise instead of
        swallowing — exercises the wrapper's capture-then-reraise branch."""
        try:
            output = await self.process({}, request)
            return Response(status=200, body=output)
        except Exception as e:
            if getattr(self, "_propagate", False):
                raise
            return Response(status=500, body=f"API error: {e}")

    async def process(self, input, request):
        raise NotImplementedError


class Response:
    def __init__(self, message="", status=200, body=None, **kw):
        self.message = message
        self.status_code = status
        self.headers = {}  # Quart Response has a headers mapping
        self._body = body if body is not None else message

    def get_data(self, as_text=False):
        return self._body if as_text else str(self._body).encode()


class FakeRequest:
    def __init__(self, path="/api/x", method="POST", headers=None):
        self.path = path
        self.method = method
        self.headers = dict(headers or {})


class HandledException(Exception):
    pass


class RepairableException(Exception):
    pass


class InterventionException(Exception):
    pass


_helpers = _pkg("helpers")

_ext = types.ModuleType("helpers.extension")
_ext.Extension = Extension
_helpers.extension = _ext

_plugins_mod = types.ModuleType("helpers.plugins")
_plugins_mod.get_plugin_config = lambda name: {}
_helpers.plugins = _plugins_mod

_api_mod = types.ModuleType("helpers.api")
_api_mod.ApiHandler = ApiHandler
_api_mod.Request = FakeRequest
_api_mod.Response = Response
_helpers.api = _api_mod

_errors_mod = types.ModuleType("helpers.errors")
_errors_mod.HandledException = HandledException
_errors_mod.RepairableException = RepairableException
_errors_mod.InterventionException = InterventionException
_helpers.errors = _errors_mod

sys.modules.setdefault("helpers", _helpers)
sys.modules["helpers.extension"] = _ext
sys.modules["helpers.plugins"] = _plugins_mod
sys.modules["helpers.api"] = _api_mod
sys.modules["helpers.errors"] = _errors_mod


class FakeAgent:
    def __init__(self, context=None, agent_name="a0"):
        self.context = context
        self.agent_name = agent_name


class FakeContext:
    def __init__(self, id="ctx-1"):
        self.id = id


def run(coro):
    """Drive a coroutine to completion, then drain any captures the code
    spawned via runtime.spawn() — asyncio.run cancels pending tasks at
    teardown, so without the drain fire-and-forget captures would silently
    never execute in tests (in real a0 the loop persists)."""
    async def _main():
        result = await coro
        from usr.plugins.glitchtip.helpers import runtime

        tasks = list(runtime._tasks)
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        return result

    return asyncio.run(_main())


import json  # noqa: E402
import threading  # noqa: E402
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer  # noqa: E402

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_runtime():
    """Every test starts with the plugin unconfigured (runtime.reset clears
    client/latch/cooldown/redactor + breadcrumbs + trace context) and the
    ApiHandler patch (process-global when applied) rolled back."""
    from usr.plugins.glitchtip.helpers import runtime

    runtime._reset()
    yield
    runtime._reset()
    orig = getattr(ApiHandler, "_glitchtip_original", None)
    if orig is not None:
        ApiHandler.handle_request = orig
        del ApiHandler._glitchtip_original


class _StoreHandler(BaseHTTPRequestHandler):
    """Loopback stand-in for GlitchTip's store endpoint — encodes the Sentry
    ingest contract (POST /api/<project>/store/, X-Sentry-Auth). Only accepts
    project 9 so tests can also assert the 404 path."""

    received: list = []

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length)
        type(self).received.append(
            {
                "path": self.path,
                "auth": self.headers.get("X-Sentry-Auth"),
                "body": json.loads(body or b"{}"),
            }
        )
        if self.path == "/api/8/store/":
            # redirect fixture: a compliant client must NOT follow this —
            # forwarding would leak X-Sentry-Auth + the event body
            self.send_response(302)
            self.send_header("Location", "/api/9/store/")
            self.end_headers()
            return
        if self.path == "/api/7/store/":
            # 200 with no id field — exercises the event-id fallback path
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b"{}")
            return
        status = 200 if self.path == "/api/9/store/" else 404
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"id": "ok"}')

    def log_message(self, *a):
        pass


@pytest.fixture()
def live_dsn():
    """Yields (dsn, events_list): a loopback store server + captured posts."""
    _StoreHandler.received = []
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _StoreHandler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://pubkey@127.0.0.1:{srv.server_port}/9", _StoreHandler.received
    srv.shutdown()
    srv.server_close()
