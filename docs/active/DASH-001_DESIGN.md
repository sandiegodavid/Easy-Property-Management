# DASH-001 — Home attention and portfolio overview

Date: October 12, 2026
Status: Design decisions accepted October 12, 2026; implementation and validation remain pending.

## Purpose and boundaries

Home answers what needs attention now, what is waiting, and what happens next, with source-backed money and information coverage. It is a read composition over authoritative modules, not a new task store or workflow engine. An empty queue establishes only that no recorded work matches supported rules at the displayed instant.

This design follows [Architecture](../ARCHITECTURE.md), [Product brief](../PRODUCT_BRIEF.md), [Backlog](../FEATURE_BACKLOG.md), [Decisions](../DECISIONS.md), and the confirmed interactions in [UI-001](UI-001_DESIGN.md). Current behavior is documented in the [module guides](../README.md); accepted decisions here define required delivery; they do not establish existing capability.

DASH-001 delivers Needs action, Waiting, Upcoming, appointments, information review, inventory context and recorded-money summary. It consumes UI-001 forms, routes, disclosure, recovery and source commands. Legal/HOA extensions arrive with UI-002; showings with LEAD-002; intake/AI/assistant health with DASH-003; reports/value estimates with DASH-002. No mail polling, AI reasoning, background notifications, legal calculations, import or new domain lifecycle belongs here.

## Existing implementation and required extensions

| Boundary | Verified implementation | DASH-001 work |
| --- | --- | --- |
| Browser Home | `application/apps/web/src/shared/home.tsx` explicitly renders unavailable Home plus Task links. | Replace placeholder only when real contracts and adapters are ready. Reuse existing frontend workflows. |
| Operator composition | `operator/application/overview_service.py` captures one snapshot, independent section results and bound cursors for property/owner overviews. | Add portfolio-wide Home composition in Operator; do not call individual property overviews in a loop. |
| Context read shape | `platform/context_reads.py` provides bounded metadata pages, a two-part continuation and contextual scope. | Add a typed attention projection/window supporting global priority ordering, reasons, counts and temporal transitions. Existing context pages are not attention pages. |
| Tasks | `tasks/application/service.py::summary` exposes overdue/today/next7days/dueReminders; contextual summary and TASK-002 waiting exist. | Add caller-transaction portfolio attention facts, including unlinked Tasks and independent reminders; retain current summary behavior. |
| Maintenance | `maintenance/infrastructure/summary_reader.py` reads issues by reported time. Appointments exist in the owning domain. | Add priority-filtered issue and portfolio appointment projections, with exact counts; reported-time previews cannot find all urgent work. |
| Leases | `leases/infrastructure/summary_reader.py` returns contextual current leases by creation time. | Add end/review-date eligibility and expiry ordering; explicitly handle ended/terminated contracts and continued occupancy. |
| Finance | `finance/application/money_ports.py::MoneyContextReader` already accepts caller connection, instant and property relation. | Reuse it for money. Add bounded outstanding/due/late expectation facts; cash totals are not delinquency totals. |
| Owner reports and concerns | Owning services retain verification and concern lifecycles; concerns have contextual metadata reader. | Add attention projection for pending reports and unresolved concerns with source actions and grouping links. |
| Coverage | `operator/application/coverage_sources.py` batches area facts for bounded subjects. | Add exact portfolio membership/counts and paginated coverage review rows without calling one property overview per property or materializing all evidence. |
| Inventory | Portfolio owns occupancy, availability, property/space scope and time zones. | Supply set-based vacancy/unknown counts and typed filtered drill-downs. Never infer vacancy from missing leases. |

Paths in this table are relative to `application/apps/server/app/` unless otherwise stated. These gaps are part of DASH-001 implementation in the relevant owning packages; they do not reopen completed domain workflows or require migration compatibility.

## Operator experience

Use the existing warm neutral/teal theme and Light/Dark settings. Top: Home, visible portfolio/property scope, last updated, Refresh. Lead with Needs action and its exact count. Put Waiting and Upcoming underneath, with a compact appointment agenda alongside on wide screens and below on narrow screens. Information needing review remains visibly separate. Money and inventory are compact supporting summaries, not a wall of charts.

Initial lists show 5 rows, each with View all and the full matching count. Never cap the displayed count to the preview size. Urgent rows lead the Needs action list; if more than five are urgent, explicitly state the urgent total. No combined grand total across overlapping agenda and work collections.

Every row summary contains display-only source title, property/space, reason, time/status and chevron. The entire bar toggles inline details, with the UI-001 hint: “Click anywhere on an item’s summary bar to expand or collapse its details.” Enter/Space, visible focus, aria-expanded and independent expansion are required. Actions and navigation links live inside the expansion. Do not put a Record payment button inside the disclosure trigger.

