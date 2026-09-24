# UI-001 Operator Experience Design

## Status

Product design confirmed by the product owner on September 23, 2026 (Q45), including the subsequent D35 correction to use the entire non-editable summary bar as the disclosure trigger. This is the authoritative product/interaction specification for UI-001 and the coordinated DASH-001 experience. Detailed API/schema contracts for new prerequisites remain implementation work; this approval does not mean features are implemented.

## Goals

- Help the operator complete useful property-management work.
- Give evidence-backed assurance that supported responsibilities are visible.
- Avoid overwhelming the operator while keeping important information accessible.
- Provide clean workflows and a calm, modern visual style.

## Confirmed decisions

### D1: Design the workflows and Home experience together

Design UI-001 and the future DASH-001 Home experience as one coherent journey, while retaining their separate implementation scope. Explicitly identify later capabilities. The journey covers attention, action, confirmation, and follow-up.

### D2: Separate work needing attention from information needing review

No immediate actions does not establish complete information. Present supported responsibilities, missing information, and intentionally non-applicable items explicitly. Avoid an opaque green property-health score. An example is “No immediate actions · Lease details incomplete.”

### D3: Lead with portfolio-wide priorities

Optimize the default experience for handling work across the portfolio. Also provide a complete property workspace and quick contextual entry for payments, expenses, conversations, and issues. These entry points open the same authoritative records.

### D4: Use a calm professional visual direction

Use warm neutral backgrounds, crisp typography, restrained color, and comfortable spacing. Use compact tables where comparison matters, modest property photos for recognition, and strong colors for meaningful states.

### D5: Offer configurable permanent destinations, including Owners

The default primary navigation is Home, Properties, Owners, Leasing, Money, Maintenance, and Providers, with Settings at the bottom (Providers added by D39). Settings lets the operator customize permanent destinations; an operator managing only their own properties can hide Owners. D17 defines customization controls and access to hidden destinations. Home includes the work queue and tasks. Owners must provide an owner-wide view of all related properties and information, including maintenance, money, leases, and conversations. Providers also remain accessible within Maintenance; conversations and documents remain available alongside related records. Owner and property views compose authoritative records rather than copy them.

### D6: Separate active work, waiting, and upcoming work

Home presents Needs action, Waiting, and Upcoming. Urgent issues and overdue obligations come first with an understandable priority reason. A manageable initial selection has explicit totals and View all; additional records are never silently omitted. Missing-information prompts are separate unless they block an important action. D19 defines attention ordering.

### D7: Waiting work has an explicit follow-up

Record who or what the operator is waiting for and a follow-up date. Waiting work resurfaces in Needs action when follow-up is due. Without a date, show Follow-up not scheduled. Deferring a reminder does not resolve its source issue. The compatibility findings below identify required backend extensions, included by D18.

### D8: Show coverage by applicable responsibility

Each property has a compact Coverage section for applicable areas such as occupancy, lease, rent tracking, deposits, and maintenance review. Distinguish Recorded, Needs review, Missing required information, and Not applicable. Derive states from records where possible; ask the operator only for facts the app cannot establish and retain the time of manual review. Avoid completion percentages and checks implying unsupported ongoing monitoring. D20, D33, and the explicit rules below govern applicability and review prompts.

### D9: Match the interaction surface to the work

Use inline expandable sections directly beneath records for quick inspection and short actions (D35 supersedes the original side-panel direction), and dedicated pages for substantial workflows such as leases, inspections, and deposit settlement. Preserve filters, scroll position, and property context on return. Use explicit action labels and show the result plus the next relevant step. Protect unfinished input and reserve confirmation screens for consequential actions. D15 and D21 define draft protection and failure recovery.

### D10: Prioritize desktop and laptop operation

Optimize keyboard use, readable tables, and evidence comparison. Keep narrower windows and tablet layouts usable. Full phone use and remote property-visit access are later product decisions; responsive layout alone does not provide remote access to the local MVP.

### D11: Give each owner a cross-property workspace

The overview presents the owner's properties, outstanding actions, recent conversations, available money summaries, and prominent owner concerns. Tabs are Properties, Money, Leases, Maintenance, Conversations, and Details. Distinguish money across related properties from money actually due to the owner. Multiple owners do not imply known financial shares. Retain former property relationships in history. Later owner-accounting capabilities must not be presented as already available.

### D12: Make navigation scope explicit

Main navigation opens portfolio-wide destinations. Tabs inside an owner or property remain scoped to that context. View in Money and equivalent cross-module links apply an explicit removable owner/property filter. Do not silently carry a global scope across main-navigation clicks.

### D13: Group related attention without merging responsibilities

Group explicitly related work into one issue entry, showing its next action and other outstanding steps. Preserve every underlying task and deadline. Unrelated owner concerns remain separate. Opening the entry explains the whole situation; completing a step never silently completes other work. Exact identity and grouping rules must respect source links.

### D14: Trigger reviews from meaningful changes or explicit review dates

Do not expire every review at an arbitrary interval. A relevant lease change can prompt rent-tracking review; an unrelated repair must not invalidate lease review. Explain why review is needed and distinguish recorded information from operator-reviewed information. D33 defines the initial per-area triggers.

