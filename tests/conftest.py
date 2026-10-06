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
        plain-text 500. The plugin's patch observes this response."""
        try:
            output = await self.process({}, request)
            return Response(status=200, body=output)
        except Exception as e:
            return Response(status=500, body=f"API error: {e}")

    async def process(self, input, request):
        raise NotImplementedError


class Response:
    def __init__(self, message="", status=200, body=None, **kw):
        self.message = message
        self.status_code = status
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
    return asyncio.run(coro)


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_runtime():
    """Every test starts with the plugin unconfigured, no trace context, and
    the ApiHandler patch (process-global when applied) rolled back."""
    from usr.plugins.glitchtip.helpers import breadcrumbs, runtime, trace_context

    runtime.reset()
    trace_context.reset()
    breadcrumbs.clear()
    yield
    runtime.reset()
    trace_context.reset()
    breadcrumbs.clear()
    orig = getattr(ApiHandler, "_glitchtip_original", None)
    if orig is not None:
        ApiHandler.handle_request = orig
        del ApiHandler._glitchtip_original
