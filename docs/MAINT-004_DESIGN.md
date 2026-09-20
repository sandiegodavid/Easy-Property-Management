# MAINT-004 — Maintenance Reporter Attribution

## Purpose

`MAINT-004` extends the implemented MAINT-001 issue aggregate so every official maintenance issue records who reported it and the reporter's contextual role: `owner`, `tenant`, `manager`, or `staff`. Reporter attribution remains visible in issue intake, issue detail and lists, linked communication history, and later repair reporting.

The boundary is deliberate:

- Maintenance owns the reporter assertion attached to an issue, its validation policy, its durable display snapshot, and correction history.
- Parties owns reusable person or organization identity and contact methods.
- Portfolio owns effective-dated property ownership.
- Leasing owns effective-dated tenant participation.
- Communications owns immutable interaction records, participants, and generic context links.
- Future Security owns authenticated users and authorization roles; MAINT-004 must not create an early user or workforce subsystem.

This is a backend/API design. `UI-001` owns the deferred operator interface. No application code is included here.

## Current implementation baseline

MAINT-001 is implemented with required property context, optional space context, `reported_at_utc`, lifecycle, appointments, cost context, evidence, expense links, task follow-ups, idempotent creates, audit, exact-schema validation, and bounded list/detail projections. Its current issue create contract has no reporter fields.

The reusable identity and relationship facts currently available are:

- `parties` provides stable person or organization IDs, display names, contact methods, archive state, and batch reads.
- Portfolio records effective-dated `client_owner` relationships and a special `local_operator` ownership whose `party_id` is intentionally null.
- Tenant profiles establish tenant eligibility, while lease participants establish the tenant party's effective-dated relationship to a leased space.
- COM-001 participants always reference a Party and may use communication-local role `reporter`.
- COM-001 links are generic but their current closed type set does not include `maintenance_issue`.
- The local application has one audit actor, but it has no manager profile, staff profile, workspace-user ID, or saved operator display name. Future `SEC-001` and `SEC-002` are intentionally outside the local MVP.

These facts make owner and tenant attribution possible without copied identities. They do not yet establish a canonical identity for manager or staff reporters.

## Scope

MAINT-004 provides:

- exactly one authoritative reporter attribution for every official maintenance issue;
- the reporter role vocabulary `owner`, `tenant`, `manager`, and `staff`;
- a stable reporter subject reference and immutable display-name snapshot;
- role validation against effective-dated Portfolio or Lease facts where those facts exist;
- a confirmed, audited correction workflow that does not rewrite communication history;
- `maintenance_issue` as a valid COM-001 context-link target;
- issue-linked communication summaries in maintenance detail;
- reporter filters and projections for list, UI, AI handoff, and later repair reporting;
- exact-schema, audit, archive-validation, and encrypted backup/restore coverage.

MAINT-004 does not provide:

- a staff directory, manager employment records, authentication, authorization, or SaaS workspace users;
- owner or tenant self-service intake; `INTAKE-001` owns direct external submissions;
- message ingestion, sender matching, AI extraction, or duplicate detection;
- email/SMS delivery;
- editable copies of party names, contact methods, or communication bodies in Maintenance;
- multiple co-reporters on one issue;
- automatic reporter changes when ownership, leases, parties, or communications later change.

## Reporter model

### Reporter attribution is part of the issue aggregate

An issue has exactly one reporter attribution. It is not a separate aggregate because it has no independent lifecycle or meaning outside that issue. Storing it on `maintenance_issues` keeps issue creation atomic and avoids an extra join or abstraction on every list and detail read.

The attribution contains:

- `reporter_role`: `owner`, `tenant`, `manager`, or `staff`;
- `reporter_subject_kind`: `party` or `local_operator`;
- `reporter_party_id`: required only for a Party subject;
- `reporter_display_name_snapshot`: the bounded name shown when the attribution was recorded or corrected.

The Party remains the reusable identity source. The snapshot preserves historical readability after a rename or archive and follows the existing COM-001 participant-snapshot pattern. Maintenance does not copy email, phone, contact preference, tenant notes, ownership terms, or lease details.

`local_operator` is a typed subject variant, not a fake Party ID and not the audit actor string. It exists because self-owned Portfolio relationships already use `local_operator` with no Party record. The server snapshots the bounded workspace-level operator display name when that future Settings value is configured; until then it snapshots the exact fallback `Local operator`. It never infers a name from the operating-system account or audit actor.

