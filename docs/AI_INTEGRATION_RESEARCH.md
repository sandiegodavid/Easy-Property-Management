# AI integration research and recommendations

September 24, 2026

## Assessment and scope

OpenAI's desktop agent environment offers a better-documented technical integration path for this local application than the personal Muse Agent capabilities established so far. Muse could offer greater convenience for operators already using it, but comparative adoption and end-to-end workflow reliability remain unverified. More available tools alone do not establish better property-management outcomes.

This note consolidates the assistant comparison and architecture recommendations from the product discussion. It distinguishes documented product support, session reports, and proposed application design. Its provider-neutral recommendations are now adopted by the architecture, governance, assistant-connection, backlog, and UI designs; this does not establish any implemented adapter or measured provider ranking. [Meta Muse research](META_MUSE_RESEARCH.md) contains the detailed Meta findings and proposed file-bridge requirements.

## Separate the integration layers

| Layer | Role in this application | Selection considerations |
| --- | --- | --- |
| Built-in model assistance | App-controlled extraction, summaries, draft preparation, and advisory suggestions. | Task quality, supported inputs, data handling, latency, and cost. |
| Personal assistant integration | Delegated discovery in connected email or other apps, scoped context access, and evidence-backed proposals. | Actual account access, supported local connectivity, scheduling, permissions, reliability, and operator setup. |
| Computer use | Operate interfaces without suitable connectors or visually verify an application workflow. | Available desktop environment, permissions, interactive state, and reliability for the specific task. |

Choosing an assistant does not require choosing the same vendor for built-in model assistance. Model API credentials do not establish access to a personal assistant's connected accounts, memory, or schedules. The Meta report documents this distinction for Muse and Meta Model API; any other integration must establish its own account and capability boundaries.

## ChatGPT desktop, Muse Agent, and local model comparison

“ChatGPT integration” must identify the actual execution environment. The documented desktop Work/Codex capabilities must not be attributed to every ChatGPT chat or to model API access alone.

The local-model column describes Gemma 4 E4B served by a local runtime such as Ollama. It is an inference component, whereas the other columns describe assistant environments. It can complement either assistant; tools, account access, and scheduling require separate application code or an agent runtime.

| Dimension | OpenAI desktop environment | Personal Muse Agent | Local model — Gemma 4 E4B | Assessment for this application |
| --- | --- | --- | --- | --- |
| Structured local integration | Documentation describes local STDIO and Streamable HTTP MCP support in desktop/Codex clients. | Custom local MCP support has not been established; the supplied session reports no MCP client. | App backend can call a local inference API through `AiProviderPort`; model function calling alone is not an MCP client. | Evaluate MCP for the OpenAI assistant and a separate inference adapter for Gemma. |
| Desktop computer use | Documented for desktop Work/Codex in supported regions with the Computer Use plugin and required permissions. | The supplied session reports no Mac screen, mouse, or keyboard control. This is not proof of a universal product limitation. | No desktop-control environment is supplied by model weights; an additional tool-execution layer would be required. | OpenAI offers an additional documented interaction option; local inference does not automatically provide it. |
| File exchange | Any proposed exchange still needs verification in the selected client and permission configuration. | The supplied session reports file read/write/list/rename commands; the proposed bridge remains untested. | The app selects and prepares bounded file content, calls the model, and retains its output through governance. The model has no inherent workspace access. | Validate assistant delivery and receipts; keep local-model file access and persistence app-owned. |
| Property-management workflows | Mail access, scheduling, evidence retention, and unattended operation need scenario testing. | The same requirements remain to be demonstrated against the proposed bridge. | Candidate for extraction, summaries, and drafts over retained evidence; mailbox discovery and scheduling remain separate. | Tool availability does not establish workflow completeness. All options retain operator review. |
| Privacy and offline use | A local desktop client does not by itself establish local inference; verify the selected service's data path. | A Mac client or file bridge does not establish local processing; connected services may require the cloud. | Verified local execution can keep inference payloads on-device and work offline after setup; reject cloud variants and silent remote fallback. | Select by actual execution and disclosure boundaries, not the client location or provider label. |
| Setup and resource costs | Verify required account access, permissions, subscriptions, and limits for the chosen environment. | Verify connected accounts, bridge setup, permissions, and operating limits. | Requires runtime/weights installation and sufficient memory; trades hosted inference charges for hardware use and maintenance. | Compare setup, reliability, and operator correction time alongside service costs. |
| Adoption and convenience | Adoption among this application's target operators has not been established in this research. | Greater personal-assistant adoption has not been established either. | Target-operator adoption is unmeasured; app-integrated assistance could avoid a separate assistant account but adds device setup. | Existing usage may reduce setup friction; measure it rather than assume a market advantage. |

