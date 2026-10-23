# LEGAL-001 — Manual Legal-Matter Design

## Purpose

`LEGAL-001` records operator-entered legal-process facts and supporting evidence for a property or lease. It is a manual case-management aid, not legal advice, deadline calculation, notice delivery, or an eviction eligibility engine.

## Boundaries and safety rules

- Never infer legal compliance, readiness to file, possession, collectible tenant charges, notice delivery, or a successful outcome.
- A matter never changes lease, occupancy, rent, deposit, maintenance, or expense state implicitly.
- Legal expenses remain FIN-002 records; attorney engagement is a legal-matter relationship, never a Maintenance assignment.
- Original source records and evidence are preserved. A privacy label is not a legal-privilege determination.

## Data model

`legal_matters` has a stable UUID; required property ID; optional lease ID; status `preparing|active|on_hold|closed`; title; optional court reference; next-action text; optional waiting summary; created/updated/closed timestamps; and a required close outcome/reason only when closed. Property/lease consistency is validated through their source ports.

Associated immutable-link records use stable IDs and audit history:

- participants (Party IDs with a role and captured display snapshot),
- attorney/law-firm engagements (provider/Party ID, role, contact context, engagement date),
- source facts and notices (description, observed/recorded date, source reference, confirmation state),
- milestones (typed `notice_delivery`, `attorney_engagement`, `filing`, `hearing`, `agreement`, `outcome`, or `other`, each with date and evidence),
- deadlines (date/time, source, confirmation state, no computed legal meaning),
- typed links to Files, Communications, Tasks, Finance expenses, and authoritative source records.

No hardcoded linear milestone transition is required. Case status and dated milestones are independent.

## Commands and invariants

Create and update matter details through typed strict requests and writer-locked transactions. Add or correct linked facts by appending a new revision/audit event; do not silently overwrite evidence provenance. Close only with a non-empty operator-entered outcome and reason. Reopen is explicit and audited.

All links validate target existence through application ports. Deleting/archiving a linked record retains a historical reference and state instead of deleting the legal matter. Files are registered through FILE-001; tasks use TASK-002 for follow-up semantics; communications remain COM-001 records.

## Read and operator contract

Legal matters live under Leasing and related property/lease contexts, not as a permanent destination. A detail read includes status, next action/waiting facts, dated milestone timeline, evidence and source fact links, counsel, tasks, communications, costs, and closure outcome. It carries source availability/status rather than manufacturing empty values.

The UI distinguishes an operator-entered deadline from a confirmed deadline and shows its stated source. It offers explicit actions to record facts, contact, task, milestone, evidence, or closure; it never offers “file now,” automatic notices, or compliance assessments. A reviewed export selects records/evidence explicitly and separates internal/legal notes from the packet.

## Verification and definition of done

Test status/milestone independence, close/reopen audit history, property/lease consistency, immutable historical links, missing/deleted source handling, deadline provenance, link validation, no indirect lifecycle mutations, and bounded contextual reads. The feature is complete when a manual matter can be created, tracked, evidenced, followed up, closed, exported for review, and audited without any legal conclusion being inferred.

## Included operator interface delivery

This UI is part of this functional backlog and its completion criteria. Reuse the delivered UI-001 shell, generated contracts, source-owned commands, Light/Dark themes, keyboard/focus behavior and recovery patterns. Validate real temporary-workspace reads/writes, stale revisions, lost responses, restart/restore and bounded queries; backend-only delivery is incomplete.

#### D37: Include manual eviction/legal-matter tracking after MVP

This follow-up slice includes manual case tracking, evidence, attorney links, and reminders. Automated legal-rule interpretation is deferred. Record preparation and process facts without inferring legal eligibility, compliance, deadlines, or successful eviction. Use linked source records and separately confirmed milestones; actual move-out, rent, maintenance, and expense records retain their own lifecycles. D39–D40 define placement and lifecycle; the implementation boundaries below identify supporting work.

Use a typed legal-matter record linked to the property, lease, relevant parties, and any attorney or law firm. Track preparation, source facts and evidence, notices and service evidence, court reference, milestones, attorney involvement, communications, tasks, costs, and outcome. Preserve original records and versioned evidence. Any recorded deadline includes its date, source, and confirmation state.

Do not infer readiness to file, legal compliance, possession, move-out, collectible tenant charges, or automatic notice delivery. Legal expenses remain Finance-owned, and attorney engagement is distinct from a maintenance assignment. A reviewed export packet distinguishes selected evidence from internal or legal notes without treating an app privacy label as a determination of legal privilege.

#### D40: Separate legal-matter status from milestones

Use Preparing, Active, On hold, and Closed as broad manually controlled case statuses. Notice delivery, attorney engagement, filings, hearings, agreements, and outcomes are dated milestones with evidence, not a mandatory linear wizard. Each open matter displays its next action and waiting context. Closing requires an outcome and reason and never automatically ends the lease, changes occupancy, or changes financial records.

Deliver contextual `/legal/:matterId` detail from Leasing, property, lease and owner contexts, with attorney engagement, evidence, milestones, Tasks, Communications, costs and explicit closure confirmation. Providers remain a shared directory; attorney engagement is not a Maintenance assignment. Register legal next-action/deadline targets in Home, bounded search and information review through source contracts. No permanent Legal destination. Test out-of-order milestones, on-hold/closure, preserved history and unchanged lease/occupancy/money unless separately acted on. UI-001 and DASH-001 are delivered foundations; this feature does not depend on HOA-001.
