# Plan: a0-plugin-glitchtip — program roadmap (2026-10-10)

**Type:** program-level roadmap. Docs only; no application code changes in the PR that adds this file.
**Authoring note:** written by hand in the shape of `2026-10-06-001-feat-glitchtip-plugin-plan.md`; the `compound-engineering:ce-plan` skill was invoked with `mode:pipeline confirm:auto` but its multi-reference workflow was not run to completion.
**Evidence base:** `docs/research/2026-10-10-landscape.md`, repo state at `origin/main` (v0.1.0, no open issues or PRs, CI = `pytest tests/ -q`).

## Problem frame

v0.1.0 is feature-complete against Khan#193 but has never been run against a live GlitchTip. Its transport posts to the legacy Sentry store endpoint, which official Sentry SDKs have dropped. The next work is to prove it, harden the one risky dependency, make it discoverable, and avoid growing it.

## Now / Next / Later

| Horizon | Unit | Title | Difficulty |
|---|---|---|---|
| Now | U1 | Live GlitchTip smoke test (store endpoint) | easy |
| Now | U2 | Envelope transport fallback | medium |
| Next | U3 | Manifest metadata and a0-plugins index listing | easy |
| Next | U4 | Collapse the two `_85_` extensions onto one shared body | easy |
| Later | U5 | Settings panel status chip + screenshot | medium |
| Later | U6 | Automatic Langfuse link on events | hard |

## Units

### U1 — Live GlitchTip smoke test
- **Status:** not started. **Evidence:** README "Known limitations" says only verified against `POST /api/<id>/store/`; the tests use a loopback `http.server` fixture only (`tests/test_client.py`).
- **Goal:** run a throwaway self-hosted GlitchTip, call `POST /api/plugins/glitchtip/glitchtip_test`, trigger one agent-loop exception and one API 500, confirm the three events and their `trace_id` tag appear. Record the GlitchTip version tested in README.
- **Dependencies:** none. **Verification:** event ids visible in GlitchTip; result noted in README and AGENTS.md.
- **Difficulty:** easy. A docker-compose GlitchTip and three manual calls.
- **Feasibility:** needs a GlitchTip instance and a running a0 (operator-side, no paid calls). Blocker: if the store endpoint is rejected, U2 becomes urgent.
- **Simpler alternative:** none smaller; this is the cheapest possible proof. Skipping it is the real risk.

### U2 — Envelope transport fallback
- **Status:** not started. **Evidence:** the 2026-10-06 plan names `/envelope/` as the fallback; Sentry's Python SDK removed store usage ([sentry-python PR 2656](https://redirect.github.com/getsentry/sentry-python/pull/2656)); no source states whether GlitchTip will keep accepting store.
- **Goal:** in `helpers/client.py`, add an envelope body framing (`POST {base}/api/{project}/envelope/`, header line + item header + event JSON) behind a config switch or automatic fallback on 404/410; keep redirects refused and never-raise behaviour.
- **Dependencies:** U1 (to know which endpoint real GlitchTip accepts). **Verification:** new offline `tests/test_client.py` cases against the loopback fixture; live check repeated from U1.
- **Difficulty:** medium. Small code, but the envelope format and GlitchTip's acceptance must be verified, and a new config key means the three-way sync (`helpers/config.py`, `default_config.yaml`, README table).
- **Feasibility:** envelope spec is public Sentry protocol; GlitchTip support for envelopes is not confirmed in the sources found here. Could block if GlitchTip only partly implements it.
- **Simpler alternative:** do not add a switch: if U1 shows store works on current GlitchTip, document the dependency and defer U2. If envelope works better, replace store outright and delete the store path in `helpers/client.py` rather than carrying both.

### U3 — Manifest metadata and a0-plugins index listing
- **Status:** not started. **Evidence:** `plugin.yaml` has no `author`, `license`, `homepage`, `min_a0_version` (`a0-plugin-jev-compact` does); discovery is via the `a0-plugins` index (landscape section 1, medium confidence).
- **Goal:** add the metadata, re-verify the index contract against the official repo, open the listing PR with tags and the social card as thumbnail.
- **Dependencies:** U1 (list only after a live proof). **Verification:** `plugin.yaml` parses; index CI (`name` matches `^[a-z0-9_]+$`) passes.
- **Difficulty:** easy. Metadata plus a PR to another repo.
- **Feasibility:** index rules came from third-party mirrors; re-read the official `a0-plugins` contribution docs first. The `min_a0_version` value needs a real check.
- **Simpler alternative:** skip the index and rely on direct `git clone` install; costs discoverability only.