### Reporter role is contextual, not a global Party role

`reporter_role` records the capacity in which the subject reported this issue. It does not add `owner`, `tenant`, `manager`, or `staff` to `parties.party_kind`, and it does not imply a global authorization role.

Owner and tenant attributions are verified against source-owned relationship facts at the issue's property-local reported date:

| Reporter role | Validation |
| --- | --- |
| `owner` + Party | The Party has a `client_owner` relationship to the issue property on the reported local date. |
| `owner` + local operator | The property has `local_operator` ownership on the reported local date. |
| `tenant` + Party, space issue | The Party is an effective lease participant for that exact space on the reported local date. |
| `tenant` + Party, property issue | The Party is an effective lease participant for at least one space at that property on the reported local date. |
| `manager` or `staff` | The subject must be `local_operator` in the local MVP. The selected role records the capacity in which that operator reported the issue. |

A tenant reporter must have the required historical lease participation; an active tenant profile alone does not establish which property the person occupied. A current Party rename, archived tenant profile, ended lease, or ended ownership does not invalidate a retained attribution that was valid on its reported date.

Normal operator-entered creation selects an active Party. A currently archived Party may be selected only for a backdated issue when its source-owned relationship was effective on the reported local date and the request includes explicit historical-selection confirmation and a bounded reason. The server retains the archived Party snapshot and does not restore the Party, profile, ownership, or lease.

### Reporter attribution does not derive from communication

Maintenance is the source of truth for the issue reporter. COM-001 participant role `reporter` says how a Party participated in one communication; it does not establish or change the issue's authoritative reporter role.

COM-001 gains `maintenance_issue` as a generic link target. A communication linked to an issue remains owned and corrected by Communications. An issue may have zero or more linked communications, and each communication may include the issue reporter or other participants. Maintenance detail obtains linked communication summaries through a consumer-neutral, transaction-aware Communication reader.

For a Party reporter, UI-001 should prefill the same Party as a `reporter` participant when recording the originating communication. The server must not rewrite an immutable communication merely because issue attribution is later corrected. A mismatch remains visible history rather than being silently normalized.

A local-operator subject cannot be a COM-001 participant in the local MVP because COM participants require Party IDs. The linked communication still appears in issue history. A later workspace-user identity design may add an authenticated operator participant type, but MAINT-004 does not create a fake Party or broaden COM-001 participation now.

### Reporter correction is explicit and audited

Reporter fields are not changed through the general issue patch endpoint. A dedicated correction command requires:

- an existing issue;
- the complete replacement reporter attribution;
- `confirmed: true`;
- a bounded correction reason;
- the same relationship validation used by issue creation, evaluated at the issue's original reported date.

The current issue row is updated in place and one correlated `maintenance_issue` audit event with action `reporter_corrected` retains the before and after attribution. Existing communications, intake sources, tasks, appointments, and financial links are not modified. A semantically identical correction is rejected as a no-op rather than adding misleading history.

### Official issue creation requires attribution

Once MAINT-004 is implemented, every new `POST /api/maintenance-issues` request requires a reporter object. The existing MAINT-001 idempotency fingerprint includes that complete reporter input. Reusing an issue-create key with changed attribution returns the existing typed idempotency conflict.

Draft ingestion and AI suggestions may hold unresolved or suggested reporter text, but they cannot create an official issue until the operator selects a valid reporter subject and role. Unknown or anonymous is deliberately not added to the official role vocabulary because the Product Brief says every issue records a reporter and one of four roles.

## Data model extension

The current-baseline `maintenance_issues` extension is:

| Field | Rule |
| --- | --- |
| `reporter_role` | Required `owner`, `tenant`, `manager`, or `staff`. |
| `reporter_subject_kind` | Required `party` or `local_operator`; `manager` and `staff` require `local_operator`, `tenant` requires `party`, and `owner` permits either. |
| `reporter_party_id` | Party foreign key exactly when subject kind is `party`; null for `local_operator`. |
| `reporter_display_name_snapshot` | Required trimmed display text, 1–240 characters. Generated by the server, never accepted as free-form identity input. |

Database constraints enforce the closed vocabularies, nonblank snapshot, subject/Party null pairing, and role/subject combinations. Application policy enforces effective dates, property/space relationship, Party lifecycle, historical-selection confirmation, and the source-owned owner/tenant relationships.