### D15: Preserve substantial unfinished work as local drafts

Substantial workflows use resumable local drafts with visible Draft saved status. Drafts do not affect official balances, occupancy, or completed-work counts. Short forms preserve input during navigation and warn before discarding it. Official record commits remain explicit. Persistence must distinguish domain drafts from unfinished form input and must not claim success before saving succeeds.

### D16: Establish a restrained visual hierarchy

Use a slim left sidebar, warm off-white canvas, white content surfaces, dark readable text, and a restrained teal accent. Clear page titles, compact summaries, structured lists, recognition-oriented property cards, and comparison-oriented financial tables take precedence over decorative dashboard cards. Pair semantic status colors with text. Provide subtle transitions, visible keyboard focus, and reduced-motion support.

### D17: Customize navigation without hiding obligations

Settings supports showing, hiding, and reordering destinations, plus Restore defaults. Home and Settings remain accessible. Hidden destinations remain available under More. Hiding a destination only changes navigation; its unresolved work remains in Home.

### D18: Plan the supporting backend work explicitly

Include structured waiting/follow-up, coverage reviews, and draft recovery in the delivery plan. Keep dashboard aggregation under DASH-001 and shared workflow support under UI-001 or named prerequisites. Do not present nonfunctional controls. The exact dependency breakdown remains to be documented.

### D19: Keep urgency, appointments, and unscheduled work visible

Urgent issues lead the attention queue. Today's appointments appear in a compact time-ordered strip. Other actionable work is ordered by overdue deadline, due today, then undated work needing a decision, with the reason shown. Upcoming defaults to seven days and offers a longer-range option. Undated work remains visible as Needs scheduling.

### D20: Make property setup progressive and resumable

Allow a minimal valid property record, then offer a resumable setup checklist with applicable questions. Occupied rentals need lease/rent context; vacant properties need availability context. Missing information blocks only actions that require it. Explain each gap and link to its resolution. Not applicable is explicit and justified, never a bypass for required information.

### D21: Report partial success precisely and recover locally

Distinguish saved, unsaved, and partially completed work. If a payment is recorded but its attachment fails, retain the payment and offer Retry attachment without suggesting payment re-entry. Preserve input and show persistent errors beside affected items. Routine saves use brief success feedback with durable confirmation in the record itself.

### D22: Make the property overview an operational summary

Show property identity, occupancy/availability, owners, current lease, money summary, next actions, and coverage. Tabs are Spaces, Leases, Money, Maintenance, Conversations, Documents, and Details. Every summary opens its source records. Represent unavailable information explicitly rather than as zero.

### D23: Record rent in context and keep money categories distinct

Open a rent row and choose Record payment. Prefill its lease and outstanding amount, keeping date, actual method, recipient, and allocation visible and editable. Show remaining balance before saving. Money has distinct Rent, Expenses, Deposits, Scheduled checks, and Owner reports views. Scheduled checks and pending owner reports never count as received income. Portfolio totals require the appropriate reporting backend.

### D24: Connect lease execution and rent setup with explicit steps

Guide the operator through Lease details, Review and execute, Review rent schedule, and Related setup. Each step commits through an explicit action. After execution, show Lease recorded. Rent schedule needs review until synchronization is confirmed. Related setup includes applicable deposit tracking and move-in inspection. Unfinished steps remain visible as follow-up work.

### D25: Review repair completion without collapsing lifecycles

Offer a completion review covering work outcome, verification, appointments, assignment, and outstanding tasks. Each has a deliberate action; existing resolution guards remain enforced. Contractor reports completed can coexist with verification pending. Issue resolution explains remaining follow-up rather than silently completing unrelated work.

### D26: Compare owner rent reports with evidence and existing payments

Use a dedicated review page with reported details and evidence beside matching recorded payments. The operator can link a compatible existing payment, verify and record a new payment, or reject with a reason. Pending reports remain in the review queue. Verified reports link directly to the authoritative payment. Never offer an override that counts the same reported income twice.

### D27: Connect move-out, inspection, and settlement without merging decisions

The normal guided sequence is Confirm move-out, Finish inspection, Compare condition, Prepare settlement, Approve, and Record refund. Allow saving and resuming between steps. Show condition evidence beside proposed deductions, but require explicit entry and justification of each deduction. Settlement approved and Refund recorded are separate states. Clearly label exceptional paths allowed by existing domain rules.

### D28: Record conversations with optional follow-up in context

Offer Record conversation from the related owner, property, lease, or issue with context prefilled. Capture participants, channel, time, and summary. An optional Create follow-up section belongs in the same flow. Present conversations and follow-ups together chronologically while preserving separate statuses. Labels such as Record email must accurately describe recording an external interaction rather than sending it.

### D29: Use qualified reassurance on quiet days

Home says No actions due today, retaining counts for waiting, upcoming, and information-review work plus the next appointment/deadline. An empty queue never establishes that everything is handled.

### D30: Defer reminders without hiding urgency or rewriting deadlines

A follow-up reminder date does not change the original deadline. Overdue work remains overdue; urgent unresolved issues remain prominent when reminders are deferred. Removing urgency requires explicit priority change and a reason. Waiting context retains the source issue status.

