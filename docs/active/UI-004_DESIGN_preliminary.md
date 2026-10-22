# UI-004 Preliminary Legal and HOA Operator Experience Design

## Status and delivery scope

This post-MVP design preserves the LEGAL-001 and HOA-001 interaction decisions previously allocated to UI-002. It is a preliminary interface handoff, not an implementation-complete specification. The [backlog](../FEATURE_BACKLOG.md) owns phase and dependencies; [LEGAL-001](LEGAL-001_DESIGN.md) and [HOA-001](HOA-001_DESIGN.md) own domain policy. Original decision IDs and validation scenario numbers remain stable.

UI-004 follows UI-001 and DASH-001, then delivers contextual legal matters and HOA violation/shared-repair workflows when both domain contracts are ready. It reuses the current shell, full-summary-bar disclosure, accessibility, recovery, Home composition, search and information-review patterns. Spreadsheet intake and issue-proposal review remain [UI-002](UI-002_DESIGN_preliminary.md); connected-assistant setup and health remain [UI-003](UI-003_DESIGN_preliminary.md).

## Domain terms

- **Legal matter:** A manually tracked preparation/process record linking a property/lease, participants, counsel, evidence, milestones, and next actions. It is not a legal eligibility determination.
- **HOA violation notice:** A received allegation or required-action notice tracked through response and documented resolution. A recorded allegation is not an admitted violation, and completion of a linked repair does not establish association acceptance.
- **Shared HOA-covered repair:** One Maintenance-owned case for a building system or common element affecting one or more managed condo units, with an association-responsibility assertion, affected scope, coordination history, and explicit physical verification. It is not a provider assignment or proof of accepted coverage.

## Confirmed product and interaction decisions

### Providers, legal matters, and HOA coordination

#### D37: Include manual eviction/legal-matter tracking after MVP

This follow-up slice includes manual case tracking, evidence, attorney links, and reminders. Automated legal-rule interpretation is deferred. Record preparation and process facts without inferring legal eligibility, compliance, deadlines, or successful eviction. Use linked source records and separately confirmed milestones; actual move-out, rent, maintenance, and expense records retain their own lifecycles. D39–D40 define placement and lifecycle; the implementation boundaries below identify supporting work.

Use a typed legal-matter record linked to the property, lease, relevant parties, and any attorney or law firm. Track preparation, source facts and evidence, notices and service evidence, court reference, milestones, attorney involvement, communications, tasks, costs, and outcome. Preserve original records and versioned evidence. Any recorded deadline includes its date, source, and confirmation state.

Do not infer readiness to file, legal compliance, possession, move-out, collectible tenant charges, or automatic notice delivery. Legal expenses remain Finance-owned, and attorney engagement is distinct from a maintenance assignment. A reviewed export packet distinguishes selected evidence from internal or legal notes without treating an app privacy label as a determination of legal privilege.

#### D38: Keep initial HOA work narrow

The initial HOA feature supports receipt and tracking of HOA violation notices and their resolution. It also supports the D47 case: coordination of an HOA-covered common-element repair affecting condo units. Retain association/sender identity, property, original notice and any cited rule/evidence, dates, next action, communications, linked remediation work, and closure evidence. For a shared repair, retain one Maintenance-owned case, affected managed units, responsibility/coverage evidence, every contact and follow-up, and physical verification. These narrow capabilities do not require a standing HOA rules or board-management module.

A violation notice remains a separate matter from its remediation work. Preserve the original notice, cited rule reference, response, disputed state, claimed amounts, linked remediation, and closure evidence. A shared repair remains a Maintenance record even when it is linked to an HOA notice or coordinated through the association.

Standing rules management, architectural approval requests, assessments, board administration, and other broader HOA capabilities are explicitly deferred to HOA-002. Preserve records and links so these can be added later without recreating violation or coordination history. Notice-related claimed or disputed amounts and HOA repair estimates remain contextual facts; they do not automatically create paid expenses or tenant charges.

#### D39: Place Providers, legal matters, and HOA work in context