Expanded details show all attention reasons, source dates, waiting context, next action and source links. Short actions may use the existing source form; substantial workflows open their dedicated page. Retain scope, scroll and return location. Home offers no generic Complete, Dismiss or Snooze operation for arbitrary source records.

Background refresh must not unmount dirty forms or move focus. Preserve edited rows, label changed source state, and offer refresh/reconciliation. If a row stops qualifying, retain its expanded editor until safely closed; it no longer contributes to the new server count. Collapse never saves or discards input.

### Nonblocking loading and latency

Dashboard reads are asynchronous from the browser. Render the shell, navigation and existing content immediately; Home fetching must not gate other routes or freeze disclosure, typing or source actions. Use the existing query layer with cancellation on scope/runtime changes, deduplicated requests and at most one in-flight refresh per query key. Discard late responses for superseded scopes. On the server, execute synchronous SQLite work in the supported worker/thread boundary; an async endpoint must not perform blocking database work on the event loop. Keep the transaction and connection in their owning worker. Asynchronous transport alone does not make expensive queries fast.

For an initial load, use stable section skeletons and announce loading without showing zero counts. During refresh retain previous content with its original timestamp and a quiet Updating indicator. After two seconds show “Still loading” with elapsed wait and access to other destinations. After a ten-second client wait, show a recoverable timeout with Retry; cancel where supported and prevent accumulating background requests. A timeout is not a successful empty result or proof of server cancellation. Filters and View all remain usable independently of unrelated requests. Source actions read current owning records even when the preview is older.

Measure end-to-end first-load, collection-page and refresh latency on the supported local setup with representative data. Initial acceptance targets: p95 Home and collection reads within one second, and shell/navigation feedback within 100 ms. Query-count budgets still apply. Include worker queue wait and database duration in measurement, without logging sensitive payloads. These are acceptance targets to validate, not measured performance claims.

### Conditional nightly snapshot tables

Start with indexed, bounded live reads. If representative measurement repeatedly misses the one-second p95 target or demonstrates disruptive loading/refresh delays after query optimization, add Operator-owned nightly snapshot tables for the expensive derived projections. This optimization is authorized conditionally within DASH-001; record the measurements and the chosen cached sections before implementing it. Asynchronous loading remains required with or without snapshots.

Snapshot tables are disposable read caches in the workspace database, never authoritative tasks, balances or source statuses. A published generation records workspace identity, projection version, source marker, scope/period, captured instant, build time, next temporal invalidation and completion state. Build from one consistent source read, stage a complete generation, then publish atomically through the existing single-writer boundary. Readers must never mix generations or consume partially built rows. Keep writes short and serialized; rebuilding must not hold a write lock throughout the expensive read or interrupt ordinary operator work. A source change between capture and publication makes the generation stale and ineligible for fresh results.

Refresh nightly at 02:00 UTC while the server runs, with one coalesced catch-up on startup if the scheduled build was missed. Do not imply that the computer wakes or work occurs with the server closed. Source mutations and time transitions invalidate relevant generations immediately; coalesce regeneration requests. Refresh requests prefer valid cache or a live read, and may request regeneration when expensive live fallback times out. Rebuild failure preserves the prior complete generation as explicitly stale, with retry guidance.

Nightly data alone cannot satisfy urgent repairs, payments, follow-up deadlines or current exact totals. Serve cached collections as fresh only when source marker, projection/scope/period and temporal validity match the request. Otherwise use a live read or disclose stale/unavailable state and suppress the zero-action assurance. Do not combine cached counts with live rows or sum live deltas without a separately validated reconciliation contract. Arbitrary date/property filters use live reads unless an exactly matching generation exists. Extend cursors with generation identity when reading cached pages; retain existing workspace/runtime/source/time validation.

Exclude disposable snapshot rows from portable archives and rebuild after restore; any schema registration, export filtering and retained-validator handling must be explicitly implemented and tested before enabling caches. If an archive format cannot omit them, accept only validated cache records as disposable and discard them before serving the restored workspace. Runtime changes invalidate all prior cache use. Retain only the current and previous complete generation per supported cache scope; no raw evidence, credentials or form input in caches.

## Source membership and classification

The source owner determines eligibility, terminal state, urgency, amounts, local dates and deadlines. Operator combines these facts into display collections. Accepted initial rules:

| Source | Needs action | Waiting / Upcoming | Exclusions and next action |
| --- | --- | --- | --- |
| Tasks/reminders | Active overdue or due-today Task, actionable follow-up, due undismissed reminder, or active undated nonwaiting Task. | Nonactionable waiting goes to Waiting; other future due dates go to Upcoming within horizon. Future waiting remains Waiting with scheduled follow-up. | Completed/cancelled/deleted Tasks excluded. Show source Task/reminder action; reminder identity remains separate inside the Task row. |
| Rent expectations | Positive source-computed outstanding amount due today or late. | Positive future due expectations within horizon go to Upcoming. | Exclude void/superseded/fully allocated expectations. Record payment or review rent in owning workflow. Pending reports/checks never reduce outstanding by themselves. |
| Repairs | Unresolved urgent/emergency issues always; other unresolved issues without an explicit active waiting follow-up remain actionable. | A nonurgent issue may be Waiting only through explicit linked Task waiting with no actionable source/Task reason. | Terminal issue excluded. Assignment or appointment alone does not prove waiting or completion. Review issue. |
| Owner rent reports | Pending verification reports. | Waiting only through explicit linked waiting support if such a link exists and no other action reason remains. | Verified/rejected reports do not stay pending. Review report, never quick-accept from a badge. |
| Owner concerns | Unresolved concerns by default. | Explicit linked waiting can move nonactionable concerns to Waiting. | Resolved/dismissed excluded. Review concern; Task completion does not resolve concern. |
| Lease review | Within 30 property-local days of recorded contract end: review current terms/renewal/move-out. Past end with continued occupancy remains review work. | Days 31–90 appear only when the selected horizon reaches them. | No inferred notice date or automatic termination. Do not invent expiry for open-ended contracts. Confirmed successor/closure must be considered by Lease projection. |
| Maintenance appointments | Scheduled appointment whose end passed without recorded completion/cancellation: review outcome. | Today/future appointments appear in agenda; future ones may also appear in Upcoming. | Cancelled/completed excluded. Completion does not resolve repair. |
| Coverage | Never classified as an overdue obligation merely because information is missing. | Missing required information or needs-review in separate Information needing review collection. | Recorded/not-applicable areas excluded from review list but included in coverage context counts. |

Needs action takes precedence over Waiting, which takes precedence over Upcoming for the same canonical row. Preserve every qualifying reason. A waiting follow-up rescheduled into the future cannot hide an overdue Task, due reminder, urgent repair or actual source deadline. Do not propagate a Task's waiting state to all records on its property.

Tasks retain TASK-001 semantics: a future timed deadline today still belongs to its today attention bucket, while a future timed waiting follow-up is not yet actionable. Distinguish “Due today at 4 pm” from “Follow-up scheduled at 4 pm”; do not turn both into an overdue label. Undated waiting remains Waiting with “Follow-up not scheduled,” never automatically acquires a deadline.

### Identity, grouping and counts

Use stable canonical keys `(sourceKind, sourceId)`; coverage keys include subject and area. Aggregate multiple reasons/reminders for the same Task into one Task row. Rent stays one row per expectation; do not merge different rent periods or leases into a misleading single balance.

An explicit owning relation from a follow-up Task to an issue/concern may attach Task reasons to that source row. Register which typed relation is eligible; generic same-property/lease context is insufficient. Count the resulting source row once per primary collection, retain child Task/reminder IDs, and expose every independently actionable child. Apply grouping before count, ordering and pagination, including when the parent has no separate attention reason. Unlinked Tasks always remain visible. If the parent is terminal but a linked Task remains active, show the Task independently with terminal-source context.

A pending owner report and an unpaid expectation are distinct decisions: link them when the source provides a relationship; do not suppress either. Agenda is a separate time view and may reference a row also in Upcoming/Needs action. Label its count Appointments, not additional actions. Legal/HOA shared-repair grouping is an extension, not guessed from matching titles or addresses.

## Scope, dates and refresh

Default operational scope includes all recorded unresolved obligations, including obligations on archived properties, labeled Archived. Inventory defaults to active properties; money retains FIN-003's explicit archived-property semantics. Display these differences; do not use one ambiguous portfolio count for all three. Support an explicit property filter; owner filtering can follow through a source-owned relation later and is not required for first delivery. Workspace-level unlinked Tasks appear in All properties and are excluded by a property filter, with a visible scope explanation.

Capture one aware UTC `asOf` per response. Use each property's stored IANA zone for rent, lease and agenda dates; use Task's own stored zone for its deadline/follow-up. Show zone labels on cross-zone appointments. Initial Upcoming horizon is seven days; allow 30 and 90. The interval includes the remainder of local today through the end of the Nth following local day; source-specific Needs action rules take precedence. No browser clock classifies work.

Agenda is an interval-overlap view of scheduled appointments in that local window; ongoing appointments remain visible until their recorded end. Appointment order is actual UTC start, stable ID tie. Past uncompleted appointments leave the future agenda but remain outcome-review work. No showing or inspection calendar is implied unless those sources have a real scheduled-appointment contract.

Money requires explicit inclusive `fromOn`/`throughOn`. The initial default is the complete current calendar month based on server UTC date, visibly labeled with exact dates; each source still uses its property-local transaction date. The full-month window may include future-dated recorded activity; show that fact and retain source drill-down. Never silently present it as month-to-date. Period selection is URL state; no new persisted preference is required.

