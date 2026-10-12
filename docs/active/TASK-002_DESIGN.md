# TASK-002 — remaining delivery and acceptance

## Current boundary

The implemented backend is described in [Tasks, reminders and waiting](../modules/tasks.md). This document tracks remaining acceptance; it does not restate a pre-implementation baseline. The backlog currently records **🟡 In progress — pending UI**.

Remaining browser workflow delivery is owned by UI-001 Slice 53, followed by Slice 57 integration acceptance. Backend registration and receipts alone do not complete the operator workflow.

## Remaining work

Waiting set/replace/clear, timed follow-up reschedule/date removal, visible unscheduled state and independent Task deadline/reminder facts.

Preserve displayed revisions, strict validation, source membership, original-key reconciliation, accessible confirmations and dirty-input recovery. Verify critical paths against real temporary workspaces.

The retained requirements below remain acceptance constraints. Backend requirements are represented by the current module and executable tests; their presence here does not assert they are unimplemented or newly verified.

## Retained operator requirements

UI-001 renders waiting context on the source task and in contextual record views. A waiting row identifies whom/what is awaited, the follow-up state, original deadline when present, and a clearly separate action to schedule or reschedule follow-up. It never presents a deferred reminder as resolved work.

DASH-001 may show the task in Waiting until the scheduled follow-up becomes due, then surface it in Needs action with the reason **Follow up with [label]**. Task urgency/overdue facts and separately available authoritative source urgency/deadlines govern placement and wording. A future follow-up today remains scheduled until its timestamp; undated waiting remains visible as Follow-up not scheduled.

## Acceptance constraints to verify

TASK-002 is complete when the typed persistence, audit, command, bounded read, and regression contracts described in the current module exist; all existing TASK-001 semantics remain intact; and UI/DASH consumers can distinguish waiting, due follow-up, unscheduled follow-up, and source urgency without client-side derivation.

## Validation and delivery references

- [Current module and focused tests](../modules/tasks.md#validation).
- [Shared validation matrix](../platform/persistence.md#validation-matrix).
- [Current operator experience](../ui/operator-experience.md) and [delivery evidence](../ui/validation.md).
- [Historical full design](../archive/designs/TASK-002_DESIGN.md) for decision rationale and original contract detail. It is a planning snapshot, not the current implementation reference.

Outstanding review findings remain in [pending_code_review_comments](../pending_code_review_comments); this documentation change does not resolve them.
