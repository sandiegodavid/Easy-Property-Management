# LEASE-001 — completed acceptance, October 12, 2026

LEASE-001 is complete. Current behavior is consolidated in the [Lease module guide](../../modules/leases.md); the [original design](LEASE-001_DESIGN.md) retains requirements and rationale. Existing UI-001 delivery supplied the lifecycle forms. This acceptance pass closes the remaining document and contextual-display gaps without changing lease business rules, persistence or public APIs.

## Delivered scope

- Residential/commercial draft, participant, rent/deposit term, renewal, execution, end/terminate/void and negotiated termination workflows retain their existing source-owned commands and independent Lease/Space revisions.
- Detail distinguishes contract milestones from physical occupancy and shows authoritative Space status with its own failure state. The existing Inspection section supplies attention; rent and settlement remain separate Finance decisions.
- Lease and termination-case document panels use the shared recoverable FILE-001 upload command. Its generated browser allowlist now includes both supported targets. Original bytes must be reselected after restart; an interrupted response reconciles the original operation. Upload returns to Lease detail without mutating the Lease revision or lifecycle.
- Document lists retain unavailable active evidence without download actions. Selected metadata/history retains archived associations without per-file detail requests for the normal list.
- Termination detail exposes request explanations, clause references, proposal versions, fees, waiver/conditions, access arrangements and decision dates. Recording requests, proposals or documents does not end occupancy.

## Focused validation matrix

| Area | Evidence | Result |
| --- | --- | --- |
| Happy paths | Browser residential draft/participants/terms, commercial execution, renewal decisions, termination negotiation/completion, end/terminate/void and both document targets | Passed |
| Invalid combinations | Foreign children, incomplete drafts, stale Space revisions; Lease suite covers overlaps, source ownership, active Tenant checks, invalid move-out/reasons and positive USD rent | Passed |
| Idempotency and retries | Saved draft/child recovery; original lifecycle responses; document byte reselection and one upload after a lost committed response | Passed |
| Transaction rollback | Lease suite verifies Lease/source-timeline rollback, audit-failure rollback and immutable command receipts | Passed |
| Persistence/schema | Lease suite validates rent/currency checks, retained command histories and receipt immutability | Passed; no schema changes |
| Backup/restore | Real encrypted Lease history/document round trip preserves terms, participants, renewal, accepted termination, linked documents, occupancy audits and exact command responses | Passed |
| Query budgets | Existing bounded Lease directory/context/recovery tests; browser verifies no per-file metadata reads until a document is selected; Space context uses one source read | Passed |
| UI integration/accessibility | Independent Space/Inspection failure preserves Lease facts; unavailable document cannot open; commercial milestones and source drill-down pass keyboard/axe checks in both themes at 390px without horizontal overflow | Passed |

Commands run from `application/`:

- `node scripts/python.mjs -m pytest apps/server/app/modules/leases/tests -q`: **81 passed**.
- `npm run test:web -- apps/web/tests/leasing-inspections.spec.ts`: **23 passed** against the rebuilt and packaged web assets.
- `npm run test:web -- apps/web/tests/money.spec.ts --grep 'supporting evidence can be reselected'`: **1 passed**, protecting the existing shared upload/history workflow.
- Root `npm run lint` and `npm run typecheck`, changed-file Prettier checks and `git diff --check`: passed.
- Web workspace production build and direct wheel packaging: passed.

Root `npm run format:check` remains blocked by existing formatting in `demo/dataset.json` and `demo/README.md`. `npm run contracts:check` confirms the existing generated OpenAPI snapshot is stale after separate Home API changes, so normal contract-gated packaging is also blocked. Only the Lease target allowlist was regenerated from that retained snapshot; no public API changed. These adjacent artifacts were not modified. The full application suite and shared browser restore suite were not rerun.

Earlier delivery evidence remains in the [Lease command-readiness record](../implementation-plans/LEASE-001_COMMAND_READINESS.md) and [completed UI-001 matrix](../implementation-plans/UI-001_IMPLEMENTATION_MATRIX_COMPLETED_2026-10-12.md). Separate Inspection/Finance backlog items and review findings are not closed by this acceptance.