Refresh on entry, after relevant source mutation, on window focus and every 60 seconds while Home is visible. Server supplies `nextTransitionAt` (earliest known timed transition or applicable local midnight); refresh at that boundary while visible. Stop polling hidden views and never imply monitoring while the app is closed. Retain failed refresh results only as explicitly stale with original timestamp.

## Backend contracts

Implement `HomeCompositionService` in Operator application with source-owned attention ports wired in bootstrap. Operator retains composition ownership. Conditional snapshot tables cache derived projections under the policy above; they do not create a new domain authority. Use one caller-owned deferred read transaction and captured instant for membership, totals, previews and money. Do not compose independent HTTP requests or independently transactional public services and call the result one snapshot.

HTTP endpoints:

- `GET /api/operator/home`: initial bounded sections, inventory and money; accepts `propertyId`, `horizonDays` (7/30/90), explicit money dates and `limitPerSection` (default 5, max 10).
- `GET /api/operator/home/items`: one named collection with identical scope/date rules, default 50/max 100, and optional opaque cursor. Collections: `needs_action`, `waiting`, `upcoming`, `appointments`, `information_review`.

The browser sends the explicit normalized money period even when using the default. Collection reads do not require unrelated money parameters; cursors bind only normalized parameters relevant to that endpoint. View all uses the Home collection endpoint so its membership/count cannot silently differ from a source directory. Source detail and financial metric drill-down retain typed source routes and explicit filters.

Response envelope: `contractVersion`, `workspaceId`, `runtimeEpoch`, `asOf`, `sourceRevision`, normalized `scope`, `nextTransitionAt`, `supportedSources`, and typed section results. Each available section has `matchingTotal`, `items`, `nextCursor`, `viewAllTarget`. Unavailable sections have a stable `reasonCode` and retry context, no fabricated count or empty items. Each item includes:

- `key`, discriminated `source`, source revision, source status, property/space identity, display title;
- `collection`, ordered `reasons` with typed codes, priority band and relevant source references;
- separate Task deadline, follow-up and source-deadline facts; dates include zone/date-only distinction;
- `groupLinks` with typed relation and child identity, bounded child preview and exact child count/detail target;
- `nextAction` from a registered action vocabulary and typed detail/section target;
- minimal `provenance` identifying owning source and relevant source revision/date, without raw message/file content;
- exact money fields only where applicable, using Finance representations.

Use discriminated schemas rather than arbitrary dictionaries in the public contract. Validate source-target/action pairings; unknown kinds fail the affected collection instead of rendering an unsafe URL. No credential, raw Intake evidence, document body or sensitive free-form notes in previews. Existing audited source reads govern expanded evidence.

### Ordering and bounded execution

Needs action orders emergency/urgent source reasons, overdue work, due-today/actionable follow-up, then undated/review decisions; within each band use earliest relevant instant/local-day boundary, then source kind and ID. Waiting sorts unscheduled first, then next follow-up instant, then stable key. Upcoming sorts next relevant instant; information review sorts missing-required before needs-review, then property/subject/area. The server owns normalized keys.

Ports accept connection, normalized scope, captured instant, collection and continuation key. Owners expose SQL-filterable facts/relations or bounded source candidates with exact grouped counts. For a merge algorithm, fetch at most page-size-plus-one from each registered source after the same global key, merge only these bounded candidates, and hydrate selected rows in batches. Grouping and parent selection must precede candidate limits; grouped counts cannot be reconstructed from truncated previews. Reuse source-owned relations rather than importing another module's ORM in Operator.

Coverage requires a dedicated set-based eligibility/count projection matching the existing coverage derivation, including manual review provenance. Do not infer global counts from the first 50 subjects. Reuse derivation rules and test equivalence; a raw unbounded Python scan is not the implementation plan.

Acceptance budget: at most 64 SELECTs for initial Home, 24 for one collection page, and no per-row or per-property query growth. Record source sub-budgets during implementation and include Finance integrity checks/marker reads in measurements. Output size is bounded by section limits; grouped children preview at most three per row. Validate the budget on 1, 10 and 50 properties plus at least 1,000 Tasks/expectations; profile indexes for eligibility and stable ordering. Live reads are the initial implementation; enable nightly snapshot tables when measured latency meets the optimization trigger above.

### Continuations and failures

Bind cursors to contract/ordering version, collection, normalized filters, workspace/runtime, source marker, `asOf` and last composite key; 15-minute lifetime. Extend the existing cursor utility explicitly for composite attention keys rather than forcing them into the two-field metadata cursor. On changed source marker/runtime or expiry return 409 with refresh guidance. Malformed inputs return 422, oversized content 413, absent explicit property 404, and whole-workspace unavailability 503 through the shared error envelope.

A cursor freezes time classifications at its first-page `asOf`; it is not a durable SQLite snapshot. Reopen a short read transaction and reject source changes. A new first page refreshes current time. Do not page frozen results into a newly refreshed list.

