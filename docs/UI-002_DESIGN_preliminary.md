# UI-002 Preliminary Operator Experience Design

## Status and delivery scope

This preliminary design preserves the confirmed follow-up product decisions and technical handoffs moved from UI-001. It is the working design for UI-002, not an implementation-complete specification. Decision IDs and original validation scenario numbers remain stable. Dedicated domain designs own backend policy; [ARCHITECTURE.md](ARCHITECTURE.md) governs the stack and trust boundaries. No domain scope changes are made by this split.

UI-002 follows UI-001 and DASH-001. Its prerequisites are LEGAL-001, HOA-001, DATA-002, DATA-003, INGEST-002, and MCP-001. Deliver legal matters, HOA notices/shared repairs, Excel/Google Sheets intake, retained-evidence issue-proposal review, and connected-assistant setup/health. Extend existing workspaces, search, coverage, and Home through supported source contracts. DASH-003 retains the broader ingestion/voice/assistant attention dashboard scope.

Reuse [UI-001's shell, navigation, components, accessibility, client architecture, and recovery contracts](UI-001_DESIGN.md#technical-implementation-design). Do not duplicate that specification or implement domain policy in the browser. Backend readiness and UI delivery registration must both permit a route. Unsupported deep links explain the missing capability and offer a safe return. Do not claim legal/HOA, import, or assistant coverage before its UI is delivered.

## Domain terms

- **Legal matter:** A manually tracked preparation/process record linking a property/lease, participants, counsel, evidence, milestones, and next actions. It is not a legal eligibility determination.
- **HOA violation notice:** A received allegation or required-action notice tracked through response and documented resolution. A recorded allegation is not an admitted violation, and completion of a linked repair does not establish association acceptance.
- **Shared HOA-covered repair:** One Maintenance-owned case for a building system or common element affecting one or more managed condo units, with an association-responsibility assertion, affected scope, coordination history, and explicit physical verification. It is not a provider assignment or proof of accepted coverage.

## Confirmed product and interaction decisions

### Providers, legal matters, and HOA coordination

#### D37: Include manual eviction/legal-matter tracking in MVP

This follow-up MVP slice includes manual case tracking, evidence, attorney links, and reminders. Automated legal-rule interpretation is deferred. Record preparation and process facts without inferring legal eligibility, compliance, deadlines, or successful eviction. Use linked source records and separately confirmed milestones; actual move-out, rent, maintenance, and expense records retain their own lifecycles. D39–D40 define placement and lifecycle; the implementation boundaries below identify supporting work.

Use a typed legal-matter record linked to the property, lease, relevant parties, and any attorney or law firm. Track preparation, source facts and evidence, notices and service evidence, court reference, milestones, attorney involvement, communications, tasks, costs, and outcome. Preserve original records and versioned evidence. Any recorded deadline includes its date, source, and confirmation state.

Do not infer readiness to file, legal compliance, possession, move-out, collectible tenant charges, or automatic notice delivery. Legal expenses remain Finance-owned, and attorney engagement is distinct from a maintenance assignment. A reviewed export packet distinguishes selected evidence from internal or legal notes without treating an app privacy label as a determination of legal privilege.

#### D38: Keep MVP HOA work narrow

MVP supports receipt and tracking of HOA violation notices and their resolution. It also supports the D47 case: coordination of an HOA-covered common-element repair affecting condo units. Retain association/sender identity, property, original notice and any cited rule/evidence, dates, next action, communications, linked remediation work, and closure evidence. For a shared repair, retain one Maintenance-owned case, affected managed units, responsibility/coverage evidence, every contact and follow-up, and physical verification. These narrow capabilities do not require a standing HOA rules or board-management module.

A violation notice remains a separate matter from its remediation work. Preserve the original notice, cited rule reference, response, disputed state, claimed amounts, linked remediation, and closure evidence. A shared repair remains a Maintenance record even when it is linked to an HOA notice or coordinated through the association.

Standing rules management, architectural approval requests, assessments, board administration, and other broader HOA capabilities are explicitly deferred until after MVP. Preserve records and links so these can be added later without recreating violation or coordination history. Notice-related claimed or disputed amounts and HOA repair estimates remain contextual facts; they do not automatically create paid expenses or tenant charges.

#### D39: Place Providers, legal matters, and HOA work in context

Providers is a configurable permanent destination, visible by default and hideable through Settings. It remains accessible contextually from Maintenance and legal matters. Legal matters live within Leasing and the related lease/property. HOA notices live within the affected property; HOA-covered shared repairs live in Maintenance and every affected managed-property workspace. Both contribute actionable records to Home and appear in the relevant owner workspace. Do not introduce separate permanent Legal and HOA destinations in MVP.

The provider directory crosses module boundaries and uses shared party identity and one provider profile. Legal / Attorney is a service category with optional practice-area labels. An attorney engagement belongs to its legal matter rather than becoming a maintenance assignment. Formal category selection depends on VEND-CAT-001 being delivered before the consuming UI.

Legal and HOA work reuse Tasks, Files, Communications, Finance, and shared identity through explicit supported links. Do not squeeze either domain into repair categories or owner-concern records. Dedicated feature designs own their domain contracts and backlog sequencing.

#### D40: Separate legal-matter status from milestones

Use Preparing, Active, On hold, and Closed as broad manually controlled case statuses. Notice delivery, attorney engagement, filings, hearings, agreements, and outcomes are dated milestones with evidence, not a mandatory linear wizard. Each open matter displays its next action and waiting context. Closing requires an outcome and reason and never automatically ends the lease, changes occupancy, or changes financial records.

#### D41: Close HOA notices through an explicit outcome

Use Received, Reviewing, Action underway, Response submitted, and Closed, with flexible transitions and a separate disputed flag. Completing a linked repair can make evidence submission the next action but never closes the notice automatically. Closing records an outcome and supporting record, such as association acceptance or withdrawal. Operator closure without HOA confirmation requires a reason and an explicit unconfirmed label. Claimed fines and actual payments remain separate.

#### D47: Track one shared HOA-covered repair across affected condo units

When a building system or common element affects multiple condominium units, create one shared maintenance case rather than duplicate independent issues. Select a primary property for navigation and link every affected managed property or unit. If the operator does not manage every affected unit, retain a bounded free-text affected-area note without creating fake portfolio records. The case appears once on Home and in every linked property workspace.

The case records the affected scope (for example, Shared building water regulator), the association responsible for coordinating or covering the work, the basis and confidence of that responsibility, and the current next action. The HOA is a saved organization/contact, not a provider assignment. If the HOA hires a contractor, preserve the contractor as a separate provider and keep the HOA relationship visible. An operator-entered coverage assertion is not proof that the HOA has accepted responsibility, and an HOA estimate or claimed charge is not a paid property expense.

Show an ordered coordination timeline containing every call, email, submitted document, response, promise, appointment, and operator note. Each communication remains a distinct source-linked record. Repeated follow-ups are separate Tasks with waiting-for context and dates; completing one follow-up may schedule the next but never resolves the maintenance case. Home shows the current actionable follow-up or Waiting state without repeating the case once per affected unit.

The case remains open until the physical outcome is explicitly verified. HOA acknowledgement, approval, contractor assignment, or a promised replacement date are milestones rather than resolution. Closing requires an outcome such as regulator replaced and service verified, plus the verification date/source. Unresolved damage inside an individual unit can remain a separate linked issue after the shared asset is repaired.

In the summary bar, show the shared asset, affected scope, current HOA state, and next follow-up, for example: Shared water regulator · 3 units affected · Waiting for Cascadia HOA · Follow up Sep 25. Expanding it shows responsibility/coverage evidence, affected managed units, the communication timeline, current commitment, and actions to record contact, schedule another follow-up, link a contractor, or verify completion.

##### HOA follow-up presentation example

Inside the expanded shared-repair case, show:

> **Waiting for Cascadia HOA**
>
> Three contacts recorded · Replacement date still unconfirmed
>
> Next follow-up: September 25
>
> **Prepare follow-up** · **Record response**

Preparing the follow-up uses the selected correspondence and latest commitment to draft a message. Review shows the proposed content, supporting records, and intended changes together. Draft approval and message sending are distinct actions. Keep the next follow-up and unresolved repair visible until separately updated or physically verified; an assistant's work status never establishes repair completion.

The actions sit inside expanded content per [UI-001 D35](UI-001_DESIGN.md#d35-toggle-secondary-actions-directly-beneath-their-source-item). AI-assisted preparation follows D46's availability and review controls and the owning drafting feature; drafting availability is not guaranteed by UI-002 alone.

### Spreadsheet intake

#### D43: Import properties, owners, and providers from spreadsheets

Importing properties, owners, and providers from Excel and Google Sheets is a focused follow-up MVP intake capability, separate from DATA-001's broader later import of leases, balances, and operational history. D44 and D45 define source access and existing-record behavior.

Provide Import in each of the three directories and Settings → Import data. The proposed shared flow is Select source, Choose sheet, Map columns, Validate and review, Confirm import, Results. Offer templates with explicit property/owner relationship keys; preview source rows, field mappings, relationships, and intended operations before committing. Import owner identities before dependent property relationships within a coordinated batch. Reuse shared party identity for owners/providers rather than silently duplicating people or organizations.

Never invent required fields, infer ownership shares, or silently merge ambiguous identities. Unknown optional information stays unknown. Rows with missing required values or unresolved relationships cannot be committed as valid records. Use create/link/skip with explicit duplicate review per D45; general overwrite/update imports are outside MVP. Produce a row-level outcome report and recoverable import history; retries must not duplicate successfully imported records. Preview source values as a snapshot and avoid executing spreadsheet macros or treating formulas as app instructions.

#### D44: Support Excel uploads and direct read-only Google Sheets import

Support local Excel uploads and direct Google Sheets selection through read-only authorization. Let the operator select the spreadsheet and worksheet and review a captured source snapshot before import. Import exactly the reviewed snapshot; rereading changed source values requires a new preview. Do not require a sheet to be published publicly, modify the source sheet, or introduce ongoing synchronization in MVP. Source authorization does not create an application user account; credentials follow existing local secure-storage boundaries.

#### D45: Create, link, or skip; never silently overwrite

MVP imports create new valid records or explicitly link/skip existing ones after duplicate review. Linking means reusing the selected identity or record to satisfy a relationship; it does not authorize changing its existing fields or merging identities. Conflicting or ambiguous matches require resolution before affected rows can commit. Preserve property-to-owner relationships through explicit mapping. Present row-level validation errors and final import results, including created, linked, skipped, and failed outcomes. Retry only unfinished work without duplicating successful writes. General existing-record overwrite/update behavior is deferred.

### D46 (UI-002): Add connected assistants independently of built-in AI

Settings → **AI assistance** adds a **Connected assistants** card alongside UI-001's **Built-in AI** card. Model-provider and assistant selection are independent. Shared controls extend governance without authorizing official writes. Built-in model setup remains specified in UI-001.

### Connected-assistant setup

Explain: “Let an assistant bring relevant messages and propose work for your review.” List configured connections with the actual assistant/client name, connection method, allowed property/account scope, and status. Add connection offers validated local MCP clients and a separately verified file-exchange option for Muse Agent; unvalidated candidates show Setup not verified. More than one connection is permitted, but warn about overlapping scheduled mailbox coverage. Model-provider selection and assistant selection never change one another.

Setup follows choose client → inspect capabilities → select scope/data disclosure → test with synthetic evidence and a proposal → enable. No universal assistant API-key box. Grant creation is explicit; the assistant cannot approve its own scope. Show technical transport details only when needed for setup or troubleshooting. File exchange does not imply on-device inference. If the required file isolation is unavailable, offer manual import instead of pretending scoped automation is safe.

For scheduled discovery show last contact, last successful poll, requested versus acknowledged interval/configuration, failed/partial polling, and pending proposals. For interactive clients show last activity and connection-test status; do not invent a polling schedule. Use Not configured / Setup required / Ready / Paused / Needs attention / Revoked, with a reason and recovery action. “Connected” does not mean all messages have been found. Restoring a workspace displays historical connection details with Setup required.

### Shared control and proposal review

**Pause all AI assistance** stops new model calls, assistant reads/exports, and proposal admission. Explain that prior disclosures cannot be recalled and the assistant may still run its independent schedules. In-flight work may already have left the device; late results must pass current governance before admission. Existing drafts remain available for explicit operator review, edit, dismissal, and source-checked approval. Pausing one connection does not pause the other connections; revocation is a separate explicit action.

Per-action controls expose enablement, daily caps, registered model limits, and a read-only redaction profile summary. Assistant proposals use admission/payload limits rather than invented token budgets. Missing usage is Unknown. None of these controls approve a draft.

Show “Drafts awaiting review” with a count and link to the normal contextual queue. Each draft labels **Generated with [provider/model] · On this device/Cloud service** or **Proposed by [assistant connection] · [connection method]**. Distinguish verified connection identity from assistant-reported model details. Source, exact bounded governed input, AI suggestion, and operator edits remain separate. A file handoff must never be labeled local inference. Show stale evidence and paused/revoked source warnings; no generic approval bypasses a stale-source conflict.

### Integration acceptance scenarios

- Choose local assistance with a Muse file connection, then change only the model to a hosted option; assistant scope stays unchanged and cloud disclosure is required.
- Choose Meta Model API with a different compatible MCP assistant; neither credential grants the other connection's access.
- Test unavailable runtime, missing credential, unsupported modality, rejected disclosure, provider change, and restore; show truthful recovery/manual options.
- Pause globally and per connection; existing drafts stay visible, new requests are blocked at the appropriate boundary, and assistant scheduling is not falsely reported stopped.
- Review proposals from two assistants with duplicate source evidence; show source provenance and duplicate handling without two official records.
- Use full-summary-bar mouse/keyboard expansion in both themes; input controls inside expanded panels never toggle the parent.

The comparison demo uses clearly labeled simulated setup, tests, and review states. It makes no external calls and stores no credentials; it does not prove that any listed integration is implemented.

## Feature ownership and backend readiness

Dedicated contracts take precedence over product descriptions where they provide more specific policy.

| Backlog item | Dedicated design | Owns |
| --- | --- | --- |
| LEGAL-001 | [Manual Legal Matters](LEGAL-001_DESIGN.md) | Manual case facts, links, milestones, deadlines, closure, and safety boundaries. |
| HOA-001 | [HOA Notice and Shared-Repair Coordination](HOA-001_DESIGN.md) | Violation notices and HOA coordination for a Maintenance-owned shared repair. |
| DATA-002 | [Spreadsheet Intake](DATA-002_DESIGN.md) | Excel snapshot intake, create/link/skip decisions, commits, and outcomes. |
| DATA-003 | [Read-Only Google Sheets Intake](DATA-003_DESIGN.md) | Google Sheets authorization and immutable source snapshots. |
| HOA-002 | [Deferred Association Management](HOA-002_DESIGN.md) | Post-MVP association documents/profiles and approval workflows. |
| INGEST-002 | [Issue Proposal Review](INGEST-002_DESIGN.md) | Retained-evidence comparison, operator decisions, and atomic issue-review outcomes. |
| MCP-001 | [Assistant Integration](MCP-001_DESIGN.md) | Scoped access, grants, source/proposal submission, receipts, pause/revocation, and health. |

CONN-001 authorization is required through DATA-003 for read-only Sheets intake. DATA-001 retains broader later import/update scope. HOA-002 retains broader association management after MVP. Moving a UI workflow does not mark a backend feature implemented.

#### HOA-001 — HOA coordination

- Maintenance currently supports a property-level issue without a space, while Communications and Tasks support repeated contact and follow-up. Those records can remain authoritative for repair work, contact history, and reminders.
- The backend does not yet persist an HOA responsibility/coverage assertion, association evidence, multiple affected managed units, or the identity needed to present one shared case without duplicates. HOA-001 must add those links and physical-verification closure facts without treating the association as a provider or copying the underlying Maintenance issue.

### Legal and HOA implementation boundaries

- **LEGAL-001:** Supply authoritative cases, provider engagement links, manual statuses/milestones, deadline provenance, evidence targets, typed communication/task links, and closure outcomes. Do not introduce an inferred eviction deadline engine.
- **HOA-001:** Supply notice/property/sender context, original notice/rule references, response/remediation links, disputed state, claimed-charge context, and evidenced or explicitly unconfirmed closure. Shared-repair links retain Maintenance ownership, association responsibility, affected managed units, repeated contacts/follow-ups, and physical verification. Defer standing rules, architectural approvals, assessments, and board administration.

## Technical implementation handoff

### Feature folders and routes

Add `features/legal`, `features/hoa`, and `features/imports` under the existing web app. Extend existing `ai-review`, `settings`, and source-action registries instead of creating another shell. Register only ready workflows.

| Route | Purpose |
| --- | --- |
| `/legal/:matterId` | Manual legal-matter workflow from D37–D40. Legal matters are contextual links rather than a default permanent destination. |
| `/hoa/notices/:noticeId` | HOA violation-notice workflow and explicit closure. |
| `/imports/:importId/review` | Frozen spreadsheet snapshot, mapping, duplicate decisions, validation, and commit result. |
| `/ai/review/:draftId` | Extend the existing typed review route with INGEST-002 issue-proposal handlers, retained evidence, provenance, and atomic outcome presentation. |
| `/settings/:section?` | Add Import data, Google Sheets authorization, and Connected assistants sections. |
| `/maintenance/issues/:issueId/:section?` | Extend issue detail with shared HOA repair context. |

Legal matters are contextual links within Leasing and the related property/lease. HOA notices are contextual property links; shared repairs appear in each affected managed-property workspace. Add owner context without duplicating source records. Do not add permanent Legal or HOA destinations.

### Import and proposal commits

Use the shared disclosure, forms, error, recovery, and generated-client contracts from UI-001. Consequential import commits and legal/HOA closures require a confirmation naming the record/operation and consequence. Import review displays the frozen snapshot, mappings, unresolved relationships/duplicates, create/link/skip decisions, validation, and row-level results. Reconcile lost responses with the original operation key before retrying; never repeat successful writes.

INGEST-002 review displays retained source evidence, proposed fields, operator edits, and provenance separately. Approval must use the domain-owned atomic operation and show its correlated outcomes. A proposal, chat approval, file delivery, or assistant grant never bypasses operator authorization within the application. Stale revisions preserve edits and offer source refresh/review; admission limits are not invented model token budgets.

### Home, search, and coverage extensions

Register legal/HOA sources and typed contextual targets through their owning backend composition contracts. Show next actions and waiting context, preserving every source deadline and lifecycle. A shared repair has one explicit grouping identity and appears once on Home regardless of affected-unit count. Do not infer grouping from similar text. Extend bounded search/coverage only where backend contracts support it; failures remain unavailable, not empty or resolved.

### Implementation sequence and readiness

1. Verify UI-001, DASH-001, and all six backend prerequisites, including revision/idempotency, evidence and transaction contracts.
2. Implement contextual legal/HOA routes and source-action adapters, then Excel/Sheets snapshot review and results using common import components.
3. Add connected-assistant setup and governance/health, then INGEST-002 proposal review and outcome handlers.
4. Register ready capabilities and extend Home/search/coverage through backend contracts.
5. Run real temporary-workspace integration, accessibility, failure/recovery, and UI-001 regression checks. Fixtures and simulated setup do not prove readiness.

Before each workflow is enabled, verify initial/empty/unavailable/stale states, supported narrow layouts, keyboard operation, and a real critical read/write path. UI-002 remains a follow-up MVP slice; approval of this preliminary design does not make a domain capability ready.

## Validation matrix

| Area | Required validation |
| --- | --- |
| Happy paths | Legal milestones/closure; HOA response and physical verification; Excel/Sheets snapshot mapping and authorized import; assistant setup and proposal review. |
| Invalid combinations | Ambiguous identities, unresolved relationships, stale evidence, unsupported source/client, unconfirmed coverage, unavailable/paused/revoked capability. |
| Idempotency and retry | Lost responses, duplicate sources, unfinished-row retry, durable receipts, original operation keys, no duplicated imports/issues. |
| Transaction rollback | Failed approval/import operation exposes no partial official state beyond the owning domain's declared atomicity; stage/result distinctions remain explicit. |
| Persistence/schema | Restart resumes durable review/drafts, frozen snapshots, provenance, source identity and typed links; generated contracts match domain schemas. |
| Backup/restore | Retained history and drafts survive; credentials/grants do not become usable; configuration returns to Setup required and unresolved outcomes are reconciled. |
| Query budget/N+1 | Bounded snapshot/review lists and independent continuations; exact matching totals; backend compositions avoid a request per displayed row. |
| UI regression | Core navigation, themes, disclosure, drafts, keyboard/focus, partial failures and existing UI-001 workflows remain functional. |

### Retained workflow acceptance scenarios

17. Open an attorney through Providers and link their engagement to a legal matter. Preserve shared identity without creating a maintenance assignment. Hide Providers from navigation without losing the engagement link or related Home actions.

18. Record milestones out of a default sequence, put a legal matter on hold, then close with a recorded outcome. Preserve milestone history, next-action/deadline facts, and unchanged lease/occupancy/financial records unless separately acted upon.

19. Complete an HOA-linked repair and submit evidence. Keep the notice open until an explicit closure outcome; distinguish association-confirmed closure from operator closure without confirmation. Preserve claimed fines independently of actual paid expenses.

22. Preview a spreadsheet containing new records, likely duplicate shared identities, and properties referring to owners. Require explicit relationship/duplicate resolution, report invalid rows accurately, and verify retries do not duplicate imported records. Link/skip leaves existing fields unchanged.

23. Record a shared water-regulator failure affecting multiple condo units and covered by the HOA. Show one case on Home and in every affected managed-property workspace. Record multiple unanswered and answered contacts, each with its own date and source, and reschedule follow-up without rewriting prior attempts. HOA acknowledgement, contractor assignment, and a promised replacement date leave the case open. Close only after explicit replacement/service verification; keep any unit-specific residual damage open separately.

24. Preview a read-only Google Sheets snapshot, then change the source externally before confirming the import. Import only the reviewed snapshot or require a refreshed preview; never silently substitute changed values. No source-sheet writes or ongoing synchronization occur.

## DASH-001 composition reference (separate deliverable)

The following retained material governs DASH-001, not UI-001 or a new UI-002 prerequisite scope. UI-002 extends this delivered composition with legal/HOA sources. It is retained here as context for that extension.

#### D6: Separate active work, waiting, and upcoming work

Home presents Needs action, Waiting, and Upcoming. Urgent issues and overdue obligations come first with an understandable priority reason. A manageable initial selection has explicit totals and View all; additional records are never silently omitted. Missing-information prompts are separate unless they block an important action. D19 defines attention ordering.

#### D13: Group related attention without merging responsibilities

Group explicitly related work into one issue entry, showing its next action and other outstanding steps. Preserve every underlying task and deadline. Unrelated owner concerns remain separate. Opening the entry explains the whole situation; completing a step never silently completes other work. Exact identity and grouping rules must respect source links.

#### D19: Keep urgency, appointments, and unscheduled work visible

Urgent issues lead the attention queue. Today's appointments appear in a compact time-ordered strip. Other actionable work is ordered by overdue deadline, due today, then undated work needing a decision, with the reason shown. Upcoming defaults to seven days and offers a longer-range option. Undated work remains visible as Needs scheduling.

#### D29: Use qualified reassurance on quiet days

Home says No actions due today, retaining counts for waiting, upcoming, and information-review work plus the next appointment/deadline. An empty queue never establishes that everything is handled.

#### DASH-001 — Home aggregation

- Exact source-linked grouping can compose existing records. Grouping across sources requires explicit stored relationships; DASH-001 must not infer case identity from similar text, addresses, or dates.
- TASK-001's current summary implementation exposes overdue and due reminders, while its design also calls for today and next-seven-day buckets. Existing task date queries can contribute source data, but DASH-001 must reconcile the bounded Home contract and ordering with TASK-002 semantics.
- UI-001 owns the Home shell, disclosure components, and source-action adapters. DASH-001 owns the complete Needs action, Waiting, Upcoming, appointments, coverage-gap, and source-backed total composition.

| Required contract | Backlog owner | Minimum response behavior |
| --- | --- | --- |
| Home composition | DASH-001 | Separate action, waiting, upcoming, appointment, and information-review collections; total counts; priority reason; source identity; next action; and pagination/view-all links. |

### Retained core Home acceptance scenarios

1. Hide Owners and reorder navigation. Owner-related unresolved work remains on Home; Owners remains reachable under More and through contextual links. Restore defaults restores navigation without modifying domain records.

4. A repair has an appointment, owner conversation, and follow-up task. Group only explicitly related records. Completing one leaves the others intact and explains unresolved work.

5. No actions are due, but information is missing and future work exists. Home gives qualified reassurance and retains both categories; it never asserts complete property health.

## Visual reference and sources

The [operator experience prototype](../demo/operator-experience.html) contains simulated Home/integration states and fictional data. It does not prove integration readiness or define domain contracts; feature designs and this delivery allocation govern deferred workflows.

- [Feature backlog](FEATURE_BACKLOG.md)
- [UI-001 core design](UI-001_DESIGN.md)
- [Architecture](ARCHITECTURE.md)
- [AI integration research](AI_INTEGRATION_RESEARCH.md)
- [California Courts eviction overview](https://selfhelp.courts.ca.gov/eviction), used to distinguish notices from court cases when structuring manual legal matters.
- [California DRE common-interest-development guidance](https://www.dre.ca.gov/Newsroom/DRE_Updates/2026_08_21_Common_Interest_Dev.html), used to distinguish governing instruments, assessments, restrictions, and unresolved violation notices when bounding HOA scope.

The California sources are jurisdiction-specific examples informing record structure, not universal procedural templates or legal rules for the app.
