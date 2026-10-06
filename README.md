# a0-plugin-glitchtip

GlitchTip error tracking for [Agent Zero](https://github.com/agent0ai/agent-zero)
— self-hosted, Sentry-compatible, **zero dependencies** (stdlib `urllib` only).

Unhandled agent-loop exceptions and API 500s become GlitchTip events tagged
with a W3C `traceparent`/OTel-compatible **trace ID**, so you can correlate
them with Langfuse traces (e.g. the community `langfuse_observability`
plugin).

Extracted from [Khan](https://github.com/duketopceo/Khan) — issue
[Khan#193](https://github.com/duketopceo/Khan/issues/193).

## Install

```bash
# into a running a0 checkout
git clone https://github.com/duketopceo/a0-plugin-glitchtip \
  <a0>/usr/plugins/glitchtip
```

Enable the plugin in the WebUI plugin list, then configure the DSN.

## Configure

Set the DSN via environment (preferred — keeps it out of config files):

```bash
export GLITCHTIP_DSN="https://<public_key>@<your-glitchtip-host>/<project_id>"
```

or the `dsn` field in plugin settings (`external` section). Optional:

| Setting | Env | Default |
|---|---|---|
| `enabled` | — | `true` |
| `dsn` | `GLITCHTIP_DSN` | — |
| `environment` | `GLITCHTIP_ENV` | `local` |
| `release` | `GLITCHTIP_RELEASE` | — |
| `api_error_events` | — | `true` |
| `breadcrumbs_max` | — | `50` |
| `send_timeout_s` | — | `5` |

## What gets reported

| Source | How | Event |
|---|---|---|
| Tool / agent-loop exceptions | `_85_` extensions on `Agent.handle_exception` and `AgentContext.handle_exception` — after core clears repairable/intervention exceptions, before `_90_` wraps the rest as handled | Real exception event **with stack trace** |
| API handler failures | startup-time wrapper on `ApiHandler.handle_request` observes ≥500 responses (a0 swallows handler exceptions into a 500 body — no stack survives) | Message-level event with path + method |
| Test event | `POST /api/plugins/glitchtip/glitchtip_test` | `{ok, event_id}` |

Every event carries `tags.trace_id` and `contexts.trace` — an OTel-format
trace ID adopted from the inbound `traceparent` header when present, else
generated per request.

## Correlating with Langfuse

GlitchTip doesn't link to Langfuse automatically — the correlation is the
shared trace ID:

1. In GlitchTip, open the event → its `trace_id` tag.
2. In Langfuse, search traces for that ID (Langfuse/OTel use the same
   32-hex format). Inbound requests that already carry a `traceparent`
   header keep that trace ID end-to-end, so gateway/front-door traces join
   up automatically.

## Known limitations

- API events are **message-level** (no stack): a0's `ApiHandler` formats
  exceptions into the 500 response before any hook can see the object.
  Agent-loop events carry full stacks.
- No performance/transaction tracing — GlitchTip is error-tracking only.
- Breadcrumbs record tool names + statuses only, never args or output.

## Test

```bash
python -m pytest tests/ -q   # offline; loopback http.server fixture only
```
