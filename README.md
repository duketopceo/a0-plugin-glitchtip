# a0-plugin-glitchtip

An [Agent Zero](https://github.com/agent0ai/agent-zero) plugin that reports
unhandled tool/API exceptions to a self-hosted [GlitchTip](https://glitchtip.com)
instance and tags events with an OTel-compatible trace ID, so they correlate
with Langfuse traces (e.g. the community `langfuse_observability` plugin).

Extracted from [Khan](https://github.com/duketopceo/Khan) (`helpers/glitchtip.py`,
`helpers/observability.py`, `helpers/request_id.py`) as part of milestone 8 —
see [duketopceo/Khan#193](https://github.com/duketopceo/Khan/issues/193).

**Status:** scaffold — implementation in progress.