OpenAI product support above is documented in [Model Context Protocol](https://learn.chatgpt.com/docs/extend/mcp) and [Computer Use](https://learn.chatgpt.com/docs/computer-use). Muse claims and their evidence limitations are recorded in the [Meta Muse capability assessment](META_MUSE_RESEARCH.md#personal-agent-capability-assessment). Local-model capabilities, runtime sources, memory considerations, and validation requirements are documented in [Local model feasibility research](LOCAL_MODEL_RESEARCH.md). The comparative assessment is an engineering recommendation, not a benchmark result.

Meta's broader product distribution would not establish active Muse Agent adoption among property operators. The relevant questions are whether an operator already uses the assistant, has connected the necessary accounts, and is willing and able to authorize this integration. No comparative adoption figures were established for this note.

## Recommended shared integration contract

Define one application-owned contract with assistant-specific adapters. Start with one validated adapter; a shared contract does not require shipping every adapter in MVP.

- **Scoped reads:** disclose only authorized properties, units, cases, and supporting context, with record identities and versions.
- **Proposals:** accept structured suggested actions and fields, with source evidence and stable submission identities. External assistants do not write directly to the official database.
- **Validation and review:** enforce permissions, schema, record matching, deduplication, and operator approval in the application. Assistant chat approval cannot substitute for app approval.
- **Receipts:** distinguish proposal admission from operator approval and successful commitment; retain clear rejection and retry outcomes.
- **Health and recovery:** expose verified connection status and recent successful activity. Recover missed delivery and avoid duplicate effects after restarts or retries.
- **Pause and revocation:** enforce access at the application boundary, including queued proposals. Explain that pausing app access cannot retract shared information or necessarily stop an assistant's independent activity.

MCP and files are transport choices beneath this contract. Neither authenticates an assistant or guarantees reliable delivery merely by being present. Preserve the Meta report's requirements for bounded exports, trustworthy attribution, complete file publication, durable receipts, recovery scans, and meaningful heartbeat validation when implementing a file adapter.

The application remains responsible for official records, durable workflow state, deadlines, reminders, approvals, and audit history. Core workflows and manual entry remain available without an assistant.

## Adapter recommendations

**OpenAI desktop Work/Codex:** evaluate MCP for scoped reads and proposal submission. Confirm the exact client, supported transport, authentication, permissions, and lifecycle on the target Mac. Documented MCP support is a starting point, not proof that this application's connector works.

**Muse Agent:** evaluate the proposed file bridge using synthetic data. Treat reported file commands and scheduling as capabilities to demonstrate. Retain manual context export and result import if automated exchange cannot be validated.

**Computer use:** use it where visual interaction provides value, especially when a third-party app lacks a suitable connector. Prefer structured integration for repeated property-record operations; OpenAI's own guidance recommends a dedicated plugin or MCP server when available. Computer use must not become a way around the application's review and authorization rules. [Computer Use guidance](https://learn.chatgpt.com/docs/computer-use)

## Evaluation before choosing a preferred assistant

Run comparable synthetic scenarios for each candidate: discover a relevant message, match it to a property/unit, retain supporting evidence, submit a proposal, review it, and observe the final receipt. Include an HOA shared-repair follow-up so drafting, sent evidence, acknowledgement, and physical repair completion remain distinct.

Compare:

- Setup effort, required accounts/subscriptions, permissions, and operator familiarity.
- Message and attachment access, extraction accuracy, ambiguous matches, and source traceability.
- Discovery delay, handoff delay, scheduling, Mac sleep, app downtime, and restart recovery.
- Duplicate submissions, stale context, revoked access, and failed or partial delivery.
- Data disclosure, usage visibility, and total operating cost.
- Whether operators can understand connection status and complete the workflow when assistance fails.

Select based on demonstrated operator outcomes and maintenance burden. A broader toolset can improve flexibility; an already-connected personal assistant can reduce setup friction. Neither advantage alone settles the decision.

## Local open-weight models

Local model inference is a third deployment option for **built-in assistance**, independent of the operator's connected personal assistant. Google Gemma 4 E4B is the initial candidate evaluated in [Local model feasibility research](LOCAL_MODEL_RESEARCH.md), which records model capabilities, licensing, runtime support, hardware considerations, and primary sources. Published model capability and actual runtime support must be checked separately.

The [model comparison](LOCAL_MODEL_RESEARCH.md#model-candidates) expands the candidate set to Qwen3.5, Ministral 3, and Phi-4-mini. Evaluate a small shortlist through the same governed adapter rather than treating Gemma as a selected default or adding every model to operator Settings.

### Fit with this application

The [architecture](ARCHITECTURE.md#ai-and-connector-architecture) already proposes a provider-neutral `AiProviderPort` beneath governed runs and domain-owned review. A local runtime adapter can fit that boundary without moving authoritative records out of SQLite or giving the model direct database access. This is architectural feasibility, not an implemented integration. The revised design permits registered hosted and local model connections independently of assistant connections.

Local inference does not supply mailbox authorization, message discovery, schedules, or personal-assistant memory. An external assistant or manual import still provides inbound evidence under the current product direction. A local model could then process authorized evidence already retained by the app.

| Workflow | Recommended local-model role | Boundary or tradeoff |
| --- | --- | --- |
| Short maintenance message or operator note | Propose summary, category, reporter, and explicit facts with source references. | Ambiguous property/unit matches require operator selection; missing facts remain missing. |
| HOA follow-up or owner update | Draft from a bounded case timeline, outstanding request, and known recipient context. | A draft is not a sent message, acknowledgement, or completed repair. |
| Possible duplicate issues | Compare a small set retrieved by deterministic property/date/text filters. | Do not ask the model to search the whole portfolio or merge records automatically. |
| Lease/document extraction | Evaluate selected passages and compare proposed values with cited source text. | Long documents, scans, tables, amendments, and cross-references need a separate quality gate; PDF parsing/OCR and model inference are distinct steps. |
| Voice notes or photos | Evaluate only after the exact runtime's modality support is proven. | Text-model success does not validate audio transcription, image interpretation, or missing attachment handling. |
| Money, deadlines, and legal process | Summarize already verified records or draft an explanation. | Calculations, due dates, permissions, and lifecycle transitions stay deterministic; do not make the model the authority for legal eligibility or emergency detection. |

### Benefits and costs

The main potential benefit is reducing disclosure: eligible tasks can be processed on the operator's machine without sending their payload to a hosted model. Offline inference can also preserve assistance during internet outages after the necessary runtime and weights are installed. This does not make cloud mailbox access offline, and it does not establish that every local runtime configuration is free of telemetry, remote fallbacks, or other network activity.

Local execution avoids a hosted provider's per-request inference charge, but consumes memory, disk space, power, and operator-machine time. Support must cover installation, downloads, model loading, compatible runtime versions, upgrades, and failures. A small model may also cost more operator review time if it misses evidence or produces weaker drafts. Compare total workflow cost and quality, not just token pricing.

Open weights allow choosing and pinning an artifact and running it independently of an inference service. License obligations and runtime licenses still apply. Pinning aids diagnosis and regression testing; it does not promise byte-identical output across machines or runtime changes.

### Proposed implementation and operator experience

Begin with one optional runtime and one pinned model artifact, selected after the feasibility checks in the local-model report. Have the FastAPI backend call it through the adapter; do not let browser code invoke an unrestricted model server. Keep inference outside SQLite write transactions. Bound context and output size, start with one inference at a time, and support timeout/cancellation so model work cannot stall normal record management. These are proposed controls, not claims about current implementation.

Retain the same redaction, minimization, schema validation, source comparison, approval, and audit rules as hosted assistance. Valid JSON is not proof of accurate facts. Record the actual model artifact/version, quantization, runtime/version, prompt/schema versions, source fingerprints, and execution location. Do not label a Gemma-generated result as Meta Muse.

Settings should explain **On this device** versus **Cloud service** separately from **Connected assistant**. For local inference, show readiness, selected model, required download/storage, and a connection test. Keep advanced runtime configuration out of routine record workflows. If the runtime is unavailable or a task exceeds its validated capabilities, preserve manual work and explain the limitation. Never silently send a local-only request to a cloud model; any cloud retry must satisfy explicit disclosure permission and existing governance checks.

Bind the inference service to the intended local interface and constrain access; localhost alone is not authentication against other local processes. Keep model weights and machine-specific runtime configuration outside portable property-workspace backups. Retain provenance in the workspace so restoring it preserves review history without bundling a multi-gigabyte runtime or implying the model is installed on the new machine.

### Adoption gate

Evaluate a small synthetic set first: short messages, missing or conflicting facts, multiple units, repeated HOA follow-ups, duplicate candidates, and embedded instructions in source text. Compare the same bounded inputs against manual review and a hosted candidate. Measure field correctness, unsupported claims, source-reference accuracy, operator corrections, time to first output, total latency, peak memory, cold-start behavior, and performance while ordinary app work continues.

Set task-specific acceptance thresholds before selecting a default. Test unavailable runtime, malformed output, timeout, cancellation, model update, and local-only operation with network access disabled after installation. Long-document and multimodal tasks require their own evaluation rather than inheriting approval from short-text results. No on-device performance or quality benchmark has been performed for this research.

The recommendation is an **optional pilot for bounded text assistance**, followed by expansion only where measured results justify it. It is not a recommendation to replace the personal-assistant bridge or to make local AI a requirement for using the app.

## Design implications and decision status

The adopted design has Settings distinguish **Built-in AI** from **Connected assistant**, with provider-specific setup and capability-aware status. Show only actions the configured adapter has demonstrated. Keep proposals in the same application review flow regardless of their source.

The revised [UI-001 design](UI-001_DESIGN.md), [AI governance design](AI-GOV-001_DESIGN.md), [MCP-001 design](MCP-001_DESIGN.md), and [architecture](ARCHITECTURE.md#ai-and-connector-architecture) now define the implementation contracts. Meta is an option, not an exclusive identity. Local inference remains an optional evaluated pilot; no report or prototype demonstrates production readiness.

MCP is not limited to ChatGPT: documented local clients also include [Claude Desktop](https://support.claude.com/en/articles/10949351-getting-started-with-local-mcp-servers-on-claude-desktop), [Claude Code](https://code.claude.com/docs/en/mcp), and [VS Code](https://code.visualstudio.com/docs/agents/reference/mcp-configuration). Exact application compatibility must be tested. Hosted ChatGPT does not inherit desktop configuration; [Secure MCP Tunnel](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels) is a separately authorized remote path, outside this local MVP's enabled scope.

## Perplexity as another integration option

[Perplexity integration research](PERPLEXITY_INTEGRATION_RESEARCH.md) evaluates public-source Search/Agent APIs, the Mac local MCP client, and the separate Computer delegation surface. The recommended first experiment is bounded public-information research; optional assistant access remains a separate grant. The note records setup, costs, the announced Sonar retirement, and API-versus-consumer privacy distinctions. This is a researched candidate, not an enabled provider or a change to accepted feature scope.