### D31: Find records across destinations

Provide persistent Search with a keyboard shortcut, results grouped by record type, and distinguishing context. Include records from hidden destinations; archived records are available through an explicit option. List filters are visible and removable. Opening a result preserves a return route to the results.

### D32: Distinguish unavailable data from empty results

Routine workspace and backup status sits in a quiet area linking to Settings. Actionable failures identify affected capabilities and recovery actions. Failed rent loading says Rent information unavailable, never No rent due. Previously loaded data is labeled potentially outdated when appropriate. Connection status appears only for implemented integrations.

### D33: Explain coverage rules and their resolution

- Occupancy/availability: unknown or conflicting information needs review.
- Lease: an occupied rental missing required lease context shows missing information.
- Rent: an executed lease without a confirmed schedule needs setup; relevant term changes trigger review.
- Deposit: show whether applicable tracking exists and differs from the lease.
- Maintenance: show recorded issues and last explicit review; an empty issue list does not establish absence of problems.

When conditions coexist, lead with the most actionable and retain others in detail. Every prompt explains why it appeared and what resolves it. Supported responsibility areas must be enumerated; Coverage must not imply comprehensive legal or physical-property monitoring.

### D34: Present current records with accessible correction history

Show the effective record first, with a compact History link and relevant correction labels. Correct payment opens the required void-and-replace flow, explains impact, and preserves the original. Everyday history exposes what happened, when, the recorded actor, reasons, and evidence; technical audit details remain secondary.

### D35: Toggle secondary actions directly beneath their source item

The product owner approved the overall visual direction and requested inline expansion throughout. The entire top summary bar of an expandable item is the expand/collapse trigger. Clicking anywhere on that bar expands the secondary content immediately beneath it; clicking the bar again collapses it. This applies to Home's Needs action, Waiting, Upcoming, calendar/appointment items, and equivalent items throughout other destinations and record tabs. Do not append an unrelated detail panel at the bottom of the page.

The summary bar contains display-only text, status indicators, and a chevron. It must not contain editable fields, checkboxes, selects, nested links, or separate action buttons. Place Record payment, review/commit actions, navigation links, and all form controls inside the expanded content. Clicking or typing within that expanded content does not toggle the summary bar. Implement the summary bar as one keyboard-focusable disclosure control with native button behavior, supporting Enter and Space.

Each item expands independently. Collapsing does not commit, discard input, complete tasks, or change source status; preserve unfinished input and existing draft rules. Use aria-expanded and aria-controls, keyboard-operable triggers, and a local Collapse action that restores focus to its trigger. Substantial workflows can still continue into dedicated pages from the expanded context.

Explain the behavior with a compact visible hint above expandable lists: “Click anywhere on an item’s summary bar to expand or collapse its details.” The entire bar is the target, not only its text or chevron. Pair the bar with a chevron that reflects expansion. Keep the hint available without hover; do not require a tutorial or modal. In expanded content, retain the local Collapse action and keyboard support. This guidance applies across Home queues, calendar items, and other record tabs.

### D36: Provide directories before individual property and owner workspaces

In response to the request to browse multiple properties and owners, main-navigation Properties opens the property directory and Owners opens the owner directory. These are distinct from an individual record's workspace.

- Properties shows recognizable property cards with identity, ownership context, occupancy/availability, and attention state. Search by address, tenant, or owner; provide occupancy/review filters and explicit visible-result counts.
- Owners shows a directory with owner identity, related-property count/names, and owner attention context. Search by owner name or property address. Self-owned properties do not require a fabricated client-owner record.
- Open property/Open owner enters the selected workspace. Provide All properties/All owners to return with directory search and filters intact, plus a labeled record switcher for reviewing multiple records efficiently.
- Contextual property/owner links open the specific record. Main navigation always returns to the corresponding directory rather than silently reopening the last record.

Directory presentation is part of the confirmed design.

### D37: Include manual eviction/legal-matter tracking in MVP

The product owner accepted manual case tracking, evidence, attorney links, and reminders for the initial release. Automated legal-rule interpretation is deferred. Record preparation and process facts without inferring legal eligibility, compliance, deadlines, or successful eviction. Use linked source records and separately confirmed milestones; actual move-out, rent, maintenance, and expense records retain their own lifecycles. D39–D40 define placement and lifecycle; the delivery boundaries below identify supporting implementation work.

Use a typed legal-matter record linked to the property, lease, relevant parties, and any attorney or law firm. Track preparation, source facts and evidence, notices and service evidence, court reference, milestones, attorney involvement, communications, tasks, costs, and outcome. Preserve original records and versioned evidence. Any recorded deadline includes its date, source, and confirmation state.

Do not infer readiness to file, legal compliance, possession, move-out, collectible tenant charges, or automatic notice delivery. Legal expenses remain Finance-owned, and attorney engagement is distinct from a maintenance assignment. A reviewed export packet distinguishes selected evidence from internal or legal notes without treating an app privacy label as a determination of legal privilege.

### D38: Keep MVP HOA work narrow

