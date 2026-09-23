# Meta Muse integration research and design proposals

Research date: September 23, 2026. These are proposals, not amendments to the confirmed implementation contracts.

## Verified product distinctions

- Meta's Muse personal agent works across connected apps and runs on a dedicated cloud VM. Its product page describes permission controls, background work, and approval of sensitive actions. The Mac download page describes access to local files and apps with permission. A Mac client therefore does not establish local-only inference or data processing. Sources: [Muse](https://ai.meta.com/muse/), [Mac download](https://ai.meta.com/muse/download/), [Meta introduction](https://about.fb.com/news/2026/09/introducing-muse-personal-ai-agent/).
- Meta Model API is a separate developer integration with bearer-token authentication and Responses, Chat Completions, and Messages protocols. Its model catalog includes Muse Spark. Sources: [API protocols](https://dev.meta.ai/docs/protocols), [models](https://dev.meta.ai/docs/models).
- Muse Code is a coding agent with its own documented configuration and MCP settings. Its capabilities do not establish equivalent support in the personal desktop agent. Source: [Muse Code configuration](https://dev.meta.ai/docs/muse-code/configuration).

## Unverified integration details

### Follow-up verification and design reconciliation — September 23, 2026

The supplied Muse replies correctly distinguish model inference from access to the personal agent. The intended built-in adapter is Meta Model API serving Muse models; a fallback to another provider is not required. See the [official overview](https://dev.meta.ai/docs/overview) and [quickstart](https://dev.meta.ai/docs/quickstart). The fixed product identity remains Meta Muse, with separate model API and optional personal-agent connection status.

The supplied replies also propose scheduled Gmail ingestion, a setup bundle, automatic schedule/configuration changes, and token rotation. These are useful design proposals but the official sources reviewed did not establish that exact personal-agent protocol. The [personal-agent product page](https://ai.meta.com/muse/) describes connected apps and background work, while the [Muse Code extension documentation](https://dev.meta.ai/docs/muse-code/extending) applies to a distinct coding product. Neither proves cloud-to-loopback connectivity or a one-approval bootstrap for this application. MCP-001 now records the connection gates and corrects the proposed secret storage, proposal endpoint, source retention, deduplication, and retry behavior. The later product decision supersedes native email ingestion: inbound is via Muse Agent or manual entry, with retained submitted evidence and heartbeat monitoring. Outbound is manually sent by the operator.

The reviewed primary sources did not establish a supported custom local MCP registration flow, application handoff/deep-link protocol, or completion callback for the Muse personal Mac agent. Validate these with the actual product and official integration documentation before promising a one-click connection. A cloud VM cannot inherently reach this app's loopback server. Do not add a public tunnel as an implicit prerequisite for the local MVP.

## Proposed operator experience

1. Name the section **Settings → AI assistance**. Separate **Connected assistant — Meta Muse** from optional **Built-in AI — Meta Model API / Muse Spark**. Keep Settings as the overall destination. Do not ask for a model API key as proof that the desktop agent is connected.
2. For agent access show workspace, permitted properties and record types, ability to read/propose, last successful connection, recent activity, test connection, and disconnect. Reveal only verified capabilities; distinguish unavailable, disconnected, and limited operation.
3. Place contextual **Prepare with Muse** actions inside expanded records, preserving D35's non-editable summary bar. Examples include case summaries, HOA follow-up drafts, owner updates, and document comparisons.
4. Show a preview of the context being shared, record references and freshness, then return proposals to the app's review flow. If supported handoff is unavailable, offer an explicitly manual copy/export workflow and manual result import without implying a live connection.
5. Home shows a compact draft-review entry when actionable work exists. The app remains authoritative for obligations and reminders. Agent work status (preparing, awaiting review, failed, cancelled) stays separate from repair/task/payment status.
6. Label revocation **Pause assistant access to this workspace**. It blocks app-mediated access and proposals; it cannot retract already shared context or stop independent activity inside Muse. Model-call limits apply to app-owned API requests; desktop-agent token use is unknown unless the integration reports it.
7. For the HOA regulator case, share the selected contact history, responsibility evidence and outstanding request. Muse prepares the next follow-up; sending and confirmed sent evidence are separate from drafting. Scheduling or an HOA acknowledgement never closes the repair.
8. Put token budgets, redaction-profile versions, and transport configuration under **Advanced**. Keep plain-language connection status, data access, permitted actions, activity, and pause/disconnect controls prominent.

### HOA follow-up presentation example

Inside the expanded shared-repair case, show:

> **Waiting for Cascadia HOA**  
> Three contacts recorded · Replacement date still unconfirmed  
> Next follow-up: September 25  
> **Prepare follow-up** · **Record response**

Preparing the follow-up uses the selected correspondence and latest commitment to draft a message. Review shows the proposed content, supporting records, and intended changes together. Draft approval and message sending are distinct actions. Keep the next follow-up and unresolved repair visible until separately updated or physically verified; Muse's work status never establishes repair completion.

## Existing design implications

`UI-001_DESIGN.md` D46 and `demo/operator-experience.html` currently conflate the personal agent and API provider. `MCP-001_DESIGN.md` already proposes delegated reads and reviewed writes, which is a useful starting point, but its transport, agent identity, proposal submission, token accounting and pause semantics require a verified adapter contract. An external agent's proposal need not trigger another model call merely to enter the review queue.

Recommended first milestone: with synthetic data, prove one bounded case read, one proposal returned for operator review, and successful denial after revocation. Then implement the supported connection controls and contextual actions. Preserve the copy/export fallback if a supported desktop transport is unavailable.
