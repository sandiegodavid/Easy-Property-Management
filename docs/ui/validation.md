# Browser validation and delivery evidence

## Evidence boundary

UI-001's delivery matrix records backend readiness through Slice 43 and browser delivery/acceptance through Slice 57 on October 12, 2026. This consolidation preserves that evidence; it does not rerun tests or close pending review findings. Later changes require focused regression validation and the repository quality gates.

## Executable entry points

Paths below are relative to `application/apps/web/`. Packaged browser cases use real temporary workspaces for persistence/recovery. Mocked unavailable/partial states complement these cases; they do not prove commits. Shared component fixtures test disclosure, forms and recovery without claiming a live Home aggregate.

| Boundary | Test entry points / recorded proof |
| --- | --- |
| Packaged transport | `tests/delivery.spec.ts`, `tests/acceptance.spec.ts`: compiled wheel assets, deep links, reserved paths/security headers and rejection of unrelated-origin multipart commands |
| Bootstrap/navigation | `tests/workspace-gate.spec.ts`, `tests/shell.spec.ts`, `tests/context-reads.spec.ts`: readiness, scope/runtime, themes, partial sections and bounded contextual reads |
| Portfolio/identity/providers | `tests/workflows.spec.ts`: current source context, lifecycle/child guards, saved forms and interrupted-command recovery; see the completed record for slice-specific cases |
| Lease/Inspection | `tests/leasing-inspections.spec.ts`: independent Lease/Space revisions, termination/renewal/move-out, participant-date acknowledgment, draft correction, original child-removal results, evidence reselection and directory cursor guards |
| Money | `tests/money.spec.ts`: partial rent/corrections, dual-revision report verification, checks/deposits/settlement/refunds, evidence partial success, original receipts and exact period source pages |
| Maintenance/communications/Tasks/concerns | `tests/work.spec.ts`: independent lifecycles, waiting/reminders, quotes/journal/expense links, child identity and deleted-Task result recovery |
| Search/coverage | `tests/search-coverage.spec.ts`: grouped paging/retry, typed navigation, required gaps, source review conflicts and original coverage receipt recovery |
| AI governance | `tests/ai-governance.spec.ts`: registry-bound synthetic capabilities, cloud disclosure, saved-payload approval gates, disabled/stale availability, secret-free recovery and explicit external-effect uncertainty |
| Home foundation | `tests/home.spec.ts`, `component-tests/attention.spec.ts`: live Task actions and unavailable aggregate, source-supplied queue/calendar fixtures, entire-bar disclosure, retained input and explicit zones |
| Manual Intake | `tests/intake.spec.ts`: admission/import/correction/supersession/dismissal/reopening, ordered role/digests, stale-source review, audited-read failure, reselection and bounded 30-record/two-page traversal |
| Accessibility/recovery | `tests/acceptance.spec.ts`, `component-tests/recovery.spec.ts`: keyboard/focus, reduced motion, 200% text reflow, Light/Dark WCAG automated checks at 390/900/1440px, serialized autosave/conflicting windows |
| Restart/encrypted restore | `tests/restart-restore.spec.ts`, `application/scripts/web_acceptance_restore.py`: committed lost Task response, one dispatch across restart, original receipt/saved form, stable workspace/evidence/Intake histories and changed runtime epoch |

Backend focused suites continue to prove owning schema, rollback, exact receipts and portable validation; links live in module guides. New boundary changes must extend the appropriate proof rather than assume old test counts apply.

## Maintenance validation

Select cases for happy paths; invalid combinations and source/child membership; revision conflicts and same-key original-result recovery; transaction rollback; retained-schema validation; backup/restore; bounded paging/query budgets; navigation, unavailable/stale states and accessibility. Mark actual results passed/failed/not run/not applicable with reasons. Run root frontend lint, formatting and complete type checking for frontend changes; run configured Ruff checks for changed Python. Do not relax rules to pass validation.

## Historical records

- [Completed design](../archive/designs/UI-001_DESIGN_COMPLETED_2026-10-12.md): preserved interaction decision IDs and technical rationale.
- [Completed browser matrix](../archive/implementation-plans/UI-001_IMPLEMENTATION_MATRIX_COMPLETED_2026-10-12.md): full slice-specific scenarios, dated results and command-safety inventory. Final acceptance recorded 119 browser cases, six shared component cases and six recovery cases; this is historical evidence.
- [Earlier backend matrix](../archive/implementation-plans/UI-001_IMPLEMENTATION_MATRIX.md): detailed source readiness sequence through the backend handoff.

The existing bundle-size warning was recorded as informational. No test execution or production model qualification occurred during documentation consolidation. [DASH-001](../active/DASH-001_DESIGN.md) and [UI-002](../active/UI-002_DESIGN_preliminary.md) have separate remaining acceptance.
