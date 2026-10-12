# AI-GOV-001 — remaining delivery and acceptance

## Current boundary

The implemented backend is described in [AI configuration, generation and review boundaries](../modules/ai-governance.md). This document tracks remaining acceptance; it does not restate a pre-implementation baseline. The backlog currently records **🟡 In progress — pending UI**.

Remaining browser workflow delivery is owned by UI-001 Slice 55, followed by Slice 57 integration acceptance. Backend registration and receipts alone do not complete the operator workflow.

## Remaining work

Truthful Off/device/cloud capabilities, connection disclosure/credentials/probes, limits/global pause and supported draft review only when release registries contain owning actions/handlers.

Preserve displayed revisions, strict validation, source membership, original-key reconciliation, accessible confirmations and dirty-input recovery. Verify critical paths against real temporary workspaces.

The retained requirements below remain acceptance constraints. Backend requirements are represented by the current module and executable tests; their presence here does not assert they are unimplemented or newly verified.

## Acceptance constraints to verify

- Exact-schema and retained-data validation cover all eight tables and their lifecycle/correlation invariants.
- Synthetic registered actions prove redaction, exact provider-input retention, output validation, draft creation, editing, generic dismissal, domain-owned dismissal, single-mode and multi-mode approval handoff, audit history, and backup/restore without creating a production AI feature.
- Unknown actions, provider/model/profile versions, extra fields, secrets, oversized context, and malformed outputs fail closed.
- Kill switch, destination-bound disclosure permission, disabled action, UTC-day cap, prompt cap, completion cap, registered adapter, and action/model capability allowlist are enforced atomically before provider access.
- Concurrent duplicate submissions make at most one provider call; same-key/different-request conflicts are stable and typed.
- Provider calls occur outside SQLite transactions; interruption recovery leaves no indefinitely running row.
- Terminal drafts are immutable; supersession is acyclic and non-branching; stale-source approval cannot create an official record.
- Approval writes the selected allowed mode, official record when applicable, review decision, terminal draft state, and all correlated audit events in one owning-domain transaction.
- Credential values are absent from SQLite, audit snapshots, logs, API responses, backups, exports, and restored workspaces.
- Backup/restore preserves stable IDs, exact redacted inputs, payloads, history, lineage, settings, and limits.

## Validation and delivery references

- [Current module and focused tests](../modules/ai-governance.md#validation).
- [Shared validation matrix](../platform/persistence.md#validation-matrix).
- [Current operator experience](../ui/operator-experience.md) and [delivery evidence](../ui/validation.md).
- [Historical full design](../archive/designs/AI-GOV-001_DESIGN.md) for decision rationale and original contract detail. It is a planning snapshot, not the current implementation reference.

Outstanding review findings remain in [pending_code_review_comments](../pending_code_review_comments); this documentation change does not resolve them.
