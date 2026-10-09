# a0-plugin-glitchtip — agent notes

An [Agent Zero](https://github.com/agent0ai/agent-zero) plugin that reports
unhandled exceptions to self-hosted GlitchTip with OTel-format trace IDs.
`README.md` is the user-facing doc; this file is what an agent needs that the
README does not say.

## Commands

```bash
# Tests — standalone, offline, no A0 checkout required
python3.12 -m pytest tests/ -q
# …or without pytest installed: uv run --with pytest python -m pytest tests/ -q

# CI (.github/workflows/ci.yml): Python 3.12, pip install pytest, pytest -q
```

There is no linter or formatter configured. Do not add one in an unrelated
change.

## Layout

| Path | What it is |
|---|---|
| `plugin.yaml` | Manifest — `name: glitchtip` is the `usr/plugins/glitchtip` install path; do not rename casually. |
| `default_config.yaml` | Endpoints/policy only. A real DSN is semi-secret (public key) — prefer `GLITCHTIP_DSN` env over writing it here. |
| `helpers/dsn.py` | Sentry DSN parse → `Dsn(base, project_id, public_key, scheme)` + store URL/auth header. Keeps reverse-proxy path prefixes; `public_key` excluded from repr. |
| `helpers/event.py` | exception/message → Sentry **store** event dict; frames in `extract_tb` order (caller→raise-site); `_SENSITIVE_HEADERS` denylist + fail-closed per-field redactor. |
| `helpers/client.py` | stdlib `urllib` POST of pre-serialized bytes to `{base}/api/{project}/store/` with `X-Sentry-Auth`; **redirects refused** (would leak auth+body). Never raises — failures return None. |
| `helpers/runtime.py` | Facade: `configure()` (env > config), `capture_*` (sync) / `acapture_*` (`asyncio.to_thread`), `spawn()` (fire-and-forget), 60s send-failure cooldown, `_MAX_IN_FLIGHT` cap, baseline redactor + omaseal layering, `is_noise_exception`/`report_loop_exception` shared by the `_85_` extensions, `_reset` (test hook). |
| `helpers/config.py` | `DEFAULTS` + `get_config()` = a0's `get_plugin_config` merge (which already folds in `default_config.yaml`); `num`/`truthy` safe coercion. |
| `helpers/trace_context.py` | W3C `traceparent` parse/generate + ContextVar storage; rejects version `ff`, all-zero IDs, malformed fields. |
| `helpers/breadcrumbs.py` | Ring buffer; strips forbidden keys (`value`, `args`, `output`, …) defensively; `reset()` restores default capacity. |
| `extensions/python/startup_migration/_20_*` | Plugin init: configure + apply the ApiHandler patch. Runs in `initialize.py` via `call_extensions_sync` — **sync execute, fully guarded** (a raise aborts a0 boot). |
| `extensions/python/_functions/.../handle_exception/end/_85_*` | Exception capture — see ordering contract below. |
| `extensions/python/tool_execute_after/_30_*` | Tool-name/status breadcrumb — never args/output. |
| `api/glitchtip_test.py` | `POST /api/plugins/glitchtip/glitchtip_test` test event; auth+CSRF inherited. |
| `hooks.py` | install/uninstall lifecycle — log only, lazy imports, never raises. |

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
- **Sync `capture_*` block the loop.** They do a blocking urllib POST (up to
  `send_timeout_s`). In async contexts (extensions, ApiHandler code) use
  `acapture_*`, which offload via `asyncio.to_thread`; ContextVars propagate
  through `to_thread`, so trace context survives the hop.
- **Send-failure cooldown.** One failed POST suppresses all sending for 60s
  (`_SEND_COOLDOWN_S`) — an unreachable GlitchTip plus an exception storm must
  not compound into repeated connect+timeout work. "Second event never sent"
  in tests/debugging is this.
- **Config keys are a three-way sync.** A new key lands in
  `helpers/config.py DEFAULTS`, `default_config.yaml`, and the README settings
  table. `default_config.yaml` and `get_plugin_config("glitchtip")` merge over
  `DEFAULTS` in that order.
- **Redaction is layered.** `_baseline_redact` (regex denylist — Bearer/`sk-`/
  `gh*`/`AKIA`/`key=value`/PEM blocks) always runs; when `a0-plugin-omaseal` is
  installed, its `mask_text` registry composes over it. The soft import in
  `_resolve_redactor` is optional wiring, not a missing dep — do not "fix" it.
- **`_85_` dedup marker.** `report_loop_exception` sets `exc._glitchtip_reported`
  so an exception traversing both Agent- and AgentContext-level hooks emits
  exactly one event.
- **Spawn is fire-and-forget.** `runtime.spawn(coro)` schedules captures the
  response/raise path must not wait on (API events); refs live in
  `runtime._tasks` until done. Tests drain via the `run()` helper in conftest.
- **`_reset()` leaves the ApiHandler patch installed** — intentionally one-way
  for the process; the wrapper goes pure-passthrough when inactive (tests
  un-patch via `ApiHandler._glitchtip_original`).
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