If any required source for a merged collection fails, mark that entire collection unavailable; totals and priority order would otherwise be incomplete. Independent agenda, money or coverage can remain available. Expected source failures may be isolated only while the snapshot remains usable; transaction/connection failure fails the full request. Unexpected errors are logged safely and do not become successful empty results.

“No immediate actions in recorded information” requires an available Needs action collection with zero total. Display any unavailable supported source/coverage alongside; never say Everything is taken care of. Missing registered core adapters is a readiness failure. Deferred features appear as unsupported capability context, not runtime outages, and do not block the initial Home.

## Mutation, persistence and portability

Home is read-only. Expanded commands call the owning domain with current revision, confirmation and existing idempotency/recovery contract. Opening, collapsing, refreshing and loading Home do not create Tasks, acknowledge reminders, synchronize rent, record coverage review or append domain audit events. Source mutations invalidate affected Home keys, not every query in the application.

The initial live-read design adds no Home table or durable computed balance. Conditional snapshot tables are rebuildable Operator-owned caches and must satisfy the generation, invalidation and portability rules above. Restore/relocation rebuilds Home from source data; runtime epoch changes invalidate client caches and cursors. Source schema changes, if needed for query indexes, belong in the current greenfield baseline. Query filters/expansion are presentation state; sensitive evidence must not be persisted in browser storage.

## Resolved design decisions

All 15 recommendations from the original contradictions and missing decisions were accepted by the operator on October 12, 2026. Decision 16 records the subsequent requirement for nonblocking reads, latency handling and conditional nightly snapshots. Numbers are retained for traceability. These decisions govern the specification above and the implementation plan below.

1. **Ownership:** backlog calls this Dashboard while Architecture assigns compositions to Operator. Implement Home in Operator, with source ports in the owning modules; no parallel domain authority.
2. **Dependencies omit named sources:** DASH-001 explicitly names MAINT-001 but appointments belong to MAINT-002; lease expiry and inventory also rely on Lease/Portfolio. Document direct source requirements MAINT-002, LEASE-001, PORT-003 and TASK-001 alongside current dependencies. They are transitively present through UI-001; do not add UI-002, INGEST-002 or LEAD-002 as gates.
3. **Context previews are insufficient:** existing readers order by creation/report time and omit portfolio reminder/appointment/late-rent selection. Deliver the source extensions above under DASH-001. Keep aggregation in the backend; OPS-001 contextual reads do not establish Home readiness.
4. **Waiting versus urgency/deadlines:** UI-001 requires waiting to resurface and also forbids hiding urgent/overdue work. Use precedence Needs action > Waiting > Upcoming, retaining all reasons and independent reminder state.
5. **Duplicate work counts:** no existing Home grouping contract decides whether source and follow-up count twice. Require explicit typed source-follow-up grouping before pagination; independent report/rent decisions remain separate; no title/property heuristics.
6. **Undated and ordinary unresolved work:** backlog specifies urgent repairs but offers no rule for ordinary open issues, concerns or undated Tasks. Keep these in Needs action unless explicitly waiting, below urgent/dated work; never silently exclude unresolved ordinary work.
7. **Lease review timing:** expiry does not specify lead time or legally required notice dates. Use a fixed 30-day review window and 31–90-day extended Upcoming; Lease owns eligibility including successors/continued occupancy. No new legal rule or configurable reminder store.
8. **Calendar scope and missed outcomes:** “appointments” could imply showings/inspections and elapsed appointments might disappear. Include Maintenance appointments only initially, interval overlap for ongoing work, and past uncompleted outcome review. Showings stay LEAD-002.
9. **Portfolio time and period:** multiple property zones provide no single Today/month. Use source-local operational rules, explicit zones, seven-day default, and an explicitly labeled UTC-selected full calendar month for money, with property-local source dates. Month-to-date is outside the initial default; any later change requires an explicit reporting-zone policy.
10. **Archived scope and unlinked Tasks:** current contextual readers can miss unlinked work, and Finance includes archived history. Retain unresolved archived obligations and unlinked Tasks in All properties, active-only inventory, separately labeled Finance scope.
11. **Partial failures and assurance:** exact merged counts cannot coexist with silent source omission. Return unavailable whole affected collection, independent other sections, null/absent unavailable totals and qualified zero-action language.
12. **Coverage is bounded but not a global review directory:** current batched facts do not alone establish efficient exact cross-portfolio review counts. Implement a set-based coverage membership/count port with parity tests; keep coverage gaps separate from delinquency/action counts.
13. **Refresh and expiry:** existing cursors freeze time, while follow-ups become actionable at exact instants. Use frozen continuation semantics plus fresh first-page refresh at server transitions/focus/60 seconds; protect dirty forms during membership changes.
14. **Money and inventory acceptance scope:** Product brief includes vacancy/money/value snapshot; backlog defers value metrics to DASH-002. Include a small vacancy/unknown summary and FIN-003 recorded-activity totals now, each with drill-down; no profit, owner-entitlement or estimated value claims.
15. **Missing read budgets and global bounds:** existing contextual limits cannot be assumed sufficient for merged portfolio collections. Enforce the explicit page/child limits and query budgets above; reject designs with per-property/record reads or truncated-count arithmetic.