Indexes support `(reporter_role, status, reported_at_utc)` and `(reporter_party_id, reported_at_utc)`. The fields join the existing issue create audit snapshot, exact-schema validation, retained-data validation, backup, export, and restore. No separate reporter table or reporter repository is introduced.

Reporter references are historical facts and do not block Party archival. The stable Party row remains present after archive, and the issue snapshot remains readable. Maintenance registers no new Party-role activity or contact-reference guard because it owns neither an active Party profile nor a preferred contact method.

## Application and module boundaries

The Maintenance application service owns the policy and consumes small, neutral transaction-aware facts:

- Party operations: load one Party for creation/correction, enforce the active-versus-confirmed-historical rule, and batch current Party states when detail needs them.
- Portfolio context: return effective property ownership facts for a date, including `local_operator` and `client_owner` subjects.
- Lease context: return effective participant facts for a Party, property/space, and date.
- Communication link reader: return bounded counts and summaries keyed by `maintenance_issue` IDs.
- Audit recorder: append the reporter create/correction facts in the caller's transaction.

Portfolio and Lease readers must expose neutral relationship facts; they must not contain `maintenance_reporter_eligible()` or maintenance-specific response objects. Communications must expose generic link summaries rather than a Maintenance projection. Maintenance maps those facts into reporter eligibility and issue responses.

The existing source-owned readers are close but incomplete:

- `SQLitePortfolioContextReader.party_owned_property_on()` covers a Party client owner but does not return local-operator ownership or batch ownership facts.
- `SQLiteLeaseContextReader.participant_active()` requires a known lease ID and cannot answer property/space participation directly.
- COM-001 has no reusable transaction-aware batch reader for communications by linked entity.
- Party transaction operations already provide the identity fact needed for one write; Party batch reads already exist for projections.

Add the smallest neutral single/batch reader methods needed by Maintenance, preserve the caller-owned SQLite transaction, and assert fixed query budgets. Do not place maintenance-specific operations inside Parties, Portfolio, Leasing, or Communications.

### COM-001 extension

MAINT-004 extends COM-001's generic link vocabulary and database check with `maintenance_issue`. The composition adapter validates that the issue exists and returns its property time-zone snapshot for COM-001's occurrence-date rules. Communication create, correct, list, detail, audit, schema validation, and archive validation then treat the link like other typed context links.

This extension does not make Communications depend on Maintenance policy. The generic Communication service continues to validate an allowed link type through its context protocol; the composition layer supplies the target lookup. No `maintenance_operations.py` or reporter policy belongs in Communications.

## API contract

### Reporter input and response

Issue create adds a required reporter object:

```text
reporter: {
  role: "owner" | "tenant" | "manager" | "staff",
  subjectKind: "party" | "local_operator",
  partyId?: UUID,
  historicalSelectionConfirmed?: boolean,
  historicalSelectionReason?: string
}
```

The two historical-selection fields are accepted only for an archived Party on a backdated issue; they must either both be absent or be `true` plus a bounded reason. They are included in the issue-create idempotency fingerprint and audit context but are not stored as current reporter fields. The server resolves `reporterDisplayName` and never accepts a caller-provided name in place of a stable subject. Issue list/detail responses add:

```text
reporter: {
  role,
  subjectKind,
  partyId,
  displayName,
  currentPartyState?
}
```

`currentPartyState` may indicate `active` or `archived` for a Party subject. It is current context, not part of the historical attribution snapshot.

### Endpoints and filters

| Method | Path | Change or intent |
| --- | --- | --- |
| `POST` | `/api/maintenance-issues` | Require and validate reporter attribution as part of the existing idempotent create. |
| `POST` | `/api/maintenance-issues/{issueId}/reporter/correct` | Confirm and audit a complete reporter replacement with reason. |
| `GET` | `/api/maintenance-issues` | Add `reporterRole`, `reporterPartyId`, and `reporterSubjectKind` filters and reporter summary output. |
| `GET` | `/api/maintenance-issues/{issueId}` | Return reporter detail and linked communication summaries. |
| `POST/GET` | Existing COM-001 endpoints | Accept and filter `entityType = maintenance_issue`. |

Malformed reporter shapes return `422`; missing issue, Party, property, space, or relationship sources return controlled `404` where appropriate; unsupported role/subject combinations and invalid business relationships return `400`; changed idempotency payloads, stale corrections, and concurrent changes return typed `409`.

## Read behavior and performance

Issue list projection includes only the stored reporter snapshot and role. Filtering uses Maintenance-owned indexed fields and adds no cross-module query.

