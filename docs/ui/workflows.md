# Operator workflows

Each workflow uses the owning module's commands, revisions, confirmation rules and immutable original receipts. Browser forms use generated contracts and registered Operator recovery. Consult the linked module for domain policy and the linked source for exact current forms/routes; these guides replace backlog slice narratives as the developer entry point.

## Create and edit completion

Standalone record create/edit workflows replace their editor with `SavedCommand`/`SavedItem`: a contextual success heading, readable saved business data, and an explicit **Back to [item]** button. Property creation/editing no longer redirect automatically. Return navigation targets the item (or its owning record for a child) without adding the completed form as a new parent. Embedded Task quick-add, AI connection creation and AI draft edits use the same presentation inside their enclosing content, without page navigation. AI controls allow an explicit new connection or return to draft review.

Completion appears only after the existing command/recovery contract acknowledges success. Details come from the immutable owning receipt, not a fresh mutable item read. If that read fails, keep the success confirmation and offer a read-only retry; never resubmit the mutation. Unknown outcomes and validation/conflict failures keep the original form and recovery actions. Lifecycle commands use the same saved-data presentation with a contextual completion heading. Filter forms, immediate settings toggles and write-only credential controls retain their existing behavior.

Forms collect missing-field feedback with operator labels and move focus to the error summary after a failed submission. Routine chrome omits source revisions, attempt identities and API field/unit boilerplate. Information review uses the same bottom action row: **Record review** and **Save unfinished form**. Calendar dates display as `Oct 1, 2026` without changing their source day; instants use browser-local time; monetary displays use grouped `USD 1,950.00` while request values retain their original numeric units.

Every recoverable form shows saving, saved or failed feedback beside its action row. **Unfinished form saved** includes the saved time; the draft-save button reads **Saved** until another edit needs saving. Date/time filters use browser-local controls and send zoned instants. Settings distinguishes the automatically saved Home refresh interval from appearance and navigation choices saved with **Save preferences**.

New maintenance issues, owner concerns, conversations and owner rent reports use the owning service's UTC clock. Their browser forms omit **Reported at**, **Raised at** and **Occurred at**; owner reports still collect the payment's **Received on** date. Edits preserve the original event time, as do conversation corrections; a replacement owner report receives its own report time. Generated browser contracts also omit these fields when recovering saved input. Application/API integrations may still supply an explicit historical instant. Missing times remain `null` in canonical command identities and are resolved only for persistence, so retries recover the original timestamp rather than creating a new request identity.

| Server-time validation boundary                                                            | Focused proof                                                                                             |
| ------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------- |
| Inputs absent; new issue/concern times match recorded time; same-key replay                | `saved-results.spec.ts`; owning-module server-time tests                                                  |
| Conversation create/edit/correction, lost-response recovery; journal event input unchanged | `work.spec.ts`; Communications server-time test                                                           |
| Owner report create/edit/replacement; payment date unchanged                               | `money.spec.ts`; Owner-accounting server-time test                                                        |
| Omitted timestamps through attempt preparation, retained validation and encrypted restore  | Operator `test_concern_recovery.py`, `test_financial_batches.py`; owning-module retained validation tests |

This changes command defaults, not table schemas or content publication. Existing rollback, query-budget and attachment tests remain the authority for those unchanged boundaries.

**Unfinished forms** lists only active drafts and submissions whose outcome is unknown. Drafts can be discarded directly; unknown submissions must be checked before further action. Reconciliation removes a finished submission from this queue without deleting its audit/recovery record. Original committed responses remain accessible through their owning record's History/recovery contracts, not a duplicate permanent receipt list here. Each form has one resume destination, including Information review.

| Validation boundary | Focused proof |
| --- | --- |
| Missing fields, invalid input, focus and no mutation | `form-feedback.spec.ts` |
| Manual save and autosave acknowledgment beside actions, saved time and button state | `form-feedback.spec.ts`; `search-coverage.spec.ts` |
| Bounded property choices; local date filters, daylight-saving gaps and retained offsets | `dynamic-filters.spec.ts` |
| Actionable queue, discard, one review resume link, local saved times | `recovery-page.spec.ts` |
| Retry/reconciliation and retained receipt after queue removal | Operator `test_command_recovery.py`; `test_operator.py` also covers rollback, schema/backup, bounded pagination and query budget |
| Review action row and saved-form recovery | `search-coverage.spec.ts` |
| Named payer choices and inspection participants; existing IDs preserved internally | `money.spec.ts`, `leasing-inspections.spec.ts` |
| One tenant/provider profile action; ID editing/recovery unchanged | `tenant-ids.spec.ts`, `provider-ids.spec.ts` |