16. **Latency and asynchronous delivery:** Home queries must not block the interface or server event loop. Use visible initial/refresh/delayed/timeout states, cancellation and bounded request concurrency; measure p95 latency against the one-second target. If optimized live reads still impair operation, add nightly snapshot tables with source/time invalidation, atomic generation publication, truthful stale state and restore rebuild. Nightly data cannot silently replace current obligations.

## Ordered implementation slices

Follow the numbered order below. Slice IDs are local to DASH-001 and remain stable for implementation/review references. All slices are **pending**; this is a delivery plan, not evidence of completion. Each slice should produce a reviewable change with focused validation before proceeding. UI-001's reusable workflows and the source prerequisites in the backlog are required at the point of integration.

Slices 1–11 deliver the backend contract; slices 12–17 deliver the frontend; slice 18 measures the integrated experience. Slices 19–20 are conditional optimizations: skip them with recorded evidence when slice 18 meets the latency targets. Slice 21 is the final delivery gate. Source extensions remain DASH-001 work in their owning packages, with no dependency on deferred UI-002 capabilities.

### Backend slices

1. **Slice 1 — Typed Home contracts and source registry.** Define normalized scope, attention windows, collection/item discriminators, reason/action vocabulary, typed routes, grouping relation rules and source-owned ports. Specify available/unavailable envelopes, exact totals, bounded child previews and `nextTransitionAt`. Include concrete request/response examples for every initial source and failure state. Establish the registered-source/collection dependency map. **Exit:** schema and contract fixtures reject invalid source/action/target combinations and contain no raw evidence. Keep Home capability unavailable until all core adapters and composition are wired.

2. **Slice 2 — Portfolio scope, inventory and calendar facts.** Provide source-owned relations for portfolio/property selection, retained archived obligations and active-only vacancy/unknown summaries, with batched identity/zone hydration and filtered drill-down targets. Supply local-day boundaries at the caller's captured instant. **Exit:** explicit missing property is 404; unknown occupancy never counts as vacancy; all-property and single-property scopes produce correct inventory and obligation membership without per-property reads.

3. **Slice 3 — Task, reminder and waiting attention.** Add transaction-aware portfolio projections for deadlines, due reminders, exact-instant waiting follow-ups, undated work and unlinked Tasks. Return source-owned classification, ordering facts, temporal transitions and typed relation identities. Preserve existing TASK-001 summary behavior. **Exit:** future-today deadlines and follow-ups remain distinct; terminal/deleted Tasks are excluded; reminders remain independent; source counts and candidate bounds are exact.

4. **Slice 4 — Maintenance issue and appointment attention.** Add urgency/ordinary-unresolved issue projections, explicit follow-up relations, scheduled appointment agenda membership, interval overlap and elapsed-uncompleted outcome review. Return owning revisions and next transitions. **Exit:** urgent work remains actionable while waiting; appointment completion/cancellation and issue resolution remain independent; ongoing, cross-midnight and past-uncompleted appointments classify correctly.

5. **Slice 5 — Finance rent attention and recorded-money reads.** Add bounded source-owned positive-outstanding expectation facts for late, due-today and future rent. Integrate the existing caller-connection FIN-003 money reader with explicit dates and scope. Provide exact metric drill-down targets and canonical money representations. **Exit:** partial allocations, voids/corrections, archived history and property zones match Finance policy; pending reports, scheduled checks and deposits cannot inflate rent received; grouping never sums different expectation periods into one row.

6. **Slice 6 — Lease review attention.** Add source-owned expiry/review eligibility, 30-day action window, extended Upcoming and overdue-end continued-occupancy facts. Consider confirmed successor/closure records and exclude invented expiry/notice dates. **Exit:** boundary dates, open-ended contracts, ended/terminated contracts, successors and continued occupancy have explicit tested outcomes.

7. **Slice 7 — Owner report and concern attention.** Add pending-verification report and unresolved-concern projections, owning identities/revisions and eligible concern-follow-up relations. Link reports to relevant rent context without suppressing separate decisions. **Exit:** terminal sources leave the queue, historical owner context is retained, active child Tasks survive terminal parents, and reports remain provenance rather than income.

8. **Slice 8 — Portfolio information-review projection.** Add set-based coverage eligibility/counts and bounded review pages matching current source derivation and manual-review provenance. Return missing-required before needs-review, applicability counts and typed resolution targets. **Exit:** projection matches coverage rules across a complete portfolio, including more than 50 subjects; unavailable sources do not become recorded coverage; no first-page-derived totals or per-subject query growth.