Issue detail may include current Party state and a bounded recent communication summary. Page/detail projections must remain set-based:

- Party contexts are fetched once for all distinct reporter Party IDs.
- Communication counts/summaries are fetched once for all issue IDs through the generic link reader.
- Ownership and lease relationship queries run only for create/correction validation, not for every list row.
- Historical display always uses the stored snapshot, so an archived Party never creates an N+1 fallback.

Default communication history remains available from COM-001's cursor endpoint filtered by `maintenance_issue` and issue ID. Maintenance detail should include only a bounded summary, not duplicate the complete ledger.

## Audit, privacy, and portability

Issue creation records reporter role, subject kind, stable Party ID when present, and display snapshot in the existing atomic `maintenance_issue` event. Reporter correction records one before/after event and its reason in the same immediate transaction as the issue update.

General activity may expose the reporter role but redacts Party ID, reporter display name, historical-selection reason, and correction reason. Contextual maintenance history may reveal the full permitted attribution. Communication bodies and contact values remain governed by COM-001 and are never copied into maintenance audit snapshots.

Exact schema and archive validation verify:

- reporter vocabulary and subject/Party pairing;
- nonblank bounded snapshots;
- referenced Party existence for Party subjects;
- required create audit attribution and correction history;
- valid `maintenance_issue` communication links and retained time-zone snapshots;
- stable reporter attribution and linked communication history through encrypted backup/restore.

Restore validation checks retained structural integrity. It must not re-evaluate historical ownership or lease eligibility against today's lifecycle state.

## Implementation outline

1. Extend Maintenance issue commands, fields, checks, indexes, schema validation, audit policy, responses, filters, historical-selection confirmation, and correction workflow.
2. Add the described neutral Portfolio ownership and Lease participation single/batch facts and compose them into Maintenance without importing their persistence models.
3. Extend COM-001 with the generic `maintenance_issue` link type, composition-side validation, archive checks, and a neutral batch link-summary reader.
4. Add bounded reporter and communication projections without changing MAINT-001's page query behavior.
5. Update the greenfield current-baseline workspace schema and rebuild development workspaces and fixtures; no customer-data migration or temporary unattributed state is required.
6. Add unit/integration tests for role combinations, relationship dates, self-owned properties, corrections, idempotency fingerprints, archived historical selection, communication links, audit privacy, exact schema/data rejection, query budgets, and restore integrity.
7. Deliver the operator workflow through the already-expanded `UI-001` scope.

## Backend acceptance criteria

MAINT-004 backend/API scope is complete when:

1. Every newly created official issue has exactly one valid owner, tenant, manager, or staff reporter attribution.
2. Party identity is referenced rather than copied, while the bounded display snapshot preserves historical readability.
3. Owner and tenant roles are validated against the issue property/space and reported date using source-owned facts.
4. The approved local-operator manager/staff rule is typed and does not create fake Party or authorization records.
5. Reporter correction requires confirmation and reason, writes one atomic audit event, and never rewrites linked communications.
6. COM-001 can create, correct, list, filter, and validate communication records linked to `maintenance_issue`, and those links survive workspace backup/restore.
7. Maintenance list/detail and later report inputs expose reporter filters and summaries without N+1 queries.
8. Ingestion or AI workflows cannot create an official issue while reporter attribution is unresolved.
9. Audit presentation redacts reporter identity in general activity while contextual history remains useful.
10. Reporter attribution and communication links survive exact-schema validation and encrypted backup/restore with stable IDs.

The overall operator workflow remains pending until `UI-001` supplies issue intake, reporter selection/correction, and linked communication history.

## Contradictions and design decisions

The following contradictions or ambiguities were found during design review. The decisions below are now authoritative for MAINT-004 implementation.

### 1. Manager and staff identities do not exist in the local model

The backlog requires manager and staff reporters, but the current local application has no manager profile, staff profile, authenticated user ID, or workforce relationship. Future `SEC-001`/`SEC-002` identity and authorization are much later and must not become MAINT-004 dependencies.

Decision: restrict `manager` and `staff` to the typed `local_operator` subject in the local MVP. The selected reporter role distinguishes the operator's contextual capacity. External manager/staff identities require a later explicit workforce or workspace-user design.

### 2. The local operator has no canonical display identity

Portfolio deliberately represents self-ownership as `local_operator` with a null Party ID, and audit uses an actor label rather than a reusable identity. Requiring every reporter to be a Party would force a duplicate self Party and conflict with the current model.