MVP supports receipt and tracking of HOA violation notices and their resolution. It also supports the later-confirmed D47 case: coordination of an HOA-covered common-element repair affecting condo units. Retain association/sender identity, property, original notice and any cited rule/evidence, dates, next action, communications, linked remediation work, and closure evidence. For a shared repair, retain one Maintenance-owned case, affected managed units, responsibility/coverage evidence, every contact and follow-up, and physical verification. These narrow capabilities do not require a standing HOA rules or board-management module.

A violation notice remains a separate matter from its remediation work. Preserve the original notice, cited rule reference, response, disputed state, claimed amounts, linked remediation, and closure evidence. A shared repair remains a Maintenance record even when it is linked to an HOA notice or coordinated through the association.

Standing rules management, architectural approval requests, assessments, board administration, and other broader HOA capabilities are explicitly deferred until after MVP. Preserve records and links so these can be added later without recreating violation or coordination history. Notice-related claimed or disputed amounts and HOA repair estimates remain contextual facts; they do not automatically create paid expenses or tenant charges.

### D39: Place Providers, legal matters, and HOA work in context

Providers is a configurable permanent destination, visible by default and hideable through Settings. It remains accessible contextually from Maintenance and legal matters. Legal matters live within Leasing and the related lease/property. HOA notices live within the affected property; HOA-covered shared repairs live in Maintenance and every affected managed-property workspace. Both contribute actionable records to Home and appear in the relevant owner workspace. Do not introduce separate permanent Legal and HOA destinations in MVP.

The provider directory crosses module boundaries and uses shared party identity and one provider profile. Legal / Attorney is a service category with optional practice-area labels. An attorney engagement belongs to its legal matter rather than becoming a maintenance assignment. Formal category selection depends on VEND-CAT-001 being delivered before the consuming UI.

Legal and HOA work reuse Tasks, Files, Communications, Finance, and shared identity through explicit supported links. Do not squeeze either domain into repair categories or owner-concern records. Their MVP inclusion is settled; detailed domain contracts and backlog sequencing remain implementation-planning work.

### D40: Separate legal-matter status from milestones

Use Preparing, Active, On hold, and Closed as broad manually controlled case statuses. Notice delivery, attorney engagement, filings, hearings, agreements, and outcomes are dated milestones with evidence, not a mandatory linear wizard. Each open matter displays its next action and waiting context. Closing requires an outcome and reason and never automatically ends the lease, changes occupancy, or changes financial records.

### D41: Close HOA notices through an explicit outcome

Use Received, Reviewing, Action underway, Response submitted, and Closed, with flexible transitions and a separate disputed flag. Completing a linked repair can make evidence submission the next action but never closes the notice automatically. Closing records an outcome and supporting record, such as association acceptance or withdrawal. Operator closure without HOA confirmation requires a reason and an explicit unconfirmed label. Claimed fines and actual payments remain separate.

### D42: Provide an explicit light/dark appearance switch

Settings includes Appearance with Light and Dark controls. Apply changes immediately throughout the interface, including inline expansions, forms, tables, status labels, and dialogs. Remember the operator's choice locally and preserve work when switching. Both themes retain readable contrast, text/icon status cues, and visible keyboard focus. Theme choice is presentation state and never modifies property records.

### D43: Import properties, owners, and providers from spreadsheets

The product owner requested importing properties, owners, and providers from Excel and Google Sheets. Treat this as a focused initial-release intake capability, separate from DATA-001's broader later import of leases, balances, and operational history. D44 and D45 settle source access and existing-record behavior.

Provide Import in each of the three directories and Settings → Import data. The proposed shared flow is Select source, Choose sheet, Map columns, Validate and review, Confirm import, Results. Offer templates with explicit property/owner relationship keys; preview source rows, field mappings, relationships, and intended operations before committing. Import owner identities before dependent property relationships within a coordinated batch. Reuse shared party identity for owners/providers rather than silently duplicating people or organizations.

Never invent required fields, infer ownership shares, or silently merge ambiguous identities. Unknown optional information stays unknown. Rows with missing required values or unresolved relationships cannot be committed as valid records. Use create/link/skip with explicit duplicate review per D45; general overwrite/update imports are outside MVP. Produce a row-level outcome report and recoverable import history; retries must not duplicate successfully imported records. Preview source values as a snapshot and avoid executing spreadsheet macros or treating formulas as app instructions.

### D44: Support Excel uploads and direct read-only Google Sheets import

Support local Excel uploads and direct Google Sheets selection through read-only authorization. Let the operator select the spreadsheet and worksheet and review a captured source snapshot before import. Import exactly the reviewed snapshot; rereading changed source values requires a new preview. Do not require a sheet to be published publicly, modify the source sheet, or introduce ongoing synchronization in MVP. Source authorization does not create an application user account; credentials follow existing local secure-storage boundaries.

### D45: Create, link, or skip; never silently overwrite

MVP imports create new valid records or explicitly link/skip existing ones after duplicate review. Linking means reusing the selected identity or record to satisfy a relationship; it does not authorize changing its existing fields or merging identities. Conflicting or ambiguous matches require resolution before affected rows can commit. Preserve property-to-owner relationships through explicit mapping. Present row-level validation errors and final import results, including created, linked, skipped, and failed outcomes. Retry only unfinished work without duplicating successful writes. General existing-record overwrite/update behavior is deferred.

