# Perplexity integration research

September 24, 2026

## Recommendation and scope

For a first property-app feature, use **Search API to retrieve public sources**, with local review and optional existing local-model synthesis. Add **Agent API** only when a hosted, cited research answer materially helps. Suggested first workflow: research a public maintenance product, city permit page, or vendor website and return a source-backed draft for review. This is an architectural recommendation, not a measured comparison.

Do not begin a new Sonar Chat Completions integration. Perplexity staff announced retirement on **September 27, 2026**, and reaffirmed the date September 10. The migration overview still says Sonar remains supported while recommending Agent API for new projects; treat the explicitly dated retirement announcement as the planning constraint and recheck before implementation. [Official announcement](https://community.perplexity.ai/t/sonar-is-moving-to-the-agent-api/5802), [staff clarification](https://community.perplexity.ai/t/sonar-moving-to-agents-api/6061), [migration overview](https://docs.perplexity.ai/docs/agent-api/migrate-from-sonar/overview).

Perplexity is also a documented **Mac local MCP client**, worth testing as an optional connected assistant. Keep this separate from the API: an operator may use Perplexity as their assistant while the app uses a local model or another hosted provider. This report evaluates feasibility; it neither selects a default provider nor changes implementation scope.

The user-supplied [What is Perplexity?](https://www.perplexity.ai/help-center/en/articles/10352155-what-is-perplexity) and [How does Perplexity work?](https://www.perplexity.ai/help-center/en/articles/10352895-how-does-perplexity-work) describe web-grounded conversational research with source citations and multiple underlying models. They establish the product's research focus, not an application integration contract or a guarantee of source correctness. The [homepage](https://www.perplexity.ai/) returned little readable content; the API and connector documentation below supplies the technical evidence.

## Integration paths and expected value

| Direction | Feasibility for this application | Benefit | Main tradeoff |
| --- | --- | --- | --- |
| App → Search API | Strong candidate for a small backend adapter; not tested | Public-source retrieval can support either local or hosted synthesis | Query disclosure, source quality, network dependency, and a new retrieval/evidence contract |
| App → Agent API | Documented hosted generation/research; not tested | Cited synthesis and structured output in one provider workflow | Token/tool costs, cloud state retention, variable research latency |
| Perplexity Mac → app MCP server | Documented client support; app connector still needs implementation and testing | Operator uses a familiar assistant to read scoped records and propose work | Client setup, disclosure, confirmation behavior, and reliable delivery need verification |
| App → Perplexity Computer MCP | Documented delegation surface; defer for this MVP | Multi-step work using the operator's separately connected services | Requires an MCP client, OAuth, durable task/checkpoint handling, and control of external side effects |
| Personal Computer/Comet → app UI | Published desktop/browser capabilities; app workflow untested | Can help when another system lacks a connector | Broad device permissions, UI fragility, and risk of bypassing app review boundaries |

The distinctions above are engineering assessments based on the separately cited product contracts below. In particular, **Perplexity's MCP server exposes Perplexity to clients; Perplexity's local connector consumes this app's MCP server.** Installing one does not configure the other.

For this portfolio's scale, the largest likely incremental value is external research, not replacing local accounting, reminders, or ordinary extraction. Candidate uses include manufacturer documentation, public license/permit sources, and sourced comparisons. Live vendor research would extend ISSUE-AI-004/AI-REC-002 beyond saved provider history; jurisdiction-source discovery would support JUR-001 without deciding legal applicability. Those are future capability designs, not features delivered by adding an API key. Small local models remain useful for private summaries; Perplexity does not eliminate their privacy/offline advantage. No comparative quality or productivity benchmark was performed.

## Built-in API contracts

| API | Published contract | Suitable use here |
| --- | --- | --- |
| Search | `POST https://api.perplexity.ai/search`; ranked source results, not a generated answer | Public-source discovery with application-owned synthesis and evidence display |
| Agent | `POST https://api.perplexity.ai/v1/agent`; `/v1/responses` is an accepted compatibility alias; `input` produces typed `output` items | Hosted research with search, citations, structured results |
| Sonar (legacy) | Current migration example uses `/v1/sonar`; older integrations use chat-completions semantics, `messages` and `choices` | Migration reference only |

Requests authenticate with `Authorization: Bearer` using a Perplexity API key. Official SDKs are Python `perplexityai` and TypeScript `@perplexity-ai/perplexity_ai`; both read `PERPLEXITY_API_KEY`. Raw HTTPS is sufficient, so an SDK is optional. [Search quickstart](https://docs.perplexity.ai/docs/search/quickstart), [Agent quickstart](https://docs.perplexity.ai/docs/agent-api/quickstart), [migration overview](https://docs.perplexity.ai/docs/agent-api/migrate-from-sonar/overview).

Search supports multiple queries, domain allow/deny filters, language and country controls, plus snippet/content budgets. Results include titles, URLs and snippets, with source dates where available. Recommendation: constrain jurisdiction research to the relevant official government domains, retain retrieval time locally, and allow empty results rather than inventing an answer. [Search quickstart](https://docs.perplexity.ai/docs/search/quickstart).

Agent provides presets including `fast`, `low`, `medium`, and `high`, or explicit model/tool configuration. Add `web_search` for web retrieval; do not assume an arbitrary model-only request searched. The web tool accepts domain/date/recency filters and result/token bounds. A `search_results` output item contains result IDs, URLs, titles, snippets, dates and source type. Map those IDs to displayed citations. [Agent quickstart](https://docs.perplexity.ai/docs/agent-api/quickstart), [web-search tool](https://docs.perplexity.ai/docs/agent-api/tools/web-search).

## Structured output and evidence

Agent supports JSON Schema through `response_format: { type: "json_schema", json_schema: { name, schema } }`. Required fields must be listed in the schema's `required` array. Documentation notes possible truncation and an initial schema-preparation delay of roughly 10–30 seconds. Validate the returned JSON in the application before accepting it; handle timeout, incomplete output and missing evidence. [Output control](https://docs.perplexity.ai/docs/agent-api/output-control).

Published preset citation conventions differ: `fast` uses `[1]`, while `low`/`medium`/`high` use `[web:1]`. Preserve source records, not just the answer string. Citation presence is not proof that a statement follows from the page. [Migration citation guide](https://docs.perplexity.ai/docs/agent-api/migrate-from-sonar/how-to).

Suggested application result schema (design proposal): `summary`, `findings[]` with `claim`, `sourceIds`, and optional `effectiveDate`, plus `unknowns[]`. Keep request metadata, retrieval time and source URLs in a research record. Do not turn these drafts directly into ledger changes, tenant decisions, notices or vendor commitments.

## Costs and billing

Published rates checked on the research date:

| Item | Price in USD |
| --- | --- |
| Search API standard | $5 per 1,000 successful requests |
| Search API `search_type: "fast"` | $1 per 1,000 successful requests |
| Agent standard `web_search` | $0.0025 per invocation |
| Agent fast `web_search` | $0.001 per invocation |
| Agent `fetch_url` | $0.0005 per invocation |

Search billing is per successful request, including a multi-query request of up to five queries; successful empty results are billed. Invalid/rate-limited/upstream-failed requests are not. Search has no additional token charge. Agent adds model token charges; multiple tool invocations can occur within one request. Where returned, `usage.cost.total_cost` reports request cost. For example, 100 standard Search requests cost $0.50; that arithmetic is an estimate, not a test. [Pricing](https://docs.perplexity.ai/docs/getting-started/pricing).

API access is pay-as-you-go without a required subscription. Credits are purchased in advance; billing/keys belong to a project. Auto reload is optional, and exhaustion blocks API access until replenished. Do not assume an existing consumer Pro/Max subscription funds API use. [Agent quickstart](https://docs.perplexity.ai/docs/agent-api/quickstart), [projects and billing](https://docs.perplexity.ai/docs/getting-started/projects).

## Privacy: material distinction

Perplexity's general API privacy page explicitly describes zero retention and no training for **Chat Completions API**, with billing metrics retained. It does not establish that all newer APIs inherit that commitment. [Privacy and security](https://docs.perplexity.ai/docs/resources/privacy-security).

Agent documentation explicitly says response/conversation state persists server-side. **`store: false` hides retrieval; it does not disable persistence.** It can still support `previous_response_id`. The documentation advises accounts with a ZDR agreement to consult their account team about stateful features. The reviewed sources do not establish Agent's retention duration or a general Search API zero-retention guarantee. Do not describe either as confirmed zero retention. [Conversation state](https://docs.perplexity.ai/docs/agent-api/conversation-state).

Recommendation for this app: send only public or sufficiently deidentified research prompts initially. Keep tenant identities, payment details, lease documents, maintenance narratives containing personal information, and other private records local. Before a sensitive-data workflow, obtain current product-specific retention/training/subprocessor terms for the selected Agent model or Search service; consumer-app privacy settings are not evidence of API behavior.

## API setup for a later authorized pilot

1. Sign in to the [API console](https://console.perplexity.ai) with the intended account. Open **Project → Settings** and create/select a dedicated development project. [Project setup](https://docs.perplexity.ai/docs/getting-started/projects).
2. Open **Billing**, add the payment method, and purchase the chosen small credit amount through **Buy more credits**. For a capped manual pilot, leave auto reload disabled. Adding a payment method alone does not purchase credits. [Billing instructions](https://docs.perplexity.ai/docs/getting-started/projects).
3. Open [Project → API keys](https://console.perplexity.ai/project/keys), choose **+ Generate API Key**, and name it for this application's development environment. The key is displayed only once. Save it directly in a secret store; never paste it into chat, source code, screenshots, or issue text. [API key management](https://docs.perplexity.ai/docs/admin/api-key-management).
4. Configure the backend environment with the secret under `PERPLEXITY_API_KEY`; keep it out of browser/client bundles, committed files and logs. Use a secret manager or OS credential store to inject the variable when starting the backend. The environment-variable name is official; the injection mechanism is an implementation choice. [API key management](https://docs.perplexity.ai/docs/admin/api-key-management), [Agent authentication](https://docs.perplexity.ai/docs/agent-api/quickstart).
5. Implement a server-side adapter with an explicit feature toggle, request timeout and application budget; retain the current governance rule of explicit retries rather than adding automatic retries. Validate the first request with a generic public query through `/search`, then test Agent separately if needed. Verify HTTP success, schema, working citations, provider-reported usage/cost inspection and graceful missing-key/exhausted-credit handling. These are proposed acceptance checks; none were run in this research.
6. Revoke the development key when the pilot ends or rotate by creating a replacement, updating the application and verifying it before revoking the old key. [Key rotation](https://docs.perplexity.ai/docs/admin/api-key-management).

### Application adapter design implications

Agent generation can fit `AiProviderPort` after a domain registers its research action, output/evidence schema, model/capability limits, and approval effect. Search returns sources rather than a model draft; give it a bounded retrieval port owned by the consuming capability instead of pretending it is generation. This is a proposed extension requiring a design/backlog decision. Apply the same disclosure, redaction, pause, and audit rules to outbound search queries, even when a local model later summarizes results.

Use the backend and OS credential store keyed by workspace/connection. Keep generated search queries generic: equipment model and city/jurisdiction are often sufficient without tenant names, addresses, balances, or narrative histories. Any query containing sensitive context needs its own explicit data-class approval. Retain the exact governed request, selected model/preset and tool configuration, response ID, and evidence provenance. If the service routes models without reporting the final identity, record that uncertainty rather than inventing a model version. Do not use remote conversation continuity as a substitute for the app's explicitly bounded input record.

The current AI-GOV design retains reported tokens but omits costs; do not silently introduce a financial cost field. A future reported-cost record needs its own currency/provenance contract. For the pilot, compare provider-console charges and bounded request counts. Keep tool-call limits and latency budgets distinct from output-token limits, and do not allow Agent-generated function calls to execute arbitrary application operations.


## Perplexity as a connected assistant

### Local MCP is a documented candidate

Perplexity documents local MCP support in its Mac app, using a PerplexityXPC helper to launch a server command. This makes it another candidate consumer of this application's MCP-001 tools, alongside the clients already researched. The documentation establishes a connection mechanism, not successful interoperability with this app or unattended proposal delivery. Local MCP passes selected data to Perplexity; it does not establish local model inference. [Local MCP guide](https://www.perplexity.ai/help-center/en/articles/11502712-local-and-remote-mcps-for-perplexity)

Recommended pilot setup, once the app's MCP implementation exists:

1. Install/sign in to the supported Mac app and confirm the account exposes local connectors.
2. Open account Settings → Connectors and install the requested PerplexityXPC helper.
3. Add a connector with the app's reviewed launcher command; wait for Running, enable it under Sources, and test a harmless read. These steps follow the published guide; labels may vary by app release.
4. Use the app's scoped grant and device-controlled credential bootstrap. Do not put a token in a shared command, provide a general SQLite/filesystem server, or substitute a made-up command for the not-yet-implemented launcher.
5. Prove source submission, proposal admission, app-side approval, and receipt retrieval with synthetic data. Client confirmation to call a tool is not approval of the official property record.

Steps 4–5 are this application's proposed requirements. A Running connector alone does not pass them. Check write-tool discovery and confirmation, schema compatibility, disconnect/restart, duplicate retries, stale evidence, and revocation. Keep the operator in control of final review; the assistant must not click approval controls on the operator's behalf.

### Remote MCP is a different deployment

Perplexity's dedicated remote-connector guide supports HTTPS with Streamable HTTP or SSE and OAuth/API-key authentication. Setup is Account settings → Connectors → Custom connector → Remote, followed by URL, transport/authentication, acknowledgement, and enablement. Organization permissions may restrict this. The guide describes datacenter-origin requests, so a laptop's loopback address is not a remote endpoint. Its older local-MCP article still says remote access is forthcoming; use the dedicated remote guide for that feature and confirm actual account availability. [Remote connector guide](https://www.perplexity.ai/help-center/en/articles/13915507-adding-custom-remote-connectors)

For this application, remote exposure is deferred: it would require an explicitly approved reachable deployment or tunnel, transport authentication, disclosure review, and lifecycle/support work beyond the current local-only MVP. Do not expose the existing local REST API or enable anonymous access. Prefer testing the Mac local connector first.

### Message discovery and Personal Computer

Perplexity documents a Gmail/Calendar connector with inbox querying and permissions that include email composition/sending and calendar edits. Setup occurs in Perplexity Settings → Connectors → Gmail with Calendar → Enable, then Google authorization. This is broader authority than proposal-only property intake. The app's restricted MCP grant cannot narrow Perplexity's independent Google grant. Review that permission set before any real-account pilot; the API key alone grants none of this account access. [Gmail/Calendar connector](https://www.perplexity.ai/help-center/en/articles/12168040-connecting-perplexity-with-gmail-and-google-calendar)

An eventual intake scenario could discover a maintenance email, resolve the property through bounded MCP reads, submit retained evidence and a proposal, and check the app's receipt. That complete workflow, attachment access, durable checkpoints, catch-up, and scheduling with local MCP have not been tested. Do not promise automatic inbox coverage or emergency detection from the existence of a connector.

Personal Computer is an additional desktop automation environment. Its Mac setup guide describes the Perplexity app, Comet for browser tasks, and macOS Accessibility, screen/audio recording, and disk permissions. This is a broader permission surface than a narrow application connector. [Personal Computer setup](https://www.perplexity.ai/personal-computer-setup)

Engineering recommendation: use structured MCP tools for repeated record operations. Evaluate GUI automation only for a specific task lacking a connector, with synthetic data and operator supervision. Do not require the full Personal Computer permission setup merely to call the built-in API or test local MCP. Broad desktop/filesystem permissions can bypass the app's scoped reads, so they cannot be described as equivalent to a restricted assistant grant.

### Assistant privacy differs from API privacy

The consumer help article says AI Data Retention is enabled by default for Free, Pro, and Max; Account settings → Preferences permits opting out of training use. The opt-out applies prospectively and does not eliminate processing needed to operate the service. Enterprise has separate commitments. Review these settings before disclosing property information; do not equate “not used for training,” “local MCP,” and “not stored.” API-specific commitments must be evaluated separately. [Data collection controls](https://www.perplexity.ai/help-center/en/articles/11564572-data-collection-at-perplexity)

## Calling Perplexity from an MCP client

There are two different Perplexity-hosted tool surfaces:

- **API MCP** wraps Search and Agent research tools for an MCP client. It offers remote and local deployment options backed by an API key. It does not give Perplexity access to the property workspace or confer the consumer assistant's account connections. For the app's first research adapter, direct HTTPS avoids adding an MCP client solely for those API calls. [API MCP documentation](https://docs.perplexity.ai/docs/getting-started/integrations/mcp-server), [official implementation](https://github.com/perplexityai/modelcontextprotocol)
- **Computer MCP** delegates multi-step work to Perplexity Computer at `https://www.perplexity.ai/rest/computer/mcp`, using Perplexity-account OAuth and Computer credits rather than an API key. The documented flow calls `call_perplexity_computer`, retains `thread_id`, and handles questions, authentication, and approve/deny checkpoints. A timeout can leave the remote task running. [Computer MCP documentation](https://docs.perplexity.ai/docs/getting-started/integrations/computer-mcp-server)

A future Computer pilot would configure that endpoint in an OAuth-capable MCP client, authorize a dedicated test account, and start with public research. The application would need persisted task identity, recovery, progress, explicit human responses, and a policy that denies external sends/payments rather than automatically forwarding approval. These are application design requirements, not features provided by the current synchronous AI-GOV coordinator. Prompt instructions alone cannot establish a read-only service boundary. Defer this route until its tool permissions and side-effect controls can be verified; the direct Search API pilot needs much less infrastructure.

## Operator experience and application-specific evaluation

This is a proposed fit with [AI-GOV-001](AI-GOV-001_DESIGN.md), [MCP-001](MCP-001_DESIGN.md), and [UI-001 D46](UI-001_DESIGN.md#d46-choose-built-in-ai-and-connected-assistants-independently), not a change to their accepted delivery scope.

- **Built-in AI:** a registered Perplexity cloud connection for eligible research actions, with its own API credential, data disclosure, test status, and limits. A local model may remain the default for private extraction; explicitly selected web search still sends its query to the cloud.
- **Connected assistants:** a separate “Perplexity for Mac · Local MCP” connection with an app grant, capability-test result, last activity, pause/revoke, and proposal counts. No API credential is implied. Show a schedule only after a real scheduled workflow is verified.
- **Research review:** show source links, publisher, retrieval time, the claim each source supports, conflicting evidence, and the distinction between web findings and official property facts. Retain bounded supporting excerpts where permitted rather than relying on a chat link alone. A search result is not a verified contractor credential or a binding interpretation of a lease/HOA rule.

For the shared water-regulator example, the local case timeline remains the authority for HOA correspondence, attempts, commitments, and next follow-up. Perplexity can help find public manufacturer guidance or the association's published contact route. Private responsibility depends on the applicable retained documents and reviewed facts, not a general web answer. Preparing a draft, sending it, receiving acknowledgement, and verifying replacement remain separate outcomes.

Before enabling either route, compare a small synthetic set against manual work and the existing model candidates: equipment/manual lookup, public contractor/license sources, a conflicting outdated policy page, ambiguous property matches, and repeated HOA follow-ups. Measure source correctness and freshness, unsupported claims, disclosure, operator correction time, latency, and actual provider charges. Test malformed citations/output, missing sources, rate limits, timeout, pause, revoked grants, and duplicate submissions. Domain/legal research stays advisory until the operator verifies the underlying authoritative source and applicable context.

No account was connected, API key created, paid request made, app installed, or live integration tested for this research. Published features and setup paths are feasibility evidence; quality, cost at this workload, and end-to-end reliability remain to be measured.