Providers is a configurable permanent destination, visible by default and hideable through Settings. It remains accessible contextually from Maintenance and legal matters. Legal matters live within Leasing and the related lease/property. HOA notices live within the affected property; HOA-covered shared repairs live in Maintenance and every affected managed-property workspace. Both contribute actionable records to Home and appear in the relevant owner workspace. Do not introduce separate permanent Legal and HOA destinations in this follow-up phase.

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

The actions sit inside expanded content per [UI-001 D35](../ui/operator-experience.md). AI-assisted preparation follows [UI-003's D46 connection boundary](UI-003_DESIGN_preliminary.md) when a connected assistant is used and the owning AI-DRAFT-001 action in either execution path; drafting availability is not guaranteed by UI-004 alone.

## Feature ownership and backend readiness

| Backlog item | Dedicated design | Owns |
| --- | --- | --- |
| LEGAL-001 | [Manual Legal Matters](LEGAL-001_DESIGN.md) | Manual case facts, links, milestones, deadlines, closure, and safety boundaries. |
| HOA-001 | [HOA Notice and Shared-Repair Coordination](HOA-001_DESIGN.md) | Violation notices and HOA coordination for a Maintenance-owned shared repair. |
| HOA-002 | [Deferred Association Management](HOA-002_DESIGN.md) | Later association documents/profiles and approval workflows; not a UI-004 prerequisite. |

#### HOA-001 — HOA coordination

- Maintenance currently supports a property-level issue without a space, while Communications and Tasks support repeated contact and follow-up. Those records can remain authoritative for repair work, contact history, and reminders.
- The backend does not yet persist an HOA responsibility/coverage assertion, association evidence, multiple affected managed units, or the identity needed to present one shared case without duplicates. HOA-001 must add those links and physical-verification closure facts without treating the association as a provider or copying the underlying Maintenance issue.

### Legal and HOA implementation boundaries

- **LEGAL-001:** Supply authoritative cases, provider engagement links, manual statuses/milestones, deadline provenance, evidence targets, typed communication/task links, and closure outcomes. Do not introduce an inferred eviction deadline engine.
- **HOA-001:** Supply notice/property/sender context, original notice/rule references, response/remediation links, disputed state, claimed-charge context, and evidenced or explicitly unconfirmed closure. Shared-repair links retain Maintenance ownership, association responsibility, affected managed units, repeated contacts/follow-ups, and physical verification. Defer standing rules, architectural approvals, assessments, and board administration.

## Technical implementation handoff

Add `features/legal` and `features/hoa` under the existing web app. Extend source-action registries and existing property, lease, Maintenance, owner and Home contexts only when their owning backend contracts are ready.

| Route | Purpose |
| --- | --- |
| `/legal/:matterId` | Manual legal-matter workflow from D37–D40, reached contextually from Leasing and property/lease detail. |
| `/hoa/notices/:noticeId` | HOA violation-notice workflow and explicit closure from affected property context. |
| `/maintenance/issues/:issueId/:section?` | Shared HOA repair context within one Maintenance-owned issue. |

Do not add permanent Legal or HOA destinations. Preserve one shared case across affected managed units and one grouped Home entry. Use UI-001 disclosure, forms, error, recovery, and generated-client contracts. Consequential legal/HOA closures require a confirmation naming the record and consequence. Reconcile lost responses through owning-domain operation results before retrying.

Register legal/HOA sources and typed contextual targets through their owning backend composition contracts. Show next actions and waiting context, preserving every source deadline and lifecycle. Do not infer grouping from similar text. Extend bounded search and information review only where backend contracts support it; failures remain unavailable, not empty or resolved.

Implement after UI-001, DASH-001, LEGAL-001 and HOA-001 contracts have passed revision, idempotency, evidence and transaction validation. Then add contextual routes and actions, source-owned Home/search/information-review registrations, and real temporary-workspace, accessibility, failure/recovery and UI-001 regression checks. Initial, empty, unavailable and stale states and supported narrow layouts are acceptance criteria; fixtures alone do not prove readiness.

## Validation matrix

| Area | Required validation |
| --- | --- |
| Happy paths | Legal milestones, attorney engagement, on-hold/closure; HOA response, repeated contact and physical verification. |
| Invalid combinations | Unconfirmed coverage, missing source evidence, stale matters, unavailable capability and invalid close outcomes. |
| Idempotency and retry | Lost responses, duplicate actions, original operation keys and no repeated closure or follow-up. |
| Transaction rollback | Failed source-owned command leaves no partial official state beyond declared domain atomicity. |
| Persistence/schema | Restart preserves matters, notices, shared repair links, deadlines, provenance and typed context. |
| Backup/restore | Retained history and links survive; unresolved outcomes reconcile. |
| Query budget/N+1 | Bounded Home/context lists, one grouped shared case and no per-row fetches. |
| UI regression | Core navigation, disclosure, themes, drafts, keyboard/focus, partial failures and UI-001 workflows remain functional. |

### Retained workflow acceptance scenarios

17. Open an attorney through Providers and link their engagement to a legal matter. Preserve shared identity without creating a maintenance assignment. Hide Providers from navigation without losing the engagement link or related Home actions.

18. Record milestones out of a default sequence, put a legal matter on hold, then close with a recorded outcome. Preserve milestone history, next-action/deadline facts, and unchanged lease/occupancy/financial records unless separately acted upon.

19. Complete an HOA-linked repair and submit evidence. Keep the notice open until an explicit closure outcome; distinguish association-confirmed closure from operator closure without confirmation. Preserve claimed fines independently of actual paid expenses.

23. Record a shared water-regulator failure affecting multiple condo units and covered by the HOA. Show one case on Home and in every affected managed-property workspace. Record multiple unanswered and answered contacts, each with its own date and source, and reschedule follow-up without rewriting prior attempts. HOA acknowledgement, contractor assignment, and a promised replacement date leave the case open. Close only after explicit replacement/service verification; keep any unit-specific residual damage open separately.

## DASH-001 composition reference (separate deliverable)

The following retained material governs the delivered DASH-001 composition. UI-004 extends it with legal/HOA sources; these core Home behaviors are context for that extension, not new UI-004 prerequisites.

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
- UI-001 owns the Home shell, disclosure components, and source-action adapters. DASH-001 owns the complete Needs action, Waiting, Upcoming, appointments, information-review gap, and source-backed total composition.

| Required contract | Backlog owner | Minimum response behavior |
| --- | --- | --- |
| Home composition | DASH-001 | Separate action, waiting, upcoming, appointment, and information-review collections; total counts; priority reason; source identity; next action; and pagination/view-all links. |

### Retained core Home acceptance scenarios

1. Hide Owners and reorder navigation. Owner-related unresolved work remains on Home; Owners remains reachable under More and through contextual links. Restore defaults restores navigation without modifying domain records.

4. A repair has an appointment, owner conversation, and follow-up task. Group only explicitly related records. Completing one leaves the others intact and explains unresolved work.

5. No actions are due, but information is missing and future work exists. Home gives qualified reassurance and retains both categories; it never asserts complete property health.

## Visual reference and sources

The [operator experience prototype](../../demo/operator-experience.html) contains simulated legal/HOA and Home states. It does not prove backend or interface readiness.

- [Feature backlog](../FEATURE_BACKLOG.md)
- [Core operator experience](../ui/operator-experience.md)
- [Architecture](../ARCHITECTURE.md)
- [California Courts eviction overview](https://selfhelp.courts.ca.gov/eviction), used to distinguish notices from court cases when structuring manual legal matters.
- [California DRE common-interest-development guidance](https://www.dre.ca.gov/Newsroom/DRE_Updates/2026_08_21_Common_Interest_Dev.html), used to distinguish governing instruments, assessments, restrictions, and unresolved violation notices when bounding HOA scope.

The California sources are jurisdiction-specific examples informing record structure, not universal procedural templates or legal rules for the app.
