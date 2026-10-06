# a0-plugin-glitchtip — agent notes

An [Agent Zero](https://github.com/agent0ai/agent-zero) plugin that reports
unhandled exceptions to self-hosted GlitchTip with OTel-format trace IDs.
`README.md` is the user-facing doc; this file is what an agent needs that the
README does not say.

## Commands

```bash
# Tests — standalone, offline, no A0 checkout required
python3.12 -m pytest tests/ -q

# CI (.github/workflows/ci.yml): Python 3.12, pip install pytest, pytest -q
```

There is no linter or formatter configured. Do not add one in an unrelated
change.

## Layout

| Path | What it is |
|---|---|
| `plugin.yaml` | Manifest — `name: glitchtip` is the `usr/plugins/glitchtip` install path; do not rename casually. |
| `default_config.yaml` | Endpoints/policy only. A real DSN is semi-secret (public key) — prefer `GLITCHTIP_DSN` env over writing it here. |
| `helpers/dsn.py` | Sentry DSN parse → `{base, project_id, public_key}` + store URL/auth header. |
| `helpers/event.py` | exception/message → Sentry **store** event dict; stack frames via `traceback.extract_tb`; header redaction + injectable secret redactor. |
| `helpers/client.py` | stdlib `urllib` POST to `{base}/api/{project}/store/` with `X-Sentry-Auth`. **Never raises** — failures return None. |
| `helpers/runtime.py` | Facade: `configure()` (env > config), `capture_exception`, `capture_message`, `is_active`, `reset` (test hook). |
| `helpers/trace_context.py` | W3C `traceparent` parse/generate + ContextVar storage. |
| `helpers/breadcrumbs.py` | Ring buffer; strips forbidden keys (`value`, `args`, `output`, …) defensively. |
| `extensions/python/startup_migration/_20_*` | Plugin init: configure + apply the ApiHandler patch. Runs in `initialize.py`, sync context, `agent=None`. |
| `extensions/python/_functions/.../handle_exception/end/_85_*` | Exception capture — see ordering contract below. |
| `extensions/python/tool_execute_after/_30_*` | Tool-name/status breadcrumb — never args/output. |
| `api/glitchtip_test.py` | `POST /api/plugins/glitchtip/glitchtip_test` test event; auth+CSRF inherited. |

## Conventions that will bite you

- **Zero deps is deliberate.** a0 has no plugin dependency mechanism and
  `sentry_sdk` is not in a0's requirements. The hand-rolled store-endpoint
  client is the price of stock-install compatibility — do not "upgrade" to
  `sentry_sdk` unless a0 gains a deps story. If GlitchTip ingest misbehaves,
  the fallback is the `/api/<id>/envelope/` endpoint, not the SDK.
- **Imports use the A0-qualified path** — `usr.plugins.glitchtip.helpers...`,
  not `helpers.runtime`. `tests/conftest.py` synthesizes the package and stubs
  `helpers.extension`, `helpers.plugins`, `helpers.api`, `helpers.errors`.
- **`_85_` ordering is the contract.** `handle_exception` is `@extensible`;
  core `_40_`/`_50_` extensions clear Intervention/Repairable exceptions and
  `_90_` wraps the rest as `HandledException`. At `_85_` the exception is
  still raw — capture there, not at `_95_` (you'd get the wrapper) or `_45_`
  (you'd report repairable noise). The same goes for `AgentContext`.
- **The ApiHandler patch is post-inspection.** `handle_request` swallows
  exceptions into a 500 text response; we observe the response, so API events
  are message-level — no stack. Do not try to reimplement `handle_request`'s
  body to recover the stack: that duplicates core logic and rots silently.
- **Never-raise rule.** Every public helper and every extension `execute`
  swallows its own failures — error reporting must never break the host.
- **Tests must stay offline** — loopback `http.server` fixtures only, no real
  GlitchTip, no sentry_sdk.
- **DSN auth is the public key only.** Still never log a DSN — it identifies
  the project endpoint.
- The `ApiHandler` patch is process-global; tests restore it via
  `ApiHandler._glitchtip_original` in the autouse conftest fixture.

## Hermes port note

The portable surface is `helpers/` in full (dsn, event, client,
trace_context, breadcrumbs, runtime) — stdlib-only, no framework imports.
A Hermes plugin would wrap `runtime.configure`/`capture_exception` behind
`register(ctx)` hooks; the a0-specific parts (extensions, api handler,
plugin.yaml settings) stay here as the a0 shim.
