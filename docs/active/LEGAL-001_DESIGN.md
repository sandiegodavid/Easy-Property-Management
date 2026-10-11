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

Legal matters live under Leasing and related property/lease contexts, not as a permanent MVP destination. A detail read includes status, next action/waiting facts, dated milestone timeline, evidence and source fact links, counsel, tasks, communications, costs, and closure outcome. It carries source availability/status rather than manufacturing empty values.

The UI distinguishes an operator-entered deadline from a confirmed deadline and shows its stated source. It offers explicit actions to record facts, contact, task, milestone, evidence, or closure; it never offers “file now,” automatic notices, or compliance assessments. A reviewed export selects records/evidence explicitly and separates internal/legal notes from the packet.

## Verification and definition of done

Test status/milestone independence, close/reopen audit history, property/lease consistency, immutable historical links, missing/deleted source handling, deadline provenance, link validation, no indirect lifecycle mutations, and bounded contextual reads. The feature is complete when a manual matter can be created, tracked, evidenced, followed up, closed, exported for review, and audited without any legal conclusion being inferred.