9. **Slice 9 — Home grouping, ordering and snapshot composition.** Combine slices 2–8 on one caller-owned deferred transaction and captured instant. Group eligible Tasks/reminders into canonical source rows before exact counts, candidate limits and ordering. Merge bounded globally ordered candidates and batch hydration; calculate supported sources and next temporal transition. **Exit:** all collections and money/inventory share one coherent read; multiple child reasons remain actionable; terminal-parent fallback, equal keys and multi-page datasets produce exact nonduplicated rows/counts. Independent section failures follow the dependency map.

10. **Slice 10 — HTTP delivery, continuations and readiness.** Expose `/api/operator/home` and `/api/operator/home/items`, wire ports/service in bootstrap, extend cursor support for composite keys and register the real Home capability. Bind filters, collection, version, runtime/source marker, captured instant and expiry. Run synchronous database work within the supported worker boundary. Use shared error envelopes and whole-request failure for an unusable transaction. **Exit:** endpoint tests cover malformed/oversized input, property not found, changed/expired cursors, unavailable collections versus zero totals, missing adapters and repeated read-only requests. Continuations never mix source revisions.

11. **Slice 11 — Backend readiness and performance proof.** Measure the complete endpoint query counts, candidate/output bounds, worker wait and database duration. Exercise concurrent writes, expected source failure, restart/restore/runtime changes, grouping and multi-zone transitions using representative 1/10/50-property datasets and at least 1,000 Tasks/expectations. Tune required indexes in the current greenfield baseline. **Exit:** 64/24 SELECT ceilings and fixed query growth pass; core source regressions remain clear; record latency measurements for comparison with slice 18. Backend readiness requires accurate live reads even when subsequent caching is warranted.

### Frontend slices

12. **Slice 12 — Generated contracts and asynchronous Home transport.** Generate OpenAPI client types and add workspace/runtime/scope-bound Home query keys, URL-normalized property/horizon/money filters, abort handling, request deduplication and typed availability mapping. Derive the visible full-calendar-month default from server-authoritative UTC date, not the browser's ambient date; use the existing bootstrap time fact if available, otherwise add a minimal server fact during this slice. Preserve existing UI-001 contract consumers. **Exit:** response/route types compile, superseded-scope results are discarded, navigation renders during pending reads, and absent readiness retains a truthful unavailable Home.

13. **Slice 13 — Home layout and latency states.** Replace the placeholder with the actual header/scope, Needs action/Waiting/Upcoming previews, agenda, information-review region and compact money/inventory summaries. Reuse shared disclosure and async components. Implement stable skeletons, retained timestamped content on refresh, Updating, two-second delayed feedback and ten-second recoverable timeout. **Exit:** no unavailable/loading count becomes zero; navigation/typing remain responsive; independent region failures and qualified empty states render correctly. Provide source-detail links until expanded action integrations arrive.

14. **Slice 14 — View all collections and scope-preserving navigation.** Add route-backed collection pages using the same Home membership and ordering, exact counts, 50/max-100 pagination, bound cursors and clear 409 restart guidance. Preserve filters, return location and scroll; keep source drill-downs and hidden destinations reachable. **Exit:** preview-to-directory count/membership agrees at the same read instant; frozen continuations are not appended to a fresh list; changing property/horizon resets incompatible cursors.

15. **Slice 15 — Expanded source workflows and recovery.** Register every initial source renderer/action adapter; show all grouped child Task/reminder actions and the owning detail context. Reuse source forms, revisions, confirmations, audited evidence reads and immutable-result recovery. Fetch sensitive/current detail through the source API only when needed. **Exit:** payment, issue, appointment, owner review, Task and coverage actions persist through the owning workflow; retries do not duplicate effects; failures preserve input and identify partial success; Home introduces no generic lifecycle command.

16. **Slice 16 — Money, inventory and review drill-down acceptance.** Finish source-backed money metric links, explicit periods and archived scope labels; inventory vacancy/unknown filtered views; coverage explanation/resolution; cross-zone agenda labels and current source context. **Exit:** each displayed total opens matching contributing records, source unavailable remains distinct from empty, and no metric implies profit, owner entitlement or unsupported monitoring.

17. **Slice 17 — Live refresh and protected interaction state.** Add entry/focus/60-second refresh, server `nextTransitionAt` scheduling, hidden-view pause, source-mutation invalidation and one in-flight request per key. Preserve dirty expanded editors, focus and recovery when membership changes; distinguish retained editor rows from newly counted results. **Exit:** exact follow-up boundaries resurface work, stale refresh results keep original timestamps, timeout retries do not accumulate requests, and scope/runtime changes cannot apply old responses.

### Integrated performance and conditional snapshots