Presentation-only changes do not alter domain writes, receipt formats, lifecycle rules, schemas or backup formats; the server-time defaults above change command admission without changing storage formats. List filtering stays in SQL before pagination/counting, and added name lookups use the bounded batch-name port rather than one query per row.

Presentation omits operation/record UUIDs, revisions, fingerprints and raw JSON. Instants use browser-local time; date-only values remain unchanged and minor-unit amounts are formatted as money. Official IDs use the shared masked/reveal presentation. Existing original-result APIs, persistence and backup contracts are unchanged. Superseded one-line success displays, Property redirects and Ownership confirmation-only editor branches are removed.

Money details select business fields by record and child type. Relationships and correction chains use named links instead of UUID facts; optional interest calculations show percentages and labelled days separately. Primary lifecycle actions are visible buttons on the relevant record, not a collapsed Actions group. Secondary destructive actions and history may remain disclosed.

| Area | Delivered journey and boundaries | Authority / implementation |
| --- | --- | --- |
| Portfolio | Property/Space create/edit/lifecycle, ownership, manual occupancy/availability, progressive setup and contextual history. Unknown status stays unknown. | [Portfolio](../modules/portfolio.md); [portfolio.tsx](../../application/apps/web/src/workflows/portfolio.tsx) |
| People | Shared Party/contact creation and correction, Tenant designation/profile/preferences/lifecycle, identity/duplicate guards. | [Parties](../modules/parties.md), [Tenants](../modules/tenants.md); [identity.tsx](../../application/apps/web/src/workflows/identity.tsx) |
| Providers | Profiles, multi-category assignments, services/areas, history, references/reputation and archive/restore. Providers remain accessible from Maintenance. | [Providers](../modules/providers.md); [providers.tsx](../../application/apps/web/src/workflows/providers.tsx) |
| Leasing | Bounded directory, drafts, participants, terms, execution, renewal, termination negotiation/completion, move-out and history. Lease and Space revisions remain independent. Execution leaves rent synchronization as an explicit separate step. | [Leases](../modules/leases.md); [leasing.tsx](../../application/apps/web/src/workflows/leasing.tsx) |
| Inspection | Templates/checklists, separate move-in/move-out observations, acknowledgment, finalization/correction, comparison and evidence archival. Required acknowledgment membership uses walkthrough-active participants; correction remains a draft. An Inspection failure does not hide a committed Lease. | [Inspections](../modules/inspections.md); [inspections.tsx](../../application/apps/web/src/workflows/inspections.tsx) |
| Rent and checks | Synchronize schedule with explicit anchor; record receipts/allocations and partial balances; void/replace correction; scheduled check deposit/return/replacement. A scheduled check is not received rent. | [Finance](../modules/finance.md); [money.tsx](../../application/apps/web/src/workflows/money.tsx) |
| Expenses and deposits | Actual expense/refund/category workflows, supporting evidence, deposit account and settlement draft/approval/refunds/completion. Evidence-backed deductions require review; inspection findings never automatically become deductions. Separate evidence failure preserves committed money. | [Finance](../modules/finance.md); [money-records.tsx](../../application/apps/web/src/workflows/money-records.tsx) |
| Owner rent reports | Create/edit/reject and compare verification against an existing receipt or explicit new receipt. Review both report and ledger revisions; keep one Finance receipt. | [Owner accounting](../modules/owner-accounting.md); [money-command.tsx](../../application/apps/web/src/workflows/money-command.tsx) |
| Reporting | Explicit-period FIN-003 source/property pages, USD formatting and source drill-down. Changed-view restart retains filters; Owner reporting requires explicit related Property, not inferred entitlement. | [Finance](../modules/finance.md); [money-reporting.tsx](../../application/apps/web/src/workflows/money-reporting.tsx) |
| Repairs | Issues, reporter attribution, appointments, costs, quotes/comparison, assignment, expense links, journal, evidence and follow-up. Task/appointment completion and reported work do not verify physical repair. | [Maintenance](../modules/maintenance.md); [work.tsx](../../application/apps/web/src/workflows/work.tsx) |
| Tasks and concerns | Task edits/lifecycle/reminders/deletion, independent waiting/follow-ups and owner concerns with related source context. Lost deletion recovers original receipt despite missing live Task. Waiting preserves original urgency/deadline. | [Tasks](../modules/tasks.md), [Owner management](../modules/owner-management.md); [work-records.tsx](../../application/apps/web/src/workflows/work-records.tsx) |
| Conversations | Manual interaction record/edit/correction/history and optional linked Task. This does not send messages or approve intake proposals. | [Communications](../modules/communications.md); [work.tsx](../../application/apps/web/src/workflows/work.tsx) |
| Manual Intake | Conversations → Retained sources: bounded directory, admission/import/correction/supersession/dismissal/reopening and source history. Full content uses fail-closed audited reads. Ordered file roles/digests are retained; byte recovery needs reselection. Failed/superseded sources retain history with guarded mutations. | [Intake](../modules/intake.md); [intake.tsx](../../application/apps/web/src/workflows/intake.tsx) |
| Search and Information review | Grouped literal metadata search, independent paging/retry, typed source links; source-backed gaps/reviews, reasons/dates and recoverable review receipts. Required gaps survive acknowledgment. The UI calls the internal `coverage` feature Information review; URLs and API identifiers are unchanged. | [Operator](../modules/operator.md); [search.tsx](../../application/apps/web/src/shared/search.tsx), [coverage.tsx](../../application/apps/web/src/shared/coverage.tsx) |
| AI Settings/review | Off/device/cloud choices, registry-bound connections/models/actions, data-class disclosure, write-only secrets, synthetic probes, limits/redaction/global pause; frozen provenance/input, edit/history and saved-payload review. Approval requires registered handler, current source and acknowledged saved version. Secret effects retain explicit uncertainty acknowledgment and original keys. | [AI governance](../modules/ai-governance.md); [ai-governance.tsx](../../application/apps/web/src/workflows/ai-governance.tsx) |