### D46: Choose built-in AI and connected assistants independently

This revision adopts [AI integration research](AI_INTEGRATION_RESEARCH.md). Settings → **AI assistance** has two independent cards, **Built-in AI** and **Connected assistants**, plus shared pause/review controls. Keep the default presentation brief; expand setup, scope, limits, and diagnostics under non-editable summary bars following D35. AI remains optional and never becomes a permanent navigation destination.

#### Built-in AI

Explain: “Help summarize records and prepare drafts inside this app.” Choose **Off**, **On this device**, or **Cloud service**. Below the choice show only registered, tested adapters/models for the selected route. Meta Model API and OpenAI are hosted candidates; a validated local runtime/model is another option. Do not show “Muse recommended,” an unexplained “Other,” or a selected provider that has not passed evaluation. Selection affects new runs only and does not connect a personal assistant.

For cloud setup, use write-only credential entry with Configured/Not configured state, a synthetic connection test, selected model, and explicit destination/data-class disclosure. Explain what leaves the device. Changing the destination requires that destination's permission; a generic Save cannot consent. Keys remain in the OS credential store, excluded from workspace data, history, and backups. A subscription to a chat product does not establish API credentials or billing.

For on-device setup, show runtime/model, installation/download requirement, disk/memory guidance established for that exact package, test status, and supported tasks. Advanced details contain runtime version and model digest. Never claim “Ready,” offline operation, or voice/image support until the actual device/runtime/action is verified. Setup is operator-assisted in MVP; no automatic download from a workflow. Weights and runtime setup do not travel with a workspace backup.

Show task availability separately: summaries may be Ready while transcription is Unsupported. Unsupported/unavailable actions explain why and preserve manual work. No silent fallback to cloud or another vendor. An explicit “Try with [provider]” must name the destination, preserve the original draft, and pass disclosure/governance again. Keep advanced per-action model overrides and token limits collapsed by default.

#### Connected assistants

Explain: “Let an assistant bring relevant messages and propose work for your review.” List configured connections with the actual assistant/client name, connection method, allowed property/account scope, and status. Add connection offers validated local MCP clients and a separately verified file-exchange option for Muse Agent; unvalidated candidates show Setup not verified. More than one connection is permitted, but warn about overlapping scheduled mailbox coverage. Model-provider selection and assistant selection never change one another.

Setup follows choose client → inspect capabilities → select scope/data disclosure → test with synthetic evidence and a proposal → enable. No universal assistant API-key box. Grant creation is explicit; the assistant cannot approve its own scope. Show technical transport details only when needed for setup or troubleshooting. File exchange does not imply on-device inference. If the required file isolation is unavailable, offer manual import instead of pretending scoped automation is safe.

For scheduled discovery show last contact, last successful poll, requested versus acknowledged interval/configuration, failed/partial polling, and pending proposals. For interactive clients show last activity and connection-test status; do not invent a polling schedule. Use Not configured / Setup required / Ready / Paused / Needs attention / Revoked, with a reason and recovery action. “Connected” does not mean all messages have been found. Restoring a workspace displays historical connection details with Setup required.

#### Shared control and review

**Pause all AI assistance** stops new model calls, assistant reads/exports, and proposal admission. Explain that prior disclosures cannot be recalled and the assistant may still run its independent schedules. In-flight work may already have left the device; late results must pass current governance before admission. Existing drafts remain available for explicit operator review, edit, dismissal, and source-checked approval. Pausing one connection does not pause the other connections; revocation is a separate explicit action.

Per-action controls expose enablement, daily caps, registered model limits, and a read-only redaction profile summary. Assistant proposals use admission/payload limits rather than invented token budgets. Missing usage is Unknown. None of these controls approve a draft.

Show “Drafts awaiting review” with a count and link to the normal contextual queue. Each draft labels **Generated with [provider/model] · On this device/Cloud service** or **Proposed by [assistant connection] · [connection method]**. Distinguish verified connection identity from assistant-reported model details. Source, exact bounded governed input, AI suggestion, and operator edits remain separate. A file handoff must never be labeled local inference. Show stale evidence and paused/revoked source warnings; no generic approval bypasses a stale-source conflict.

#### Acceptance scenarios

- Choose local assistance with a Muse file connection, then change only the model to a hosted option; assistant scope stays unchanged and cloud disclosure is required.
- Choose Meta Model API with a different compatible MCP assistant; neither credential grants the other connection's access.
- Test unavailable runtime, missing credential, unsupported modality, rejected disclosure, provider change, and restore; show truthful recovery/manual options.
- Pause globally and per connection; existing drafts stay visible, new requests are blocked at the appropriate boundary, and assistant scheduling is not falsely reported stopped.
- Review proposals from two assistants with duplicate source evidence; show source provenance and duplicate handling without two official records.
- Use full-summary-bar mouse/keyboard expansion in both themes; input controls inside expanded panels never toggle the parent.

The comparison demo uses clearly labeled simulated setup, tests, and review states. It makes no external calls and stores no credentials; it does not prove that any listed integration is implemented.