### U4 — Collapse the two `_85_` extensions
- **Status:** not started. **Evidence:** `extensions/python/_functions/agent/Agent/handle_exception/end/_85_glitchtip_capture.py` (27 lines) and `.../AgentContext/.../_85_glitchtip_capture.py` (29 lines) differ only by the `surface=` string and docstring; the shared body is already `runtime.report_loop_exception`.
- **Goal:** make each file a three-line subclass or import of one shared extension class (for example in `helpers/runtime.py`), keeping both file paths because a0 discovers hooks by path.
- **Dependencies:** none. **Verification:** `python3 -m pytest tests/ -q` green, including the capture/skip matrix in `tests/test_capture.py`.
- **Difficulty:** easy. Behaviour-preserving, but the two docstrings carry ordering notes that must be kept.
- **Feasibility:** a0 loads extensions by file path, so the two files cannot be removed, only thinned.
- **Simpler alternative:** leave as is; the duplication is 25 lines and documents two different ordering contexts. Only do this if a third hook site appears.

### U5 — Settings panel status chip and screenshot
- **Status:** not started. **Evidence:** `plugin.yaml` declares only `settings_sections: [external]`; README has a TODO instead of a screenshot; DESIGN.md defines `LIVE / IDLE / FAILED` chips but no UI exposes them.
- **Goal:** capture a real settings-panel screenshot from a running a0; optionally extend `api/glitchtip_test.py` or add a status endpoint returning active / cooldown state (`helpers/runtime.py` already tracks both).
- **Dependencies:** U1 (a running a0 with GlitchTip). **Verification:** screenshot committed; any new endpoint has offline tests in `tests/test_api.py`.
- **Difficulty:** medium. A new endpoint is small, but panel rendering inside a0 is unverified here.
- **Feasibility:** depends on a0's `external` settings section rendering; custom UI is not documented in the sources read.
- **Simpler alternative:** screenshot only, no new endpoint. Reuse the existing test endpoint's `{ok}` result as the status signal.

### U6 — Automatic Langfuse link on events
- **Status:** not started. **Evidence:** correlation today is a shared 32-hex `trace_id` tag only (README "Correlating with Langfuse"); no source found describes automatic Sentry-to-Langfuse linking, and Langfuse's own FAQ warns about shared tracer providers ([FAQ](https://langfuse.com/faq/all/existing-sentry-setup.md)).
- **Goal:** attach a Langfuse trace URL as an event tag when a Langfuse host is configured.
- **Dependencies:** U1; a `langfuse_host` config key. **Verification:** offline test asserts the tag; manual click-through.
- **Difficulty:** hard. Needs a stable trace-id handshake with the community Langfuse plugin, which this repo does not control.
- **Feasibility:** blocked on that plugin actually adopting the same trace id; unverified.
- **Simpler alternative:** document a Langfuse search-by-id URL pattern in README; no code.

## Merge / retire assessment

Verdict: no, keep standalone. The best simpler alternatives are (a) a vendored `sentry_sdk` or (b) folding into a sibling; neither fits. Merging into `durable`, `notion`, `device-sync` or `jev-compact` would couple an error reporter to unrelated domains and force their users to install an exception hook they did not ask for, and the landscape notes the family shares only conventions, not domain. Retiring in favour of the official Sentry SDK is only viable if Agent Zero gains a dependency mechanism (AGENTS.md records it has none), and even then the `_85_` hook and ApiHandler patch would still be needed. The honest simplification is internal: do U1 first, then either keep store as is or replace it with envelope (U2), and optionally thin the two `_85_` files (U4). The sensible family-level move is the shared `helpers/config.py`/`runtime.py` pattern noted in landscape section 6, which is out of scope here.

## Risks

- Store endpoint deprecation (U1/U2) is the single largest risk and is unverified for GlitchTip.
- Host-contract claims in the landscape come from third-party mirrors; recheck before U3.
