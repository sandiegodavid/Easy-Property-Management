# UI-002 Preliminary Operator Experience Design

## Status and delivery scope

This preliminary design preserves the confirmed spreadsheet-intake and source-backed issue-review decisions moved from UI-001. It is the working MVP design for UI-002, not an implementation-complete specification. Decision IDs and original validation scenario numbers remain stable. Dedicated domain designs own backend policy; [ARCHITECTURE.md](../ARCHITECTURE.md) governs the stack and trust boundaries.

UI-002 follows UI-001. Its prerequisites are DATA-002, DATA-003, and INGEST-002. Deliver Excel/Google Sheets onboarding intake and retained-evidence issue-proposal review. LEGAL-001 and HOA-001, including their Home and contextual workflows, move after MVP to [UI-004](UI-004_DESIGN_preliminary.md). Connected-assistant setup and health belong to UI-003; an EPM-invoked Draft follow-up can be delivered independently by AI-DRAFT-001. DASH-003 retains broader intake/assistant attention aggregation.

Reuse [UI-001's shell, navigation, components, accessibility, client architecture, and recovery contracts](../ui/frontend-architecture.md). Do not duplicate that specification or implement domain policy in the browser. Backend readiness and UI delivery registration must both permit a route. Unsupported deep links explain the missing capability and offer a safe return. Do not claim import capability before its UI is delivered or source-review availability before a proposal producer and the INGEST-002 workflow qualify.

## Confirmed product and interaction decisions

### Spreadsheet intake

#### D43: Import properties, owners, and providers from spreadsheets

Importing properties, owners, and providers from Excel and Google Sheets is a focused follow-up MVP intake capability, separate from DATA-001's broader later import of leases, balances, and operational history. D44 and D45 define source access and existing-record behavior.

Provide Import in each of the three directories and Settings → Import data. The proposed shared flow is Select source, Choose sheet, Map columns, Validate and review, Confirm import, Results. Offer templates with explicit property/owner relationship keys; preview source rows, field mappings, relationships, and intended operations before committing. Import owner identities before dependent property relationships within a coordinated batch. Reuse shared party identity for owners/providers rather than silently duplicating people or organizations.

Never invent required fields, infer ownership shares, or silently merge ambiguous identities. Unknown optional information stays unknown. Rows with missing required values or unresolved relationships cannot be committed as valid records. Use create/link/skip with explicit duplicate review per D45; general overwrite/update imports are outside MVP. Produce a row-level outcome report and recoverable import history; retries must not duplicate successfully imported records. Preview source values as a snapshot and avoid executing spreadsheet macros or treating formulas as app instructions.

#### D44: Support Excel uploads and direct read-only Google Sheets import

Support local Excel uploads and, during new-workspace onboarding, direct Google Sheets selection through temporary read-only authorization. Let the operator select the spreadsheet and worksheet and review a captured source snapshot before import. Import exactly the reviewed snapshot; rereading changed source values requires a new preview and fresh authorization if the prior session ended. Disconnect after source acquisition completes or is canceled; mapping, review and commit use the captured snapshot. Do not require a sheet to be published publicly, modify the source sheet, or introduce ongoing synchronization in MVP. Source authorization does not create an application user account; credentials follow existing local secure-storage boundaries.

#### D45: Create, link, or skip; never silently overwrite

MVP imports create new valid records or explicitly link/skip existing ones after duplicate review. Linking means reusing the selected identity or record to satisfy a relationship; it does not authorize changing its existing fields or merging identities. Conflicting or ambiguous matches require resolution before affected rows can commit. Preserve property-to-owner relationships through explicit mapping. Present row-level validation errors and final import results, including created, linked, skipped, and failed outcomes. Retry only unfinished work without duplicating successful writes. General existing-record overwrite/update behavior is deferred.

### Assistant boundary with UI-003

Connected-assistant setup, grants, preflight, health and recovery belong to [UI-003](UI-003_DESIGN_preliminary.md). UI-002 provides the same source-backed INGEST-002 review for any qualified producer; no proposal bypasses its five operator decisions. No connected assistant is required to implement and test the review contract with synthetic proposals.

## Feature ownership and backend readiness

Dedicated contracts take precedence over product descriptions where they provide more specific policy.

| Backlog item | Dedicated design | Owns |
| --- | --- | --- |
| DATA-002 | [Spreadsheet Intake](DATA-002_DESIGN.md) | Excel snapshot intake, create/link/skip decisions, commits, and outcomes. |
| DATA-003 | [Read-Only Google Sheets Intake](DATA-003_DESIGN.md) | Google Sheets authorization and immutable source snapshots. |
| INGEST-002 | [Issue Proposal Review](INGEST-002_DESIGN.md) | Retained-evidence comparison, operator decisions, and atomic issue-review outcomes. |

DATA-003 owns temporary read-only Sheets authorization during onboarding intake. DATA-001 retains broader later import/update scope. Moving a UI workflow does not mark a backend feature implemented.

### INGEST-002 — issue-review readiness and recovery (former Slice 40)

Moved from the UI-001 implementation matrix on October 9, 2026. This handoff
preserves the former planned Slice 40 identifier for traceability; it is UI-002
work, not an outstanding UI-001 readiness gate. INGEST-002 and AI-GOV-001 own
the backend contracts; UI-002 owns their operator workflow and OPS registration
integration. Existing domain scope and prerequisite order remain unchanged.

- Implement and verify the INGEST-002 decision modes: create an issue, link
  without mutation, update only explicitly selected mutable fields, dismiss as
  no issue, and discard for rework. Follow the dedicated design's reporter,
  target eligibility, reason and revision requirements.
- Complete the feature-specific AI-GOV-001 approval modes and owning handlers,
  Intake attention transitions and durable source-to-issue outcome. Validate
  exact source/evidence and draft freshness, plus target issue revision where
  applicable, on the caller-owned transaction. Maintenance effects, Intake
  attention, AI review, outcome and correlated audits commit or roll back together.
- Before registering issue-review OPS forms, deliver typed request/result/conflict
  contracts, canonical fingerprints and immutable original-result ID/key recovery.
  Reconciliation must return the original correlated outcome without re-running
  approval, disclosing evidence through a metadata-only reader, or reconstructing
  a receipt from current state. Preserve unresolved attempts until reconciled.
- Reuse the delivered generic AI review and local-operator Intake contracts from
  UI-001 Slices 29, 32 and 38. Those registrations do not establish readiness for
  issue-specific approval or consumer-owned dismissal. Approve the exact new
  OPS form batch before registration; no new mutation ledger or browser-owned
  domain policy is introduced.
- Enable retained-evidence comparison, operator edits, explicit decision controls
  and correlated outcome presentation only after backend readiness and UI-002
  route/action registration pass. Broader ingestion/voice/assistant attention
  aggregation remains DASH-003.

Validate all five decisions against real temporary workspaces, invalid/stale
combinations, same-key replay and changed-payload conflicts, lost-response
reconciliation, cross-module rollback, retained-schema integrity, encrypted
backup/restore and bounded evidence/outcome reads. Evidence disclosure retains
Intake's fail-closed read audit. Include keyboard/focus and UI-001 regression
checks before enabling the workflow; backend receipts alone do not deliver its UI.

## Technical implementation handoff

Add `features/imports` under the existing web app. Extend existing `ai-review`, `settings`, and source-action registries instead of creating another shell. Register only ready workflows.

| Route | Purpose |
| --- | --- |
| `/imports/:importId/review` | Frozen spreadsheet snapshot, mapping, duplicate decisions, validation, and commit result. |
| `/ai/review/:draftId` | Extend the existing typed review route with INGEST-002 issue-proposal handlers, retained evidence, provenance, and atomic outcome presentation. |
| `/settings/:section?` | Add onboarding Import data entry and temporary Google Sheets source authorization; connected-assistant Settings belong to UI-003. |

Use the shared disclosure, forms, error, recovery, and generated-client contracts from UI-001. Consequential import commits require a confirmation naming the operation and consequence. Import review displays the frozen snapshot, mappings, unresolved relationships/duplicates, create/link/skip decisions, validation, and row-level results. Reconcile lost responses with the original operation key before retrying; never repeat successful writes.

INGEST-002 review displays retained source evidence, proposed fields, operator edits, and provenance separately. Approval must use the domain-owned atomic operation and show its correlated outcomes. A proposal, chat approval, file delivery, or assistant grant never bypasses operator authorization within the application. Stale revisions preserve edits and offer source refresh/review; admission limits are not invented model token budgets.

### Implementation sequence and readiness

1. Verify UI-001 and the three named backend prerequisites, including revision/idempotency, evidence and transaction contracts.
2. Implement Excel/Sheets snapshot review and results using common import components.
3. Add INGEST-002 proposal review and outcome handlers independently of assistant connection setup.
4. Register ready capabilities and bounded source-backed review targets without exposing deferred legal/HOA routes.
5. Run real temporary-workspace integration, accessibility, failure/recovery, and UI-001 regression checks. Fixtures and simulated setup do not prove readiness.

Before each workflow is enabled, verify initial/empty/unavailable/stale states, supported narrow layouts, keyboard operation, and a real critical read/write path. Approval of this preliminary design does not make a domain capability ready. UI-003 separately qualifies connected-assistant controls and source-health claims.

## Validation matrix

| Area | Required validation |
| --- | --- |
| Happy paths | Excel/Sheets snapshot mapping and authorized import; exact-evidence issue-proposal review. |
| Invalid combinations | Ambiguous identities, unresolved relationships, stale evidence, unsupported source/client, unavailable/paused/revoked capability. |
| Idempotency and retry | Lost responses, duplicate sources, unfinished-row retry, durable receipts, original operation keys, no duplicated imports/issues. |
| Transaction rollback | Failed approval/import operation exposes no partial official state beyond the owning domain's declared atomicity; stage/result distinctions remain explicit. |
| Persistence/schema | Restart resumes durable review/drafts, frozen snapshots, provenance, source identity and typed links; generated contracts match domain schemas. |
| Backup/restore | Retained history and drafts survive; credentials/grants do not become usable; configuration returns to Setup required and unresolved outcomes are reconciled. |
| Query budget/N+1 | Bounded snapshot/review lists and independent continuations; exact matching totals; backend compositions avoid a request per displayed row. |
| UI regression | Core navigation, themes, disclosure, drafts, keyboard/focus, partial failures and existing UI-001 workflows remain functional. |

### Retained workflow acceptance scenarios

22. Preview a spreadsheet containing new records, likely duplicate shared identities, and properties referring to owners. Require explicit relationship/duplicate resolution, report invalid rows accurately, and verify retries do not duplicate imported records. Link/skip leaves existing fields unchanged.

24. Preview a read-only Google Sheets snapshot, then change the source externally before confirming the import. Import only the reviewed snapshot or require a refreshed preview; never silently substitute changed values. No source-sheet writes or ongoing synchronization occur.

## Visual reference and sources

The [operator experience prototype](../../demo/operator-experience.html) contains simulated Home/integration states and fictional data. It does not prove integration readiness or define domain contracts; feature designs and this delivery allocation govern deferred workflows.

- [Feature backlog](../FEATURE_BACKLOG.md)
- [Core operator experience](../ui/operator-experience.md)
- [Architecture](../ARCHITECTURE.md)
- [AI integration research](../research/AI_INTEGRATION_RESEARCH.md)