### D47: Track one shared HOA-covered repair across affected condo units

When a building system or common element affects multiple condominium units, create one shared maintenance case rather than duplicate independent issues. Select a primary property for navigation and link every affected managed property or unit. If the operator does not manage every affected unit, retain a bounded free-text affected-area note without creating fake portfolio records. The case appears once on Home and in every linked property workspace.

The case records the affected scope (for example, Shared building water regulator), the association responsible for coordinating or covering the work, the basis and confidence of that responsibility, and the current next action. The HOA is a saved organization/contact, not a provider assignment. If the HOA hires a contractor, preserve the contractor as a separate provider and keep the HOA relationship visible. An operator-entered coverage assertion is not proof that the HOA has accepted responsibility, and an HOA estimate or claimed charge is not a paid property expense.

Show an ordered coordination timeline containing every call, email, submitted document, response, promise, appointment, and operator note. Each communication remains a distinct source-linked record. Repeated follow-ups are separate Tasks with waiting-for context and dates; completing one follow-up may schedule the next but never resolves the maintenance case. Home shows the current actionable follow-up or Waiting state without repeating the case once per affected unit.

The case remains open until the physical outcome is explicitly verified. HOA acknowledgement, approval, contractor assignment, or a promised replacement date are milestones rather than resolution. Closing requires an outcome such as regulator replaced and service verified, plus the verification date/source. Unresolved damage inside an individual unit can remain a separate linked issue after the shared asset is repaired.

In the summary bar, show the shared asset, affected scope, current HOA state, and next follow-up, for example: Shared water regulator · 3 units affected · Waiting for Cascadia HOA · Follow up Sep 25. Expanding it shows responsibility/coverage evidence, affected managed units, the communication timeline, current commitment, and actions to record contact, schedule another follow-up, link a contractor, or verify completion.

#### HOA follow-up presentation example

Inside the expanded shared-repair case, show:

> **Waiting for Cascadia HOA**
>
> Three contacts recorded · Replacement date still unconfirmed
>
> Next follow-up: September 25
>
> **Prepare follow-up** · **Record response**

Preparing the follow-up uses the selected correspondence and latest commitment to draft a message. Review shows the proposed content, supporting records, and intended changes together. Draft approval and message sending are distinct actions. Keep the next follow-up and unresolved repair visible until separately updated or physically verified; an assistant's work status never establishes repair completion.

The actions sit inside the expanded content per D35. AI-assisted preparation follows D46's availability and review controls.

## Confirmed design coverage

- Coherent operating experience (D1, D3, D5–D7, D9)
  - Settled: owner workspace structure, navigation scope, source-linked attention grouping, and draft protection.
  - Settled: navigation customization controls, property workspace structure, attention ordering, seven-day default horizon, undated work, and partial-success feedback.
- Evidence-backed assurance (D2, D8)
  - Settled: review triggered by relevant changes or explicit dates.
  - Settled: progressive property setup and justified applicability.
  - Settled: coverage rules, qualified reassurance, unavailable-data states, and visible reasons for review.
- Calm presentation (D4, D10)
  - Settled: overall visual hierarchy, palette direction, keyboard focus, and reduced motion.
  - Settled: overall screen direction, directory entry points, and inline expansion refinements. Existing preview predates D39's Providers and legal/HOA additions.
- Workflow specification
  - Settled: principal rent, lease setup, repair completion, owner-report review, move-out/settlement, and conversation journeys (D23–D28).
  - Settled: finding records, deferring work, correction presentation, and operating-status feedback.
  - Settled: manual legal-matter, HOA-notice, and shared HOA-covered repair scope, navigation, lifecycle, and closure behavior.
  - Settled: appearance switch, visible inline-toggle guidance, Excel/read-only Google Sheets snapshots, create/link/skip import behavior, and independent model/assistant selections, credentials, pause, limits, governed-input, disclosure, and redaction controls (D42–D46).
  - Complete: consolidated product design confirmed. Detailed API/schema design and implementation follow separately.

## Working glossary

- **Needs action:** Supported work requiring an operator action now. Urgent issues lead, followed by overdue, due-today, and undated decision work.
- **Waiting:** Work awaiting a person or event, with a visible follow-up status. This does not resolve its source record.
- **Upcoming:** Work with a future action date, shown for the next seven days by default with a longer-range option.
- **Coverage:** Visibility into recorded, missing, review-needed, and non-applicable information for supported responsibilities; not a compliance certification.
- **Information needing review:** Missing or uncertain information that limits what the app can establish; distinct from an overdue obligation.
- **Property workspace:** A contextual view of a property's authoritative records and related work, not a separate copy of those records.
- **Owner workspace:** A contextual view across an owner's related properties and records. It must distinguish property-level facts from amounts attributable to that owner.
- **Legal matter:** A manually tracked preparation/process record linking a property/lease, participants, counsel, evidence, milestones, and next actions. It is not a legal eligibility determination.
- **HOA violation notice:** A received allegation or required-action notice tracked through response and documented resolution. A recorded allegation is not an admitted violation, and completion of a linked repair does not establish association acceptance.
- **Shared HOA-covered repair:** One Maintenance-owned case for a building system or common element affecting one or more managed condo units, with an association-responsibility assertion, affected scope, coordination history, and explicit physical verification. It is not a provider assignment or proof of accepted coverage.