## Completion and record-detail validation

| Boundary | Focused proof |
| --- | --- |
| Completion and privacy | `saved-results.spec.ts`, category archival in `workflows.spec.ts`, participant removal in `leasing-inspections.spec.ts`: readable immutable results, no technical identity facts, browser-local instants, narrow/light/dark layouts. |
| Retry and conflicts | Lost participant removal and Information review responses reconcile once; stale manual status/review inputs remain editable. A saved-detail read failure offers a read-only retry, not another mutation. |
| Money presentation | `money.spec.ts`: one labelled payment status per allocation, exact money and named related-record links; optional interest detail uses percentages. Check, report and deposit actions are directly reachable. |
| Action accessibility | `acceptance.spec.ts` plus Task, concern, renewal and inspection workflow tests: visible native buttons, keyboard navigation, narrow layouts and existing lifecycle guards. |

These are presentation-only changes. Persistence/schema, transaction rollback, backup/restore and query-budget contracts are unchanged; saved details still use one existing owning-operation read rather than per-field lookups.

## Home foundation and deferred work

[Shared attention/calendar components](../../application/packages/ui/src/attention.tsx) provide source-supplied reasons, totals, timestamps, all-day dates and explicit timed zones through independent disclosures. Live Task deadlines/waiting directories consume them. [Home](../../application/apps/web/src/shared/home.tsx) delivers bounded source-backed attention, agenda, information review, money and inventory; [DASH-001](../archive/designs/DASH-001_DESIGN_COMPLETED_2026-10-14.md) records the accepted live composition.

The installation currently has no registered production model adapters/actions/approval handlers; Settings and generic review infrastructure do not establish production generation/approval. [UI-002](../active/UI-002_DESIGN_preliminary.md) retains issue-proposal approval, assistant setup, legal/HOA and spreadsheet work. Owner statements/disbursements/fees retain their separate backlogs.