18. **Slice 18 — Integrated experience and latency gate.** Validate real-workspace flows across all initial sources, Light/Dark, keyboard disclosure, narrow layouts, dirty-form refresh and restart/restore. Measure browser end-to-end Home/page/refresh p95 and shell/navigation feedback, including worker wait, with representative datasets and deliberately slow requests. Optimize queries/indexes and rendering before assessing snapshots. **Exit:** record the measured results against one-second read p95, 100-ms shell feedback and query ceilings. If targets are met and no disruptive delays remain, record slices 19–20 as skipped; otherwise record the bottleneck and exact expensive sections requiring snapshots, then proceed to slice 19.

19. **Slice 19 — Conditional backend snapshot generations.** Implement only when slice 18 triggers the optimization. Add Operator-owned disposable generation tables, consistent capture, bounded staging, short atomic publication, source/version/scope/period/time validity, retained-generation limits and generation-bound cursors. Wire nightly 02:00 UTC builds, startup catch-up and coalesced invalidation/regeneration through the existing single-writer boundary. Resolve cache export/schema-validation handling and restore disposal before enabling reads. **Exit:** cached/live parity, source mutation during build, temporal expiry, interrupted publication, rebuild failure, concurrent commands and restore tests pass; no mixed generations or stale counts served as current.

20. **Slice 20 — Conditional cached delivery and latency revalidation.** Integrate valid cached reads, live fallback and explicitly stale/unavailable results with the frontend freshness/refresh states. Preserve source action validation, generation cursor rules and zero-action suppression. Re-run the slice 18 latency and experience cases, including arbitrary uncached filters and missed-night/startup recovery. **Exit:** optimization improves the measured bottleneck while preserving current obligations, exact counts, responsive commands and truthful stale state. If invalidation prevents useful cache hits, record that result and revisit the measured projection strategy before claiming performance acceptance.

### Final delivery gate

21. **Slice 21 — Acceptance and documentation handoff.** Complete the validation matrix, remaining actionable findings and relevant source regressions. For implementation changes run required Python lint/format checks or frontend lint/format/type checks; retain focused validation evidence for each slice. Update the Operator/frontend module guides with demonstrated behavior, record slice 19–20 implementation or justified skip, and update DASH-001 backlog status only after acceptance. Archive this plan only when its delivery and validation gates are fulfilled. **Exit:** every supported source has working drill-down/action paths, accurate totals and freshness, bounded reads and acceptable measured latency; deferred integrations remain explicitly scoped.

## Validation matrix

| Area | Required evidence |
| --- | --- |
| Happy paths | Empty workspace; mixed self-owned/client-owned portfolio; overdue partial rent; pending owner report; urgent repair with waiting; expiry; appointments; coverage; each row/metric drills to matching sources. |
| Invalid combinations | Invalid horizon/range/property/cursor; mismatched source target/action; void/terminal records; report/check excluded from received rent; unknown occupancy not vacancy; no fabricated owner identity. |
| Grouping and counts | Multiple Tasks/reminders per source, unlinked Task, terminal parent with active child, more than one page, equal sort keys, parent outside preliminary preview; every child action retained, no gaps/duplicates, exact totals. |
| Time | Multiple zones, DST boundaries, timed follow-up one instant before/at due, future-today Task versus follow-up, all-day deadlines, ongoing/cross-midnight appointments, missed completion, cursor frozen time and live refresh. |
| Retry/idempotency | Repeated reads create no records; existing source command key prevents duplicate payment/Task action; unknown command outcome recovers original result before retry; mutation invalidates Home. |
| Transaction/rollback | Concurrent writer cannot mix counts and rows; source command rollback leaves Home unchanged; failure during composition exposes no partial successful count; independent expected failures preserve other valid sections. |
| Persistence/schema | No copied Home state; canonical source status/revisions survive restart; new indexes/current-schema validation if required; sensitive evidence absent from previews. |
| Backup/restore | Same sources reconstruct same facts at fixed clock after restore; new epoch rejects old cursors/query cache; no credentials or stale Home snapshots added to portable data. |
| Query/N+1 | Initial/page ceilings measured including metadata and Finance checks; 1/10/50 properties and large history; bounded candidates/children and stable query count. |
| Latency and snapshots | Slow/timeout/cancelled requests; navigation and typing during reads; late response discarded after scope switch; coalesced refresh; p95 measurements; cache parity with live results; source/time invalidation; interrupted publication; concurrent writes; missed-night catch-up; stale zero-action suppression; restore rebuild and bounded cache retention. |
| Frontend | Light/Dark, keyboard disclosure, narrow layout, hidden destinations, exact View all, unavailable versus empty/stale, fresh total with retained dirty editor, focus and source-return context. |

Acceptance requires all registered initial sources, accurate exact totals/drill-downs and explicit limitations. The existing synthetic demo is a useful happy-path fixture, but does not replace failure, multi-zone, pagination or large-history cases. No tests were run for this documentation-only design.