## Existing constraints to preserve

- Unknown occupancy or availability is not vacant or available.
- Task completion, reminder dismissal, appointment completion, and issue or concern resolution are distinct actions.
- Scheduled checks, received rent, held deposits, quotes, and paid expenses are different financial concepts.
- Communication recording is manual in COM-001; sending and ingestion arrive separately.
- The local MVP does not provide remote access. Current reminders are shown while the application runs.
- Financial corrections preserve history, and aggregates retain source-record drill-down.

## Backlog reconciliation

- TASK-002 owns waiting/follow-up behavior; OPS-001 owns shared operator support. Tasks and provider UI are explicit UI-001 scope.
- VEND-CAT-001, CONN-001, and FIN-003 move before UI-001 so provider categories, Sheets authorization, and dashboard totals have source capabilities.
- LEGAL-001 and HOA-001 supply manual legal matters, violation-notice records, and narrow HOA-covered shared-repair coordination before their UI. HOA-002 retains broader HOA work after MVP.
- DATA-002 and DATA-003 supply initial Excel and read-only Sheets intake. DATA-001 retains broader later migration/update scope.
- UI-001 remains immediately before DASH-001. LEAD-002 adds showing integration after the showing workflow exists, removing the former forward dependency.

## Backend compatibility findings

These are implementation gaps, not reasons to silently weaken confirmed experience decisions. D18 includes supporting backend work in the delivery plan; the backlog now names its prerequisites.

- Structured waiting-for context and attention suppression/snooze are not implemented. Existing task due dates and reminders do not establish separate follow-up semantics.
- Exact source-linked grouping can compose existing records. Cross-source grouping requires explicit relationships rather than text similarity.
- Leases, inspections, communications, and deposit settlements have persisted domain drafts. There is no universal partial-form recovery facility.
- Property coverage, review attestations, and relevant-change freshness need additional persisted state and policy; updated timestamps do not establish review.
- TASK-001's summary implementation exposes overdue and due reminders, while its design also promises today and next-seven-day buckets. Existing task queries can supply date filtering; the consolidated contract needs reconciliation.
- Owner views can compose effective-dated relationships and owner-filtered concerns/reports. Owner entitlement, balances, fees, statements, and disbursements require their later domain capabilities.
- Current ownership must not erase historical or unresolved work. Local-operator ownership has no owner Party ID; the UI must not fabricate one.
- Existing Maintenance supports a property-level issue without a space, and Communications/Tasks support repeated contact and follow-up. It does not yet persist an HOA responsibility assertion, multiple affected property/unit links, or shared-case deduplication; HOA-001 must add these contracts without treating the association as a provider.

## Delivery boundaries

The design is broader than the existing UI-001 backlog row. Preserve backend-first dependency ordering and explicit readiness:

1. **Shared operator support:** Implement missing waiting/follow-up semantics, coverage review state, incomplete-form recovery, navigation preferences, and bounded search/read composition. Reuse existing domain drafts rather than replacing their lifecycle rules.
2. **Providers:** Deliver the directory with shared identity and existing service history. Bring the required VEND-CAT-001 category support before its consuming UI, rather than presenting free-form service labels as an implemented category taxonomy. Legal/Attorney belongs in the category model; engagement belongs to the legal matter.
3. **Legal matters:** Add the authoritative case record, provider engagement links, manual statuses/milestones, deadline provenance, evidence targets, typed communication/task links, and explicit closure outcome. Do not broaden rent-adjustment rules into an unreviewed eviction deadline engine.
4. **HOA coordination:** Add the notice record, property/sender context, original notice and rule references, response/remediation links, disputed state, claimed-charge context, and evidenced or explicitly unconfirmed closure. Also add the narrow Maintenance-owned shared-repair links for association responsibility, affected managed units, repeated contact/follow-up, and physical verification. Defer standing rules, architectural approvals, assessments, and board administration.
5. **UI-001 workflows:** Deliver directories, contextual workspaces, inline expansions, substantial workflow pages, and the agreed domain interactions using those validated capabilities. Navigation changes alone do not establish backend feature readiness.
6. **DASH-001 aggregation:** Compose Needs action, Waiting, Upcoming, appointments, and information review from authoritative sources. Include legal/HOA next actions and retain existing domain-specific semantics. Reconcile the current showing dependency explicitly; never imply showings exist before LEAD-002 is available.

Reports, owner balances/statements, automated sending, remote access, and AI/legal-rule interpretation retain their separately agreed scope. The backlog enumerates the new prerequisites and this document supplies acceptance criteria; it must not mark existing domain items complete merely because a design or sample screen exists.

## Design validation scenarios

These scenarios derive from confirmed decisions and must be included in implementation acceptance:

1. Hide Owners and reorder navigation. Owner-related unresolved work remains on Home; Owners remains reachable under More and through contextual links. Restore defaults restores navigation without modifying domain records.
2. Open an owner, then a related property, then Money through main navigation. Contextual tabs retain scope; main navigation returns to the full portfolio. Explicit cross-module drill-down filters are visible and removable.
3. Defer an urgent repair reminder. The reminder changes, but urgency, original deadlines, and unresolved source state remain visible.
4. A repair has an appointment, owner conversation, and follow-up task. Group only explicitly related records. Completing one leaves the others intact and explains unresolved work.
5. No actions are due, but information is missing and future work exists. Home gives qualified reassurance and retains both categories; it never asserts complete property health.
6. A lease is executed but rent synchronization is unfinished. Occupancy follows valid lease rules; rent setup remains visibly outstanding with a resumable next action.
7. Rent is recorded, but evidence upload fails. The payment remains recorded once, with a targeted attachment retry and no invitation to duplicate it.
8. An owner report matches an existing receipt. Verification adopts the compatible receipt or requires correction; it never counts the report as additional income.
9. Close a substantial draft and reopen it. Restore saved input, show draft status, and exclude it from official counts and balances.
10. Maintenance or finance data fails to load. Present unavailable/outdated information and recovery, never an empty successful result or zero balance.
11. Record move-out, finalize inspection, and prepare settlement. Findings do not become deductions automatically; approval and actual refund recording remain separate.
12. Search for a record in a hidden destination and return from detail to results. Retain query/context and respect archived-record filtering.
13. Correct a financial record. Preserve original history, reason, lineage, and current effective amounts.
14. Use keyboard navigation and narrow desktop/tablet widths. Preserve labeled actions, visible focus, readable tables, and accessible evidence comparison without overlapping controls.
15. Click the text, status, chevron, or unused space within an item's top summary bar in each Home queue, the calendar strip, and record tabs. Each toggles the same section immediately beneath the item; a second click collapses it. Enter and Space work on the focused bar. Verify no inputs, nested links, or separate action buttons occur inside the bar. Editing fields or invoking actions in the expanded section does not toggle the bar, alter neighboring expansions, or discard unfinished input.
16. Browse multiple properties/owners, filter/search, open an individual workspace, switch to another record, and return to the directory. Preserve directory criteria and show the correct selected record's context throughout.
17. Open an attorney through Providers and link their engagement to a legal matter. Preserve shared identity without creating a maintenance assignment. Hide Providers from navigation without losing the engagement link or related Home actions.
18. Record milestones out of a default sequence, put a legal matter on hold, then close with a recorded outcome. Preserve milestone history, next-action/deadline facts, and unchanged lease/occupancy/financial records unless separately acted upon.
19. Complete an HOA-linked repair and submit evidence. Keep the notice open until an explicit closure outcome; distinguish association-confirmed closure from operator closure without confirmation. Preserve claimed fines independently of actual paid expenses.
20. Switch Light/Dark in Settings while a form/inline section is open. Preserve input, focus, expansion, and record state; retain the appearance preference across restarts.
21. Explain inline toggling visibly in every relevant view and keep the chevron, aria-expanded, and actual section visibility consistent on repeated clicks and keyboard use.
22. Preview a spreadsheet containing new records, likely duplicate shared identities, and properties referring to owners. Require explicit relationship/duplicate resolution, report invalid rows accurately, and verify retries do not duplicate imported records. Link/skip leaves existing fields unchanged.
23. Record a shared water-regulator failure affecting multiple condo units and covered by the HOA. Show one case on Home and in every affected managed-property workspace. Record multiple unanswered and answered contacts, each with its own date and source, and reschedule follow-up without rewriting prior attempts. HOA acknowledgement, contractor assignment, and a promised replacement date leave the case open. Close only after explicit replacement/service verification; keep any unit-specific residual damage open separately.
24. Preview a read-only Google Sheets snapshot, then change the source externally before confirming the import. Import only the reviewed snapshot or require a refreshed preview; never silently substitute changed values. No source-sheet writes or ongoing synchronization occur.

## Screen review

An in-conversation interactive design preview uses fictional sample data to review Home, owner/property directories and workspaces, inline secondary actions, and navigation customization. The product owner approved the overall visual design and requested inline toggles and clarification of browsing multiple records. D35 and D36 document the resulting refinement. The preview is not production UI and does not write application records. The complete product design is confirmed. The illustrative preview is not an implementation contract and predates some final additions, including Providers/legal/HOA/import screens. Its AI Settings now demonstrates D46 with simulated provider/assistant states and full-bar disclosure controls; Use this document as authority for workflows not shown in the demo.

## Sources

- [Feature backlog](FEATURE_BACKLOG.md)
- [Product brief](PRODUCT_BRIEF.md)
- [Architecture](ARCHITECTURE.md)
- [Product decisions](DECISIONS.md)
- [README](../README.md)
- [California Courts eviction overview](https://selfhelp.courts.ca.gov/eviction), used to distinguish notices from court cases when structuring manual legal matters.
- [California DRE common-interest-development guidance](https://www.dre.ca.gov/Newsroom/DRE_Updates/2026_08_21_Common_Interest_Dev.html), used to distinguish governing instruments, assessments, restrictions, and unresolved violation notices when bounding HOA scope.

The California sources are jurisdiction-specific examples informing record structure, not universal procedural templates or legal rules for the app.