Decision: use one bounded workspace-level operator display name when a separate Settings design provides it, with the exact fallback `Local operator` until then. MAINT-004 snapshots the resolved value and does not infer a name from an operating-system account or audit actor string. The fallback keeps MAINT-004 implementable without prematurely expanding workspace metadata.

### 3. Owner and tenant validation dependencies are missing from the MAINT-004 row

COM-001 proves that a Party exists but not that it owns or occupies the issue property. Correct role validation needs TEN-001/Party identity, Portfolio ownership, and LEASE-001 participation facts. MAINT-001 already supplies the property/space dependency, but MAINT-004 directly consumes Tenant and Lease contracts.

The backlog row now adds completed `TEN-001` and `LEASE-001` dependencies. Decision: add the small neutral Portfolio ownership, Lease participation, and Communication link reader extensions described above, preserve caller-owned transactions, and verify fixed query budgets. Do not add maintenance-specific source-module operations.

### 4. COM-001 cannot currently link a communication to a maintenance issue

The backlog promises attribution throughout communication and lists COM-001 as a dependency, but COM-001's current link vocabulary and database check omit `maintenance_issue`. Its participant role `reporter` is communication-local and cannot replace the issue reporter role.

Decision: MAINT-004 extends COM-001's generic link vocabulary and composition validator with `maintenance_issue` without reopening COM-001's broader scope. Authoritative role attribution stays in Maintenance and immutable communication participation stays in Communications.

### 5. Existing MAINT-001 issues have no reporter

The Product Brief says every issue records a reporter, but the implemented MAINT-001 schema has none. Adding required reporter columns needs an explicit transition policy.

Decision: no customer workspace requires migration. Update the greenfield current baseline with non-null reporter fields and rebuild development workspaces and fixtures. Do not introduce nullable reporter fields, a temporary `unknown` role, a reporter-review migration state, or inferred attribution from the audit actor or a communication participant.

### 6. Historical archived-Party selection is unspecified

A backdated issue may have been reported by a former tenant or owner whose Party is now archived. Current COM-001 requires active participants for new records, while retained history may reference archived identities.

Decision: allow an archived Party only through confirmed historical selection with a bounded reason and a relationship valid on the reported date. Retain the archived Party snapshot and do not restore unrelated Party, profile, ownership, or lease state automatically.

### 7. Property-level tenant eligibility is ambiguous

A property-level issue has no space ID, but tenant participation belongs to a lease for a space. Decision: any effective tenant participation at that property on the reported local date is sufficient. Exact-space participation remains mandatory when the issue has a space.

### 8. Communication history may be empty

The Product Brief requires communication history as part of issue records but does not say every manually entered issue must begin with a communication. Requiring one would fabricate a communication for an operator-observed problem or couple two independent create workflows.

Decision: allow zero or more linked communications. Show an empty history explicitly and require a source communication only in future ingestion workflows that actually originate from a message.

### 9. Downstream backlog dependencies omit MAINT-004

`ISSUE-AI-001` drafts a reporter, `INGEST-002` creates or updates an issue after review, and `RPT-001` promises repair reporting, but their original dependencies did not all include the authoritative reporter contract. The backlog now adds MAINT-004 to these three items so AI drafts remain suggestions, approved issue creation supplies valid attribution, and repair reports can filter or display reporter facts.

## Dependencies and follow-on work

MAINT-004 requires completed `TEN-001`, `LEASE-001`, `COM-001`, and `MAINT-001`. Through those features it uses the existing Party, Portfolio, Audit, workspace, and backup foundations.

Follow-on ownership remains:

- `UI-001` — reporter selection, correction, relationship feedback, and linked communication history.
- `RPT-001` — repair reporting and drill-down using Maintenance-owned reporter facts.
- `ISSUE-AI-001` and `ISSUE-AI-002` — suggested reporter text, role, Party/property/space matches, and duplicate candidates.
- `INGEST-002` — operator-approved conversion from source/draft records to official attributed issues.
- `INTAKE-001` — direct owner/tenant submissions after authentication and external intake controls exist.
- `SEC-001` and `SEC-002` — future SaaS user identity and authorization; they do not retroactively redefine local reporter history without a migration design.

MAINT-004 introduces no staff directory, employment model, or authorization role. If the recommended local-operator rule is rejected, a separate identity/workforce prerequisite must be designed before implementation.
