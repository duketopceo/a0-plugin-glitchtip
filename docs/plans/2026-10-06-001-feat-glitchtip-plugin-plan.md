# Plan: a0-plugin-glitchtip — GlitchTip error tracking + trace correlation

**Origin:** [duketopceo/Khan#193](https://github.com/duketopceo/Khan/issues/193) · milestone 8 (Caravanserai — plugin decomposition)
**Sources:** `helpers/glitchtip.py` (151 LOC), `helpers/request_id.py` (99 LOC), `helpers/observability.py` (190 LOC, error-path wiring only) in the Khan fork.
**Template/conventions:** `a0-plugin-omaseal` (sibling plugin — same layout, conftest stubs, CI shape, A0-qualified imports).

## Problem frame

Khan ships Sentry-compatible error reporting pointed at self-hosted GlitchTip. Upstream a0 and the community index cover **tracing** (`langfuse_observability`) but nothing ships **error tracking** or request-ID correlation. This plugin extracts that capability so stock a0 gets: unhandled agent-loop and API exceptions → GlitchTip events tagged with a W3C/OTel-compatible trace ID.

**Scope boundary:** error capture + trace correlation only. No Langfuse-style tracing rebuild, no performance spans (GlitchTip is error-only anyway), no fork changes (Khan files are read-only sources — deletion is a later milestone issue).

## Key technical decisions (KTDs)

1. **Zero-dep transport instead of `sentry_sdk`.** Khan wraps `sentry_sdk` lazily; a0 has no plugin dependency mechanism (`plugin.yaml` carries no deps field; `helpers/plugins.py` never pip-installs) and `sentry_sdk` is absent from a0's `requirements.txt`. A lazy-import port would be dead on arrival for stock installs. Instead ship a ~150-LOC sender that POSTs a Sentry **store** event (`POST {dsn_base}/api/{project_id}/store/`, `X-Sentry-Auth` header) via stdlib `urllib` — GlitchTip implements this endpoint for legacy SDKs. *Rejected alternative:* lazy `sentry_sdk` import (needs a manual pip install nobody will do). *If GlitchTip store-ingest proves unreliable, fall back to the `/envelope/` endpoint — same zero-dep transport, different body framing.*
2. **Capture point = `@extensible` `handle_exception` end-extensions.** Upstream wraps `AgentContext.handle_exception` (process_chain) and `Agent.handle_exception` (message_loop/monologue) with `extension.extensible`; the decorator captures the raised exception into `data["exception"]` and runs `end` extensions regardless. Core extensions `_40_`/`_50_` clear Intervention/Repairable exceptions; `_90_` wraps the remainder as `HandledException`. Our **`_85_`** slot sees only still-fatal, raw exceptions — exactly the "unhandled" set — and still sees the real traceback before `_90_` re-wraps. Ship two files: `_functions/agent/Agent/handle_exception/end/_85_glitchtip_capture.py` and `_functions/agent/AgentContext/handle_exception/end/_85_glitchtip_capture.py`. Skip `HandledException`/`asyncio.CancelledError` defensively.
3. **API surface: wrap `ApiHandler.handle_request` at startup.** Handler exceptions are swallowed inside `handle_request` (returns plain-text 500) — nothing propagates to Flask error handlers and `_dispatch`/`handle_request` are not extensible. A `startup_migration` extension (runs in `initialize.py`, sync, `agent=None`, before the app exists) monkey-patches `ApiHandler.handle_request`: after the original returns, a `status_code >= 500` response emits a **message-level** event tagged with `request.path`/`method`/trace ID; a propagating exception (shouldn't happen, defensive) is captured and re-raised. Message-level events carry no stack — the stack is gone by then; this is a documented limitation, not a silent one.
4. **Request ID = W3C `traceparent` (OTel-compatible), not uuid4.** Khan mints `X-Request-ID` uuid4s; the issue directs OTel trace context. `helpers/trace_context.py` parses an inbound `traceparent` header (`00-<32-hex-trace>-<16-hex-span>-<flags>`) else generates fresh trace/span IDs, stores them in a `ContextVar`, and sets `data`-level tags so GlitchTip events carry `trace_id` — the same ID format Langfuse emits, giving the cross-tool correlation the issue asks for (documented as: search the trace ID in both tools).
5. **DSN via env or plugin settings; no secrets-in-config.** `default_config.yaml` fields: `enabled`, `dsn` (prefer `GLITCHTIP_DSN` env; the settings field accepts a name-style reference users can point at omaseal), `environment` (default `local`), `release`, `api_error_events` (bool, gate the handle_request patch), `breadcrumbs_max`, `send_timeout_s`. DSNs embed only the project *public* key — semi-secret, not a credential; still never logged.
6. **Init + patch happen in `startup_migration`.** No `sentry_sdk.init` global — our module holds a lazily-built client; `enabled:false` or missing DSN → everything is a no-op. All public helpers never raise.

## Layout (all paths repo-relative)

```
plugin.yaml
default_config.yaml
hooks.py                        # install(): stdlib-only, probe nothing, write state note; uninstall(): no-op (keep nothing — we write no state)
helpers/
  dsn.py                        # parse Sentry DSN → {base, project_id, public_key}
  event.py                      # exception → Sentry store-event dict (stacktrace frames via traceback.extract_tb, scrub hook)
  client.py                     # urllib POST /store, timeout, X-Sentry-Auth; swallows all errors, returns event_id|None
  trace_context.py              # traceparent parse/generate + ContextVar, trace_id/span_id accessors
  breadcrumbs.py                # global ring buffer (deque maxlen=N), crumb(category,msg,data)
  runtime.py                    # facade: configure(cfg), capture_exception(exc, tags), capture_message(msg, level, tags), is_active()
extensions/python/
  startup_migration/_20_glitchtip_init.py         # configure from plugin config + env; apply handle_request patch when api_error_events
  _functions/agent/Agent/handle_exception/end/_85_glitchtip_capture.py
  _functions/agent/AgentContext/handle_exception/end/_85_glitchtip_capture.py
  tool_execute_after/_30_glitchtip_breadcrumb.py  # crumb per tool call (name + ok/err status only — never args/output)
api/glitchtip_test.py           # POST → emits test event; returns {"ok": true, "event_id": ...}; ApiHandler auth+CSRF inherited
tests/
  conftest.py                   # copy omaseal pattern: synthesize usr.plugins.glitchtip package; stub helpers.api (ApiHandler/Request/Response), helpers.extension (Extension), helpers.plugins (get_plugin_config), helpers.errors (HandledException/RepairableException/InterventionException), agent module
  test_dsn.py, test_event.py, test_client.py, test_trace_context.py, test_capture.py, test_api.py
README.md                       # usage, GlitchTip↔Langfuse trace-ID correlation, known limitations
AGENTS.md                       # layout/contracts/agent gotchas (modeled on omaseal's)
LICENSE                         # MIT (Khan/a0 preserve)
.github/workflows/ci.yml        # copy omaseal's pytest job
```

Conventions inherited from omaseal: imports use the a0-qualified path (`usr.plugins.glitchtip.helpers...`), tests run offline with stubbed framework modules, `cryptography`-only-dependency rule does NOT apply — this plugin is stdlib-only.

## Implementation units

### U1 — `helpers/dsn.py` + `helpers/event.py` (pure, stdlib)
- `parse_dsn(str) -> Dsn | None`: `{scheme}://{public_key}@{host}[:port]/{project_id}`; reject malformed/missing project_id.
- `build_event(exc, *, trace, tags, release, environment, breadcrumbs) -> dict`: `event_id` (uuid4 hex), `timestamp`, `level:"error"`, `platform:"python"`, `exception.values[{type,value,stacktrace.frames}]` (frames reversed, in_app=True for usr/plugins paths), `tags`, `contexts.trace.{trace_id,span_id}`, `breadcrumbs.values`.
- `scrub_event(event)`: redact `request.headers.{authorization,cookie,x-api-key}`; recurse-scrub values via an injected redactor (callable, default identity) so omaseal's `mask_text` can be wired later without a hard dep.
- Tests (`test_dsn.py`, `test_event.py`): valid/invalid DSNs; frame ordering + `in_app`; header redaction; nested secret redaction via injected redactor; event has no PII fields.

### U2 — `helpers/trace_context.py` + `helpers/breadcrumbs.py` (pure)
- `parse_traceparent(str) -> (trace_id, span_id) | None`; `ensure() -> TraceCtx` (adopt inbound or generate); `reset()`; `current()`; module-level `ContextVar`.
- `crumb()` appends `{timestamp,category,message,data?}`; `snapshot()` returns list; `clear()`.
- Tests: round-trip parse/generate, malformed headers ignored, contextvar isolation between two contexts, ring buffer maxlen, crumb never stores a passed `value`/`secret` key.

### U3 — `helpers/client.py` (transport)
- `Client(dsn, *, timeout, release, environment)`; `send_event(event) -> str|None`: builds `X-Sentry-Auth` (`sentry_version=7`, `sentry_key`, `sentry_client=a0-plugin-glitchtip/0.1`), POSTs JSON to `{base}/api/{project_id}/store/`; any failure → log warning + return None. **Never raises.**
- Tests (`test_client.py`): against a `http.server` fixture on a free localhost port (offline — loopback only, no external): POST path/auth header/body shape; non-2xx → None, no raise; timeout path via unreachable port; event_id from response JSON surfaced.

### U4 — `helpers/runtime.py` (facade)
- `configure(cfg: Mapping)`: env overrides (`GLITCHTIP_DSN`, `GLITCHTIP_ENV`, `GLITCHTIP_RELEASE`) over cfg; builds client or leaves inactive; idempotent.
- `capture_exception(exc, tags=None)` / `capture_message(msg, level, tags=None)` / `is_active()` / `reset()` (test hook). All never-raise.
- Tests (`test_capture.py`): inactive when no DSN; inactive short-circuits before any socket work; capture includes trace tags; repeated configure doesn't double-patch.

### U5 — Extensions (the a0 surface)
- `_20_glitchtip_init.py` (`startup_migration`): `from usr.plugins.glitchtip.helpers import runtime`; read config via `helpers.plugins.get_plugin_config("glitchtip")` (fall back to `default_config.yaml` parse); `runtime.configure(...)`; when `api_error_events`, patch `helpers.api.ApiHandler.handle_request` once (idempotent, `getattr`-marked `_glitchtip_wrapped`).
- `_85_glitchtip_capture.py` ×2: `execute(self, data={}, **kw)` — return early when `not self.agent`, `data["exception"]` falsy, or isinstance `HandledException`/`CancelledError`/`InterventionException`/`RepairableException`; else `runtime.capture_exception(exc, tags={location: data["args"][0] if present, agent_name, context.id, trace_id})`.
- `_30_glitchtip_breadcrumb.py` (`tool_execute_after`): crumb `{"tool": <name>, "ok": bool(response and not error)}` — name/status only, no args or output text.
- Tests (`test_capture.py` continued): stub `Extension`/exception classes; feed `data["exception"]` variants → assert capture/skip matrix; verify crumb contents exclude args/output; verify patch wrapper emits event on a stubbed 500-returning handler and re-raises propagating ones.

### U6 — `api/glitchtip_test.py` (ops test event)
- `class GlitchtipTest(helpers.api.ApiHandler)`: `process(input, request)` → `runtime.capture_message("GlitchTip test event from a0-plugin-glitchtip", level="info")`; returns `{ok: bool, event_id}` — `{ok: false, error: "not configured"}` when inactive.
- Tests (`test_api.py`): active/inactive response shapes via stubbed ApiHandler/Request.

### U7 — Packaging + docs + CI
- `plugin.yaml` (`name: glitchtip`, `settings_sections: [external]`), `default_config.yaml`, `hooks.py`, LICENSE (MIT — credit agent0ai + Khan), README (install via `usr/plugins/glitchtip`, GlitchTip setup, trace-ID correlation walkthrough, limitations: API events are message-level, no performance tracing), AGENTS.md (contracts: never-raise rule, `_85_` ordering rationale, zero-dep rationale, offline-tests rule), `.github/workflows/ci.yml` (copy omaseal's — `pip install pytest` only; drop `cryptography`), README badge optional. Version `0.1.0`.
- No new test expectations; verify `pytest tests/ -q` green and `plugin.yaml` parses.

## Risks / open items

- **GlitchTip store-endpoint shape** — assumption documented in KTD-1; U3's fixture encodes the Sentry store contract (`X-Sentry-Auth` + event JSON); if a live GlitchTip rejects it, switch the transport path to `/envelope/` framing without touching the rest. Flagged for manual smoke against the operator's GlitchTip post-merge.
- **`handle_request` patch fragility** — upstream could change the method; patch is additive (post-inspection) and degrades to "API events stop, agent-loop events keep working." Documented in AGENTS.md.
- **Trace-ID ↔ Langfuse correlation** is by-convention (same ID format, both searchable) — no automatic linking until/unless a shared context package exists; README states this plainly.
- **Two `handle_exception` classes** — both covered by U5's two extension files.

## Acceptance (from Khan#193)

- [ ] Installs on stock upstream a0 via `usr/plugins/glitchtip` (Plugin Hub path)
- [ ] Unhandled tool/API exception → GlitchTip event tagged with OTel-format trace ID
- [ ] README documents Langfuse cross-correlation
