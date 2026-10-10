# Landscape: the Agent Zero plugin ecosystem and comparable agent-plugin systems

Date: 2026-10-10. Shared by `a0-plugin-durable`, `a0-plugin-glitchtip`, `a0-plugin-notion`, `a0-plugin-device-sync`, `a0-plugin-jev-compact`. Each repo's per-plugin section follows this shared text. Research used web search only; no paid model calls. Search results were mostly third-party mirrors, so every claim is tagged with how solid its source is. Where a source disagreed or was thin, that is said.

## 1. How Agent Zero plugins work (the host contract)

- Agent Zero looks for plugins in `usr/plugins/<name>/` (user) and `plugins/<name>/` (core). A folder is a plugin when it has a `plugin.yaml` at its root. Fields include `name`, `title`, `description`, `version`, `settings_sections` and per-project/per-agent flags. Valid `settings_sections` values reported: agent, external, mcp, developer, backup. Source: third-party mirrors of Agent Zero's own skill docs ([tessl a0-create-plugin](https://tessl.io/registry/skills/github/agent0ai/agent-zero/a0-create-plugin), [openskillindex a0-create-plugin](https://openskillindex.com/skills/agent0ai-agent-zero-a0-create-plugin)). Confidence: medium. The official repo was not read directly.
- Community plugins live in their own GitHub repo and are listed by a pull request to the `a0-plugins` index repo. The index is a generated `index.json` keyed by plugin name (title, description, github, tags, thumbnail). A `LICENSE` at the repo root is required, and CI requires `name` to match `^[a-z0-9_]+$`. Source: [openskillindex a0-contribute-plugin](https://openskillindex.com/skills/agent0ai-agent-zero-a0-contribute-plugin) and the mirrors above. Confidence: medium.
- Implication for this family: the `a0-plugins` index is the only discovery channel, and its card is a title, a description, tags and a thumbnail. A good thumbnail (our social card or mark) and a plain description do more for discovery than any feature. Our own plugins carry a `LICENSE` already; `a0-plugin-jev-compact` is the only one with `author`, `license`, `homepage` and `min_a0_version` in its manifest.

## 2. Comparable plugin systems

| System | Unit of extension | Distribution | What it does better than an a0 plugin | What it does worse |
|---|---|---|---|---|
| Claude Code plugins | Directory with `.claude-plugin/plugin.json`; bundles slash commands, subagents, hooks, skills, MCP servers ([guide](https://www.morphllm.com/claude-code-marketplace), third-party) | A git repo with `.claude-plugin/marketplace.json`; `/plugin marketplace add owner/repo`, `/plugin install` | Install is one command, from any git repo. Components are declarative (no Python to run). | Not a Python runtime: plugins cannot hold long-lived server code except via MCP. |
| Model Context Protocol (MCP) servers | A process speaking MCP over stdio or HTTP | Registries and per-client config | Client-neutral: one server works in many agents. Notion ships an official hosted one ([Notion docs](https://developers.notion.com/docs/hosting-open-source-mcp), [ToolHive guide](https://docs.stacklok.com/toolhive/guides-mcp/notion-remote)). | Every server is a separate process with its own auth and lifecycle. |
| Agent Zero plugins | Directory with `plugin.yaml`, `api/`, `extensions/`, `helpers/`, optional webui | One GitHub repo each + PR to `a0-plugins` index | Can hook the agent loop in-process (extensions), add API routes and settings panels, and ship an MCP server inside. | Discovery is one index; no versioned install command was found in the sources; hosts are Python-only. |

What users expect from a plugin in any of these systems: install in one step, a visible settings surface, a no-op default when disabled, a clear failure message instead of a crash at host startup, and a licence file.

## 3. Cross-cutting findings

1. **MCP is the neutral layer.** Where a capability already exists as an MCP server, a plugin that re-implements it competes with the vendor. A plugin earns its place by doing what MCP cannot: hooking the agent loop or host lifecycle in-process.
2. **Zero-dependency is a real differentiator in a host plugin.** All five plugins here are stdlib-only or lazy-import optional deps, so they cannot break a0 startup. That is a design choice worth keeping and stating in each README.
3. **Disabled-by-default and inert-when-off** is the convention that makes a plugin safe to install. Keep it.
4. **Discovery needs a card.** The `a0-plugins` index shows title, description, tags, thumbnail. Per-plugin tags and a thumbnail are cheap.

## 4. Adjacent domains (used by the per-plugin sections)

- **Durable execution** (for durable): Temporal records an event history and replays deterministic workflow code; Inngest checkpoints each `step.run()` and charges per run and per step, with a BSL self-host option; DBOS is MIT, database-native, TypeScript-centric; Restate is a single binary with sub-50ms latency claims from vendor pieces; Hatchet, Trigger.dev and LittleHorse also position as agent orchestrators. Sources are vendor-authored and flagged as directional by the search: [ZenML on Inngest alternatives](https://www.zenml.io/blog/inngest-alternatives), [Diagrid FAQ](https://www.diagrid.io/faq/alternatives-dbos-inngest/what-are-the-underappreciated-integration-costs-when-self-building-a-durable-execution-layer-on-temporal-c), [Spheron comparison](https://www.spheron.network/blog/ai-agent-workflow-orchestration-temporal-inngest-restate-gpu-cloud/), [noqta](https://www.noqta.tn/blog/durable-execution-ai-agents-inngest-trigger-temporal-2026).
- **Error tracking** (for glitchtip): GlitchTip accepts Sentry SDKs by changing one DSN string, self-hosts on roughly three services (app, Postgres, Valkey/Redis), and added incremental OpenTelemetry support and span views in 6.2, with an MCP server for AI-assisted debugging ([GlitchTip 6.2 release](https://glitchtip.com/blog/2026-06-22-glitchtip-6-2-released), [SDK docs](https://glitchtip.com/sdkdocs/all-sdks), [Sentry alternatives roundup](https://oneuptime.com/blog/post/2026-03-31-10-best-sentry-alternatives/markdown)). A competitor's roundup says it focuses on error and uptime, not full-stack observability. Langfuse trace-id correlation was not found in any source.
- **Notion access** (for notion): Notion runs an official hosted MCP server at `mcp.notion.com/mcp` (tools such as `notion-search`, `notion-fetch`, `notion-create-pages`); the open-source `makenotion/notion-mcp-server` is described as lower priority and possibly deprecated by two third-party sources. Sources disagree on whether the hosted server is OAuth-only. Verify on Notion's docs before acting: [StackOne deep dive](https://stackone.com/blog/notion-mcp-deep-dive), [ToolHive](https://docs.stacklok.com/toolhive/guides-mcp/notion-remote), [x-cmd](https://x-cmd.com/install/notion-mcp-server).
- **Device sync** (for device-sync): Syncthing is continuous two-way folder sync that needs both devices online and a daemon; Taildrop is ad hoc file transfer over a tailnet, not sync; rsync is one-way and has no memory between runs; Tailscale carries any of them. Sources are community posts and low quality: [Syncthing vs Tailscale thread](https://jisaku.com/glossary/network-nas-sync-tailscale-syncthing-remote), [rsync alternatives](https://alternativeto.net/software/rsync), [Taildrop forum](https://forum.tailscale.com/t/taildrop-alpha-futures-speculation/689).
- **Context compaction** (for jev-compact): Claude Code compacts manually with `/compact` and automatically near full context (reported near 95% of a 200K window); one critique says that timing degrades context first. A 2026 guide groups methods as LLM summarisation, opaque compression, and verbatim compaction (drop low-value lines, keep the rest word for word) and warns that 90%+ compression forces rewriting and hallucination risk. Mem0 markets a memory compression engine (vendor claim of up to 80% fewer prompt tokens, treat as marketing). Letta (MemGPT) pages data in and out like virtual memory. LLMLingua is token pruning. Sources: [morphllm guide](https://www.morphllm.com/context-compression), [Claude Code compaction explainer](https://techie007.substack.com/p/how-memory-compaction-works-in-agents), [Mem0 guide](https://guide.mem0.ai/faq/tools-reduce-context-llm-calls), [Self-Compacting Language Model Agents](https://arxiv.org/pdf/2606.23525).

## 5. What is unique about this family

- In-process agent-loop hooks with a stdlib-only footprint, which neither MCP servers nor marketplace plugins offer.
- A shared engineering standard across five repos: opt-in, inert when disabled, secrets never in config, `{ok, error}` API envelope, offline tests.
- Honest scale: these are single-host tools for one operator's Agent Zero boxes. None claims multi-tenant or multi-region.

## 6. Open risks to the whole family

- Host-contract drift: every claim in section 1 comes from third-party mirrors. Re-verify against the official `agent0ai/agent-zero` repo before the next release of any plugin.
- Five repos, five CI files and five near-identical `helpers/config.py`/`runtime.py` pairs. A shared helper package is the obvious simplification, but a0 plugins are standalone directories, so sharing means a vendored copy or a 6th plugin. See each ROADMAP.

## Plugin section: glitchtip

Scope: `a0-plugin-glitchtip` (v0.1.0) reports unhandled agent-loop exceptions and API 500s to a Sentry-compatible endpoint (GlitchTip) using a stdlib `urllib` client and the legacy Sentry store endpoint, tagged with a W3C/OTel trace id. Repo has no open issues or PRs as of this date. Source quality: mostly vendor pages and search summaries; thin where noted.

### Alternatives and comparable projects

1. **sentry-sdk (official Python SDK) pointed at a GlitchTip DSN.** GlitchTip documents that Sentry SDKs work by setting the DSN ([GlitchTip SDK docs](https://glitchtip.com/sdkdocs/all-sdks); that page does not list endpoints or Python specifics). Better: maintained by Sentry, rich integrations (the Python SDK has OpenAI/LangChain/OpenAI Agents integrations, [Sentry docs](https://docs.sentry.io/platforms/python/agent-tracing/openai-agents/)), envelope transport, breadcrumbs, local variables. Worse for this host: it is not in Agent Zero's requirements (per the repo's own plan and AGENTS.md, not independently verified here), and an agent-loop exception hook still has to be written. Note: Sentry's Python SDK removed use of the legacy `/store` endpoint and sends envelopes ([sentry-python PR 2656](https://redirect.github.com/getsentry/sentry-python/pull/2656), [issue 2662](https://github.com/getsentry/sentry-python/issues/2662)). Whether GlitchTip still accepts `/store` long term is not stated in any source I found; this plugin depends on it.
2. **Bugsink.** Self-hosted, Sentry-SDK-compatible, error tracking only, stack traces with local variables, one small Django app ([vendor site](https://bugsink.com/); sources disagree on SQLite vs PostgreSQL, and one review calls the licence source-available, not OSI open source). Better: lighter than Sentry, local variables. Worse: vendor-authored evidence only, different licence posture from GlitchTip. Relevance: the plugin's DSN and store call are generic Sentry protocol, so it may work against Bugsink too; that is untested here.
3. **Self-hosted Sentry.** Full product but heavy: one roundup lists Kafka, Redis, PostgreSQL, ClickHouse, Snuba and about 8 GB RAM minimum ([OneUptime roundup](https://oneuptime.com/blog/post/2026-03-12-10-best-sentry-alternatives-2026/markdown), a competitor's post). Better: tracing, replay, mature AI agent monitoring. Worse: operational weight. Same store/envelope question does not arise (Sentry accepts envelopes).
4. **Langfuse (tracing) with a shared trace id.** Langfuse's own FAQ describes sharing or isolating the OpenTelemetry TracerProvider when Sentry is also present, and notes OTel SDKs use random 32-hex trace ids and let you supply your own ([Langfuse FAQ](https://langfuse.com/faq/all/existing-sentry-setup.md), [Langfuse trace-id docs snapshot](https://python-sdk-v2.docs-snapshot.langfuse.com/docs/observability/features/trace-ids-and-distributed-tracing/)). Better: LLM-specific spans, prompts, cost. Worse: it is tracing, not error grouping or alerting. This plugin's "correlation" is by convention: same 32-hex id in a GlitchTip tag and a Langfuse search. No source found describes automatic linking; the community `langfuse_observability` plugin was not independently checked.
5. **Other Sentry-style services.** Highlight.io was reported to be folding into LaunchDarkly with the standalone service shutting down 2026-02-28 ([Bugsink post](https://www.bugsink.com/is-highlight-io-shutting-down), competitor source). Honeybadger is hosted-only per a comparison table ([Better Stack](https://betterstack.com/community/comparisons/honeybadger-alternative/)). SigNoz is OpenTelemetry-based with error tracking as one feature ([OneUptime roundup](https://oneuptime.com/blog/post/2026-03-12-10-best-sentry-alternatives-2026/markdown)). None has an Agent Zero hook.
6. **GlitchTip's own OpenTelemetry and MCP support.** GlitchTip 6.2 added incremental OTel support and an MCP server for AI-assisted debugging ([release post](https://glitchtip.com/blog/2026-06-22-glitchtip-6-2-released)). Relevance: the plugin's trace id is already OTel-format, so it is positioned to benefit; the plugin does not use GlitchTip's OTel ingest.
7. **Other Agent Zero plugins.** Search found no Agent Zero plugin that reports to Sentry, GlitchTip or Langfuse ([search summary of a0-debug-plugin and GlitchTip results](https://tessl.io/registry/skills/github/agent0ai/agent-zero/a0-debug-plugin)). The a0-plugins index itself was not read. Treat "no competitor" as unverified.

### What users expect

Plain DSN-only setup, no startup breakage when the DSN is missing (analogous GlitchTip plugins in other ecosystems disable themselves with a warning, per the same search summary), noise filtering, secret scrubbing, and links from an error to the trace or prompt behind it.

### What is unique here

- Hooks `Agent.handle_exception` and `AgentContext.handle_exception` at the `_85_` slot, so only still-fatal raw exceptions with real tracebacks are reported. A generic SDK would not know this ordering.
- Zero dependencies, never raises, fail-closed redaction, redirect refusal.
- Honest limits: API events are message-level; no performance tracing; events dropped during outages.

### Gaps and risks surfaced by the research

- Store endpoint dependence (item 1). The repo's own plan already names `/envelope/` as the fallback; a live smoke test is still outstanding.
- No automatic Langfuse link; only a shared id.
- Single-source claims about Agent Zero's host contract are inherited from section 1 and unverified.
