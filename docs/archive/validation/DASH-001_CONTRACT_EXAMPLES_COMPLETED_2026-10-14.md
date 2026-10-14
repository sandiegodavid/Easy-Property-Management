# DASH-001 contract examples and acceptance evidence

Delivered October 12, 2026. Strict models are in `operator/application/home_contracts.py`; owning-module `attention_ports.py` declarations accept a caller-owned transaction and neutral `platform/attention_reads.py` window. `operator/application/home_ports.py` defines the typed one-transaction composition boundary and required adapter bundle, including Portfolio scope/inventory/calendar and Finance's existing Money reader. Home capability stays unavailable pending adapters and composition.

The source window includes a discriminator so Maintenance issue and appointment projections return independent counts/candidates even though one owning reader implements both. Candidate validation checks that discriminator before merge. This does not add an independently opened source transaction.

Complete executable JSON request, item, full Home, attention, collection and failure examples are in `application/apps/server/app/modules/operator/tests/fixtures/home_contracts.json`. The snippets below explain that fixture; it is the authoritative example set checked by the focused tests. Source references use a `kind` discriminator in the generated schema, including registered property/space coverage areas. Foreign fields and raw evidence fail validation.

## Normalized requests

Full Home:

```json
{"scope":{"kind":"portfolio"},"horizonDays":7,"fromOn":"2026-10-01","throughOn":"2026-10-31","limitPerSection":5}
```

Independent complete live attention:

```json
{"scope":{"kind":"property","propertyId":"00000000-0000-4000-8000-000000000001"},"limit":5}
```

Collection:

```json
{"scope":{"kind":"portfolio"},"collection":"waiting","horizonDays":30,"limit":50,"cursor":null}
```

## Initial source responses

Each table row substitutes its kind/reason/action/owner in this concrete example, including each repeated source reference. Revision is `1`, ID is the UUID below. These examples are executable in `operator/tests/test_home_contracts.py`.

```json
{"key":"task:00000000-0000-4000-8000-000000000001","source":{"kind":"task","id":"00000000-0000-4000-8000-000000000001"},"sourceRevision":"1","sourceStatus":"active","title":"Recorded source","collection":"needs_action","reasons":[{"code":"undated","priority":"review","source":{"kind":"task","id":"00000000-0000-4000-8000-000000000001"}}],"nextAction":{"kind":"review_task","target":{"kind":"source","source":{"kind":"task","id":"00000000-0000-4000-8000-000000000001"}}},"provenance":{"owner":"tasks","sourceRevision":"1"}}
```

| Kind | Reason | Action | Owner |
| --- | --- | --- | --- |
| task | undated | review_task | tasks |
| rent_expectation | due_today | record_payment | finance |
| maintenance_issue | urgent | review_issue | maintenance |
| owner_rent_report | pending_verification | review_report | owner_accounting |
| owner_concern | unresolved | review_concern | owner_management |
| lease | lease_review | review_lease | leases |
| maintenance_appointment | outcome_review | review_appointment | maintenance |
| coverage | missing_required | review_coverage | operator |

Rent adds `outstandingMinor: 12345` and `currency: "USD"`, with priority `today`. Repair urgency has priority `urgent`. Coverage changes collection to `information_review`, uses priority `information`, adds `subjectKind: "property"` and registered `area: "occupancy"` to each reference and appends `:property:occupancy` to the key. Source status is an owning fact; these fixtures test contract shape rather than source eligibility.

Grouping permits only `issue_follow_up`, `concern_follow_up` and `task_reminder`. Preview and relation arrays allow at most three children; exact `childCount` and the owning detail target expose remaining children. Same-property context cannot group records. A grouped Task's reminder retains its Task parent identity and target. Reminders remain independently actionable children, not independently counted source rows. Needs action reasons take precedence over Waiting and Upcoming; unsupported reason/priority combinations fail validation. Separate deadline/follow-up/source-date facts specify exactly one UTC instant or local date and a valid IANA zone.

## Home and attention envelopes

Full Home wraps five named collections, inventory and money with workspace/runtime identity, normalized scope, source revision, `asOf` and `nextTransitionAt`. Complete live attention wraps only Needs action, requires all seven action sources, exact mutually exclusive `priorityTotals` and potentially overlapping `reasonTotals`. Unavailable attention forbids these totals; snapshot captures cannot satisfy the live attention contract. Each section retains its own capture, freshness, read mode and optional generation identity.

## Section response examples

### Available

```json
{"status":"available","collection":"needs_action","capture":{"asOf":"2026-10-12T12:00:00Z","sourceRevision":"1","readMode":"live","freshness":"checked","checkedAt":"2026-10-12T12:00:00Z","nextTransitionAt":"2026-10-12T13:00:00Z"},"matchingTotal":0,"items":[],"nextCursor":null,"viewAllTarget":{"kind":"home_collection","collection":"needs_action","scope":{"kind":"portfolio"}}}
```

### Unavailable

```json
{"status":"unavailable","collection":"needs_action","capture":{"asOf":"2026-10-12T12:00:00Z","sourceRevision":"1","readMode":"live","freshness":"unavailable"},"reasonCode":"adapter_missing","retryTarget":{"kind":"home_collection","collection":"needs_action","scope":{"kind":"portfolio"}}}
```

## Failure behavior

Use `source_unavailable` for expected reader failure and `source_contract_invalid` for invalid source projection. Neither failure permits totals or rows. Whole-transaction failures use the existing shared problem response. The registry maps required sources to each collection; a missing dependency invalidates the entire affected collection. Independent inventory and money have discriminated typed envelopes and filtered drill-downs.

Whole-request workspace failure uses HTTP 503 and the existing shared envelope:

```json
{"detail":{"code":"workspace_unavailable","message":"Open and validate the workspace before this operation."}}
```

Malformed requests use 422 `request_validation`; oversize inputs use 413 `request_payload_too_large`. Property-not-found and changed/expired continuation handling arrive with scope and HTTP implementation in Slices 2 and 10.

## Focused validation matrix

| Area | Evidence |
| --- | --- |
| Happy paths | Eight discriminated source fixtures plus complete Home, attention, collection and failure envelopes round-trip; explicit grouped Task/reminder ownership validates. |
| Invalid combinations | Action/target, reason/priority/collection precedence, key, raw evidence, exact money formatting/periods, scope, IANA/UTC dates, exact numeric values and child bounds fail closed. |
| Failure/readiness | Unavailable rows/counts are forbidden; successful live attention requires every action source, checked capture and coherent breakdowns; missing scope/inventory/Money adapters also keep Home unavailable. |
| Query bounds | Window allows 1–100 plus one look-ahead, known horizon and UTC. Page validation requires ordered unique candidates after the cursor and exact counts. Real SQL budgets arrive with adapters. |
| Retry/rollback/persistence/backup | No writes or schema changes in Slice 1. Continuation execution, transaction consistency and portability are later implementation gates. |

Validation: 34 focused contract cases passed; changed Python files pass Ruff lint and format checks. No SQL query-performance or browser-readiness claim is made before the later adapters and delivery slices.

## Slice 2 portfolio facts and validation

Delivered October 12, 2026. `portfolio/infrastructure/attention_reader.py::SQLitePortfolioAttentionReader` implements the Portfolio source port using only the caller's connection. `properties()` and `spaces()` return SQL relations filtered by optional property identity; the default retains archived property/space obligations. `inventory_only=True` restricts both property and space lifecycle to active records. Explicit absent property scope raises `PortfolioAttentionNotFound` with status 404; an archived property remains a valid scope with zero active inventory.

`inventory()` computes all counts in one aggregate SELECT, independent of portfolio size. It reads only valid occupancy periods effective on each property's local date, with end-exclusive comparisons. Missing or overlapping current periods count as unknown, never vacant. No Lease presence/absence is consulted. `next_transition_at` is the earliest active-property local midnight, when date-based inventory can change; an empty active scope has no transition. `inventory_spaces()` uses the same occupancy SQL projection for exact filtered totals and stable `(property_id, space_id)` continuation, then applies LIMIT before hydrating at most 100 rows. The next key is the last returned row. These facts support the typed inventory targets defined in Slice 1; HTTP routes and cursor-envelope binding arrive in Slice 10.

`calendars()` deduplicates at most 100 selected property IDs and uses one narrow query for ID, display name, zone and lifecycle; an empty batch issues no query. It returns the local date, today's UTC start, tomorrow's UTC start and an exclusive UTC horizon end after the Nth following local day. Boundaries respect the property's IANA zone and DST rather than adding fixed 24-hour intervals. For capture `2026-10-12T03:00:00Z`, Los Angeles is October 11 and Tokyo is October 12. Archived selected records retain their identity/calendar facts for obligation hydration.

| Validation area | Focused evidence |
| --- | --- |
| Happy paths | All/property scopes, active vacancy/unknown counts, matching contributing-space pages and property identity/name/zone hydration. |
| Invalid combinations | Missing explicit property is typed 404; naive captures, invalid page bounds/cursors and over-limit calendar batches fail. Overlap/missing periods never fabricate vacancy. |
| Retry/read-only behavior | Repeated reads write no metadata; projections run under SQLite `query_only` and leave transaction ownership to the caller. No command receipt is needed. |
| Transaction rollback/consistency | Caller-uncommitted occupancy is visible, then disappears after caller rollback. A concurrent property archive cannot mix old scope and new counts/calendars within a pinned deferred snapshot. |
| Persistence/schema | Actual SQLite tables and existing indexed, end-exclusive occupancy facts; no table, baseline or retained format changes. Cancelled periods are excluded. |
| Backup/restore | No new persistent or cached data to archive; source facts are recomputed from the existing portable Portfolio records and caller capture. Archive integration remains the later DASH acceptance gate. |
| Query budgets | Inventory: one SELECT at 1/10/50 properties and up to 1,000 spaces. Contributing-space page: two SELECTs regardless of page/portfolio size, with SQL LIMIT and exact total unaffected by continuation. Calendar hydration: zero for empty, one for duplicate or maximum 100-ID batches. No per-property sessions or queries. |
| Calendar boundaries | Cross-zone dates, end-exclusive occupancy transition, 23-hour spring day, 25-hour autumn day and inclusive seven/90-day horizons. |

Validation: 12 focused Portfolio cases and 34 Home contract cases passed (46 total). Changed Python files pass Ruff lint and format checks. Home adapters/composition are not yet registered for HTTP delivery.

## Slice 3 Task, reminder and waiting facts

Delivered October 12, 2026. `tasks/infrastructure/attention_reader.py::SQLiteTaskAttentionReader` reads on the caller's connection and accepts a required `TaskAttentionRelations` dependency. That source-owned SQL relation resolves related identities to retained property/space membership and explicitly eligible issue/concern follow-up parents. Property/lease context alone cannot group Tasks. Multiple contextual locations cannot multiply Task counts; ambiguous All-properties location is not presented as one guessed property. Unlinked Tasks remain in All properties and are excluded by a property filter. Archived unresolved context remains eligible.

The reader filters active, nondeleted Tasks in SQL. It reuses TASK-001 `due_bucket()` for deadline eligibility, extends future local-day horizon selection to 7/30/90 days, and handles waiting follow-ups at their exact UTC instant. A future timed deadline today is actionable; a future timed follow-up today still waits. Overdue/today deadlines or due reminders cannot be hidden by waiting. Waiting sorts unscheduled first, then follow-up instant; Needs action sorts overdue, today/actionable follow-up, then undated work; Upcoming sorts the source deadline boundary. All collections retain stable Task identity ties and accept the shared global continuation key.

Due pending or acknowledged reminders remain independent undismissed child reasons; dismissed reminders are excluded. Multiple due reminders still count one Task. The exact child count is computed before pagination; a single partitioned query hydrates at most three due children per selected Task. Existing TASK-001 summary behavior is unchanged, including its pending-reminder summary semantics. No read acknowledges or dismisses anything.

The `facts(connection, window)` port exposes classified, metadata-only SQL facts for Slice 9's parent grouping before merged counts/limits. `attention()` provides exact Task counts, priority/reason breakdowns and bounded candidates now; these source totals are not final merged Home totals. Parent grouping, remaining owning relation composition and Home readiness wiring belong to Slices 9–10. An active Task on a terminal parent has no grouping relation and remains independently visible.

`next_transition_at` covers future follow-ups/reminders, exact timed-deadline changes and source-local midnight changes to today/horizon membership across the entire selected active scope. Timed deadlines become overdue only after their exact due instant, matching TASK-001; the next transition at equality is one microsecond later. Date-only deadlines expose their local date and zone rather than an invented timed deadline. Private notes/outcomes are never selected or returned.

| Validation area | Focused evidence |
| --- | --- |
| Happy paths | Deadline/follow-up distinctions, unlinked/archived/property membership, explicit issue parent relation, terminal-parent fallback, multi-zone all-day deadlines and extended horizons. |
| Invalid/excluded combinations | Completed/cancelled/deleted Tasks cannot reappear through reminders; dismissed reminders are excluded; waiting cannot hide actionable reasons; property context never creates a grouping relation. |
| Retry/read-only | No commands, receipts or audit mutations; projections work under SQLite query-only mode. |
| Transaction rollback/consistency | Uncommitted reminder visible on caller connection, then absent after rollback. Cancellation between count and candidate reads cannot mix snapshots. |
| Persistence/schema/backup | Existing Task/reminder tables and indexes; no new durable fields or derived store. Projections rebuild from portable source records; integrated Home restore proof remains a later acceptance slice. |
| Query bounds | At most three SELECTs for counts/transition, limit+1 Task candidates and partitioned reminder previews at 1/10/1,000 Tasks. No per-Task queries; zero-candidate pages omit the reminder query. Ten due children still return three previews and exact count ten. |
| Temporal/order/continuation | Unscheduled waiting first; exact follow-up/reminder boundaries; deadline equality versus overdue; seven-day horizon inclusion/exclusion; stable continuation preserves totals without duplicate returned rows. |

Focused validation includes 13 new projection cases plus existing TASK-001 and TASK-002 summary/waiting tests. Required changed-file Ruff lint and formatting checks pass. No Home capability is enabled by this slice.

## Slice 4 Maintenance issue and appointment facts

Delivered October 12, 2026. `maintenance/infrastructure/attention_reader.py::SQLiteMaintenanceAttentionReader` requires Portfolio location and Task attention ports, and uses the same caller-owned connection for every phase. Issue and appointment streams require explicit source discriminators and expose both classified SQL facts for later composition and bounded exact-count pages.

Issues default to Needs action while open/in progress. Stored `priority=urgent` leads that collection regardless of waiting support. A nonurgent issue moves to Waiting only when `maintenance_follow_up_operations` links it to an active waiting Task and no linked Task has an actionable reason. Mere Task context, appointment scheduling or provider assignment does not establish waiting. Completed/deleted Tasks cease to influence parent classification; terminal issues leave the issue queue, while active Tasks and scheduled appointment obligations remain independently readable. Task timing is consumed from its source-owned facts rather than reimplemented in Maintenance.

The issue SQL aggregates all explicit active follow-ups before counts, continuation and candidate limits. At most three Task previews are hydrated per candidate, each preserving its own bounded reminder children and exact counts. The Task port provides bounded set-based selected-ID hydration (maximum 303 for 101 candidate issues times three previews). Nested reminders retain their exact Task parent and cannot contain further children. Metadata-only source reason summaries include qualifying child reason codes even beyond the preview. Final Home child presentation/grouping follows Slice 1 bounds during Slice 9; source issue totals are not summed with Task totals to fabricate merged counts.

Appointments are independent scheduled records. Agenda includes ongoing intervals and future starts inside the selected property-local horizon; Upcoming contains future starts; Needs action contains scheduled appointments whose end has been reached without recorded completion/cancellation. Completed/cancelled appointments are excluded without resolving the issue. Ongoing appointments that began before local midnight remain visible until the exact recorded end. Exact comparisons retain microsecond precision. Agenda ordering is actual UTC start with source identity ties; elapsed work orders by its end. The shared issue revision supplies the current owning concurrency reference, and each fact retains the appointment's displayed schedule zone and exact start/end. The next transition is the earliest future start/end or applicable property-local midnight across the selected scheduled scope.

| Validation area | Focused evidence |
| --- | --- |
| Happy paths | Urgent and ordinary issues, explicit waiting follow-ups, actionable deadline/reminder children, ongoing/future/missed appointments and retained archived scope. |
| Invalid/excluded combinations | Generic Task context cannot create waiting; terminal issues and completed/cancelled appointments leave their own queues; terminal parents cannot suppress independent active obligations; unsupported source/collection pairs fail. |
| Retry/read-only | Queries run under SQLite query-only mode and append no audit, completion, reminder or issue changes. Existing source commands remain authoritative. |
| Transaction consistency | A concurrent issue resolution between counts and candidate/child hydration leaves the complete first result on its original snapshot; the next snapshot sees the resolution. |
| Persistence/schema/backup | Existing issue, appointment and follow-up operation tables are reused; no new durable schema/cache. Restored portable source data supplies the same projections; integrated Home restore remains a later acceptance gate. |
| Query bounds | At 1/10/1,000 issues: at most five SELECTs including ranked three-child selection and batched Task/reminder hydration. At 1/10/1,000 appointments: at most two SELECTs including exact count/transition and SQL-limited candidates. No description, instructions, purpose or Task notes selected. |
| Temporal/order/continuation | Cross-midnight overlap, appointment end equality and one-microsecond transition, property-local horizons/zones, urgent totals above preview size, exact totals unchanged by stable continuation. |

Validation: 16 Maintenance attention cases, 13 Task attention cases and 34 Home contract cases passed (63 total), plus five focused existing Maintenance lifecycle/appointment/follow-up regressions. Required changed-file Ruff lint/format and diff-whitespace checks pass. Home delivery remains gated until the composition and HTTP slices.

## Slice 5 rent attention and recorded money

Delivered October 12, 2026. `finance/infrastructure/attention_reader.py::SQLiteRentAttentionReader` reads on the caller's connection and obtains retained property/space/zone context from the Lease-owned location port. It never imports Lease or Portfolio SQLAlchemy models. Its SQL facts aggregate allocations only from active receipts, retain one identity per expectation period, and exclude voided expectations and nonpositive outstanding balances from attention. Receipt voiding restores outstanding rent; a replacement reduces it only through its actual new active allocations. Pending owner reports, scheduled checks and deposit records have no allocation role in this projection.

Rent due before the property's local date is Needs action/overdue; due today is Needs action/due today; future due dates appear in Upcoming through the selected 7/30/90-day local horizon. Latest missed/clear review and receipt creation activity follow Finance's existing effective-missed policy. Facts retain lease identity, exact period, expected/received/outstanding USD cents, a source-state fingerprint, source-local due date and local-midnight ordering/transition instants. Counts and priority/reason breakdowns precede continuation and LIMIT. Invalid negative outstanding, missing retained location, non-USD expectation or cross-lease active allocation makes the source unavailable rather than returning a clean queue.

`operator/application/home_money.py::money_on_home_snapshot()` calls the existing `MoneyContextReader.summary()` with the same connection and captured instant, explicit inclusive dates and retained `property_state=all` scope. It returns the five canonical operating metrics as exact integer cents and Finance's decimal strings; each typed target repeats the exact metric, period and property scope. Capture/scope or availability disagreement fails closed. Deposit activity remains outside operating rent. Refunds reduce recorded expenses on their own source date; negative net expenses and remainders retain their exact sign. The adapter creates no additional transaction or durable read store.

| Validation area | Focused evidence |
| --- | --- |
| Happy paths | Partial/fully allocated rent, receipt void/replacement, voided expectations, due/late/missed/upcoming status, archived scope and property-local calendar boundaries. |
| Invalid combinations | Over-allocation and cross-lease active allocation fail closed; source USD amount facts require positive exact corrected outstanding and retained lease/period identity. |
| Retry/read-only | Repeated read-only projections; no synchronization, receipt, review or audit mutation. Actual FIN-003 reader uses the supplied connection with new connections blocked. |
| Transaction rollback/consistency | Receipt committed between count and candidate reads cannot mix snapshots. Caller-uncommitted receipt void is visible and rollback restores previous rent/money results. |
| Persistence/schema/backup | Existing Finance allocation/receipt/review tables and indexes; no new durable schema. Source-state fingerprints rebuild from portable records; integrated Home restore proof remains a later gate. |
| Query budgets | Rent attention: two SELECTs at 1/10/1,000 expectations, with SQL LIMIT and stable exact totals across continuation. Home recorded money remains within the existing 15-statement FIN-003 context budget, including integrity and marker reads. |
| Metric semantics | Actual persisted deposit activity does not inflate rent; January excludes a February refund, while February shows the refund and exact negative net expenses. Archived scoped history remains readable. A scheduled check created through FIN-007 leaves both rent received and expectation outstanding unchanged. Existing pending-owner-report/adoption money regressions pass. |

Focused validation: eight new rent projection cases, three Home money integration cases, 34 Home contract cases and five existing caller-snapshot Money context cases (50 total). The existing 21-case FIN-003 summary suite also passed during validation. Required changed-file Ruff lint/format and diff-whitespace checks pass. Source adapter registration and full Home delivery remain gated to Slices 9–10.

## Slice 6 lease review attention

Delivered October 12, 2026. `leases/infrastructure/attention_reader.py::SQLiteLeaseAttentionReader` reads Lease-owned facts and Portfolio-owned retained location/occupancy SQL relations on the caller's connection. Counts precede continuation; candidates use SQL LIMIT and the shared attention ordering. The adapter opens no session, selects no narratives or rent fields, and makes no lifecycle, inspection, audit or occupancy changes.

Executed, ended and terminated contracts with a recorded end remain reviewable until recorded actual move-out reaches the property's local date. Draft, void and open-ended contracts are excluded. Ends within 30 local days (including past ends) are Needs action/review; days 31–90 are Upcoming only when the selected horizon reaches them. Past-end continued occupancy requires a valid, occupied, end-exclusive Portfolio period owned by this exact Lease; another Lease or manual period cannot establish it. Unknown occupancy does not silently clear contract review. Ordering uses the property's contract-end midnight in UTC, and the next local midnight triggers temporal reevaluation.

Confirmed-successor decision: exercised options and unlinked later executed leases cannot clear the original review. There is currently no explicit successor-link record or command; no new workflow is introduced by this read slice. A future explicit-link workflow must supply confirmed facts to Lease-owned eligibility rather than infer them from dates or shared Space identity.

| Validation area | Focused evidence |
| --- | --- |
| Happy paths | Day 0/30 review, day 31/90 extended Upcoming, past-end review and exact lease-owned continued occupancy. |
| Invalid/excluded combinations | Draft/void/open-ended and recorded move-out closures excluded; cancelled, ended and manual occupancy cannot establish continuation. Exercised renewals and unlinked executed contracts retain original review. |
| Retry/read-only | Same caller connection and query-only reads; no commands, operation receipts or audit mutations. |
| Transaction rollback/consistency | Concurrent move-out between count and candidates leaves one consistent old snapshot; next transaction sees closure. Caller-uncommitted changes are visible and rollback restores persisted eligibility. |
| Persistence/schema/backup | Existing Lease/renewal and Portfolio occupancy records only; no new durable schema. Integrated Home backup/restore remains a later delivery gate. |
| Query bounds | At 1/10/1,000 leases, at most two SELECTs for exact counts/transitions and at most limit + 1 candidates. Cursor pages retain exact totals and do not overlap; no per-lease reads. |
| Temporal/scope | Different property-local dates, archived property scope, future recorded move-out and DST midnight transitions. Ended/terminated records use recorded closure, not inferred legal expiry or notice dates. |

Focused validation: 11 new Lease attention cases, 12 Portfolio attention cases and 34 Home contract cases (57 total), plus two existing Lease renewal/ordinary-end regressions. Required changed-file Ruff lint/format and diff-whitespace checks pass. Source registration and full Home delivery remain gated to Slices 9–10.

## Slice 7 owner report and concern attention

Delivered October 12, 2026. Owner Accounting and Owner Management each own their attention SQL adapter, using the caller's connection and Portfolio-owned retained property relations. Facts retain source identity/revision, historical owner Party ID/display-name snapshot, property/Space/Lease references, current property zone and archived-scope label. No current Party lookup is needed to preserve historical attribution. Source facts contain no report source/review notes, payment details, concern descriptions or Task narratives.

Pending reports are Needs action/pending verification. Verified/rejected reports leave that collection, regardless of later receipt state. The exact Lease reference provides rent-context navigation; no expectation relationship or allocation is inferred from dates, amounts or property identity. This read neither creates receipts nor reduces outstanding rent. Reports and rent expectations remain separate decisions.

Open/in-progress concerns are actionable by default. Only distinct follow-up operation pairs whose active Task still references that exact concern establish child eligibility. Generic related-context Tasks do not move a concern to Waiting. Nonurgent concerns may wait when an explicit child is waiting and no child is independently actionable; urgent concerns, overdue/today Tasks and due reminders retain Needs action. Future waiting follow-ups stay Waiting until their exact instant; undated waiting stays Waiting without an invented deadline. Completed/cancelled/deleted children cannot change parent classification. Resolved/dismissed concerns disappear without hiding independently active Tasks. The source port exposes exact follow-up pairs for later composition; final Task suppression/grouping remains Slice 9, not a heuristic in this adapter.

SQL grouping precedes total/count breakdowns, cursor ordering and LIMIT. A ranked query selects at most three child Tasks per selected concern, with batched Task/reminder hydration and exact total child counts. Ordering preserves the highest-priority actionable child's complete ordering key. Report/concern pages share neutral aggregate/continuation mechanics, not workflow policy.

| Validation area | Focused evidence |
| --- | --- |
| Happy paths | Pending verification, unresolved concerns, explicit scheduled/unscheduled waiting, due follow-ups and nested reminder identities. |
| Invalid/excluded combinations | Verified/rejected reports and resolved/dismissed concerns excluded; generic, mismatched, completed and deleted child context cannot establish waiting. Urgent parents/actionable children override waiting. Duplicate follow-up pairs count once. |
| Retry/read-only | Query-only and repeated reads; no report decisions, Task mutations, receipt/allocation writes or audit changes. Unsupported source/collection combinations fail explicitly. |
| Transaction rollback/consistency | Concurrent report review or concern resolution between counts and hydration retains one old snapshot/revision; later reads see the terminal state. Caller-uncommitted report changes and rollback are respected. |
| Persistence/schema/backup | Existing owner report/concern/follow-up and Task records; no new durable schema or migration. Historical owner names survive current Party rename/archive. Existing owner-accounting workflow suite includes its SQLite backup/restore proof; integrated Home restore remains a later gate. |
| Query budgets | At 1/10/1,000 sources, report pages use at most two SELECTs; concern pages with explicit child Tasks use at most five, including ranked child selection and batched Task/reminder hydration. Candidates are at most limit + 1; child previews at most three with exact counts. Continuation does not change matching totals. |
| Scope/temporal/provenance | Active and archived properties retain their IANA zones and explicit property filters. Exact future follow-up transition supplied; terminal parents cannot swallow active child Tasks. Report metadata supplies Lease context, not income or expectation allocation. |

Focused validation: 17 new owner attention cases and existing Task/Maintenance/Finance/Lease/Portfolio attention plus Home contracts passed (111 total). Existing Owner Management and Owner Accounting workflow suites passed (33 additional cases). Required changed-file Ruff lint/format and diff-whitespace checks pass. Home capability remains gated to composition and HTTP Slices 9–10.

## Slice 8 portfolio information review

Delivered October 12, 2026. `SQLiteCoverageAttentionReader` composes SQL fact relations exposed by the Portfolio, Lease, Finance, Maintenance and Audit application ports. Each adapter owns its persistence access. SQLite JSON functions invoke the existing pure location, financial completeness, coverage derivation and review projections without opening connections or executing nested queries. Database aggregates and ranked metadata retain bounded current occupancy/Lease contexts and the latest review; no application scan loads all subjects or evidence.

Two SELECTs calculate exact counts and at most `limit + 1` candidates on the caller's read snapshot. Applicable and not-applicable counts include all eligible areas, while the review total includes only missing-required and needs-review states. Ordering is missing-required first, then needs-review, with stable property/subject/area identities. Continuation never changes totals. Candidates retain typed resolution targets, causes, evidence revisions and latest manual-review timestamps. Archived property context remains explicit. The next property-local midnight provides a conservative reevaluation boundary.

| Validation area | Focused evidence |
| --- | --- |
| Happy paths | Empty scope; missing occupancy/availability; Maintenance review; applicable/not-applicable counts; real Lease/rent/deposit graph parity against existing batched facts, including recorded deposit activity. |
| Invalid/unavailable combinations | Source failure propagates without zero/recorded substitutes; other collections/source discriminators contribute no coverage rows; typed resolution area and subject must agree. |
| Retry/read-only | Repeated reads and SQLite query-only mode; no acknowledgment, audit, financial or source writes. |
| Transaction rollback/consistency | A property committed between count and candidates cannot mix snapshots; caller-uncommitted availability changes are visible and rollback restores the original facts. |
| Persistence/schema/backup | No new tables, indexes or stored Home records. Current-schema validation and encrypted LOCAL-002 restore reconstruct the same exact review page, counts, identities, causes and revisions at a fixed instant. |
| Query/continuation bounds | One versus 61 properties (305 subject/area references): constant count/page query budget; exact 122 review and 183 not-applicable totals; at most limit + 1 candidates; complete continuation without gaps or duplicates; batch fact hydration blocked during selection. |
| Scope/time/provenance | Property filters and archived records; latest append-only decision; exact Los Angeles midnight review deadline; changed source facts invalidate manual-review provenance without clearing intrinsic source gaps. |

Focused validation: 12 new portfolio coverage attention cases plus existing coverage, Home contract and Task/Maintenance/Finance/Lease/Portfolio/owner attention suites passed (150 total). Ruff lint and formatting checks passed for all 17 changed Python files; diff-whitespace validation passed. Home composition and HTTP registration remain Slices 9–10.

## Slice 9 Home snapshot composition

Delivered October 12, 2026. `HomeCompositionService.home()`, `attention()` and the internal frozen collection-page operation use `SQLiteHomeUnitOfWork` with one deferred read transaction and one UTC capture. Bootstrap constructs the source bundle without workspace initialization. Task location relations include Portfolio/Lease context, explicit issue/concern locations, Finance records and Communication links; generic context establishes membership, never grouping. Active owning follow-up operation pairs suppress standalone Tasks before SQL counts and limits. Terminal parents release Tasks with their source context. Source-classified parent rows retain all qualifying reason codes, bounded Task/reminder previews, exact child counts and source detail targets.

Collection streams each supply at most `limit + 1` ordered candidates. Composition merges those bounded streams, selects the global page, and hydrates only the selected property/space labels in one source-owned query. Internal continuation uses the last returned composite key, with exact totals unaffected by the key. HTTP cursor encoding/validation, endpoints and capability registration are Slice 10. Full Home and the independent live read share the complete Needs action path; live attention does not query Money, coverage or inventory.

| Validation area | Focused evidence |
| --- | --- |
| Happy paths/grouping | Mixed rent, issue, concern, pending report, lease review, missed appointment and future agenda; full/live parity; explicit follow-ups count once; generic-context Tasks remain independent; multiple child reasons and nested reminder identities/counts remain available. |
| Invalid/unavailable combinations | Missing adapter and wrong source discriminator fail the dependent collection without fabricated totals. Expected Maintenance/coverage failures preserve independent Money, inventory and other valid sections. A SQLite failure fails the whole request. Missing property scope returns source-owned not-found. |
| Retry/read-only | Repeated composition does not create source records or audit events. No cache or Home persistence is added. |
| Transaction rollback/consistency | A writer changes Task and issue state after marker capture: the in-flight read retains original rows/counts/child status; the next read sees the commit. Rolled-back source changes leave attention unchanged. |
| Persistence/schema/backup | Current-schema validation before backup and after encrypted LOCAL-002 restore; all collection rows, counts, reasons, source revisions, labels, inventory and money reconstruct at the fixed instant. Restore audit and runtime epoch deliberately change capture markers; they are not compared as durable business facts. |
| Query/continuation bounds | Mixed property-scoped composition: 58 Home SELECTs and 23 live SELECTs (81 combined), within 64/24/88 ceilings including marker, scope, label and Finance integrity reads. One collection page stays within 24. A fixed 1,000-Task dataset distributed across 1/10/50 properties uses 42 Home SELECTs. Equal boundaries across source kinds and page-size-one continuations have no gaps/duplicates; terminal fallback preserves exact totals. |
| Scope/presentation | Explicit property scope excludes unlinked Tasks; communication follow-ups inherit their linked property without grouping; selected source labels and archived metadata remain source facts. Actionable children precede waiting children in bounded previews, and overflow retains an exact count/detail target. |

Focused validation: 140 Home/source regression cases passed; all 16 composition cases passed after final updates, including database failure translation and captured-runtime propagation to Finance. Ruff lint and format checks passed for all 20 changed Python files, and diff-whitespace validation passed. Executable evidence: [test_home_composition.py](../../../application/apps/server/app/modules/operator/tests/test_home_composition.py), existing Home contracts and source attention tests.

## Slice 10 HTTP continuations and readiness

Delivered October 12, 2026. Bootstrap composes `HomeCompositionService` and exposes three synchronous GET operations: `getOperatorHome`, `getOperatorHomeAttention` and `getOperatorHomeItems`. FastAPI executes the entire SQLite read in its worker boundary. Strict query models reject unknown fields, require the Home money period and validate typed dates, UUID scope, horizons and bounds. The shared problem envelope maps malformed requests to 422, oversized cursors to 413, absent properties to 404, changed/expired continuations to 409 and unusable workspace reads to 503.

Home and live previews include an opaque continuation when more rows exist. The collection operation validates it inside the same read transaction as its marker, counts, selection and hydration. It binds the endpoint, contract and ordering versions, collection, normalized scope/horizon, workspace/runtime, source marker, captured UTC instant and final returned composite key. The lifetime is 15 minutes from the first capture. Page size can change without changing membership; unrelated money dates do not enter collection continuations. Coverage uses its property/subject/area key. Every collection envelope now requires `asOf` and `sourceRevision`, matching its section capture, with the same optional `nextTransitionAt`.

Bootstrap checks `operator.home` against the current complete adapter bundle. Missing action adapters make dependent collections unavailable with no totals or cursor; independent sections retain their own results. Missing Money is explicitly unavailable. Missing scope context or an unusable SQLite transaction fails the whole request. OpenAPI discovery requires neither workspace initialization nor database access. Browser Home remains on its existing delivery path until the frontend slices.

| Validation area | Focused evidence |
| --- | --- |
| Happy paths | Typed Home, complete live attention and all five collection routes; explicit 7/30/90 horizons; preview-to-page continuation with a different page size; coverage composite-key continuation; production workspace bootstrap advertises the capability. |
| Invalid combinations | Missing/reversed/malformed dates, UUIDs, horizon, collection, unknown query fields and numeric limits; invalid versions/key shapes/UTC instants/identities; malformed and byte-oversized cursors. Every failure uses the shared typed problem envelope. |
| Retry/read-only | Repeated Home/live/page GETs leave the audit ledger unchanged. Cursor capture and exact total remain fixed while subsequent requests advance the clock. |
| Transaction/rollback | A source change after cursor validation cannot alter the in-flight page's rows or child status; the following continuation returns 409. SQL execution is observed on worker threads, separate from the ASGI event loop. Database failures produce a whole-request 503 without SQL or internal exception text. Source rollback and snapshot consistency retain Slice 9's proofs. |
| Persistence/schema/backup | No Home or cursor persistence is added. Source-marker and runtime changes reject old cursors; encrypted restore reconstruction remains covered by Slice 9. Current-baseline/no-workspace OpenAPI contract tests exercise production composition. |
| Query/bounds | Preview and collection limits are typed and bounded; page-size-one/two continuations produce no gaps or duplicate rows. Cursor validation adds no source-record queries. Integrated HTTP query and latency measurement remains Slice 11. |
| Failures/readiness | Successful empty live attention has a real zero total; failed/missing action sources have unavailable sections without fabricated totals/cursors. Missing Money preserves action reads; missing scope context fails safely. Removing a required runtime adapter removes `operator.home` from bootstrap. |

Focused validation: 46 new HTTP cases plus Home contracts/composition, Operator foundation and endpoint contract regressions passed (234 total). Ruff lint and format checks passed for all 11 changed Python files; diff-whitespace validation passed. Executable evidence: [test_home_api.py](../../../application/apps/server/app/modules/operator/tests/test_home_api.py).

## Slice 11 backend readiness and performance proof

Delivered October 14, 2026. [test_home_performance.py](../../../application/apps/server/app/modules/operator/tests/test_home_performance.py) measures the complete three-route HTTP path on a real current-baseline SQLite workspace. Each portfolio size retains 1,000 open Tasks and 1,000 positive weekly rent expectations, distributed over 1, 10 or 50 properties with Los Angeles, Tokyo and UTC zones. Fixtures insert read-test source rows directly; the encrypted portability proof uses the separate owning-service fixture in `test_home_composition.py`.

Measurements use macOS arm64, Python 3.14.8 and SQLite 3.53.4. Each route has ten sequential samples, including its first request at that portfolio size; p95 uses nearest rank. Worker wait measures dispatch-to-worker-entry; database snapshot duration measures the complete unit-of-work read, including connection acquisition, SQL fetching and application projection. HTTP duration includes FastAPI validation/serialization and the local ASGI test transport. These values provide the backend comparison baseline for Slice 18; browser rendering, TCP transport, sustained contention and machine cold boot are not measured here. Timing values are recorded as pytest/JUnit properties rather than unstable wall-clock assertions.

| Properties | Initial / attention / page SELECTs | Initial p95 ms | Attention p95 ms | Page p95 ms | Initial worker wait p95 ms | Initial snapshot p95 ms |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 46 / 17 / 17 | 548.834 | 155.049 | 70.491 | 0.155 | 541.560 |
| 10 | 46 / 17 / 17 | 386.202 | 64.995 | 164.360 | 0.067 | 385.328 |
| 50 | 46 / 17 / 17 | 460.829 | 160.313 | 72.369 | 0.063 | 459.955 |

First-request initial times at 1/10/50 properties were 548.834/289.076/359.424 ms. Attention/page worker waits were at most 0.081 ms p95; their snapshot p95 stayed below 164 ms. Needs action continuation pages use 17 SELECTs. Waiting/Upcoming/appointments/information-review pages use 7/13/3/4 SELECTs respectively at every size. A barrier makes the 50-property initial and live requests overlap inside their read transactions: 63 combined SELECTs and 866.800 ms for both responses. The mixed-source/grouped regression retains 58 initial and 23 live SELECTs (81 combined), including Finance integrity checks, source markers and hydration. All measured costs meet the 64/24/24 and 88 combined ceilings. Existing baseline indexes suffice for these cases; the measurements do not trigger snapshot implementation. Slice 18 retains the integrated latency decision.

| Validation area | Focused evidence |
| --- | --- |
| Happy paths and bounds | Exact 2,000-row Needs action total at all three portfolio sizes; initial/live parity; every available section, maximum 100-row collection pages, at most limit-plus-one candidates per source and three child previews. SQL selection/counting remains source-owned. |
| Invalid combinations and failure | HTTP query/cursor bounds and binding regressions; expected source failure makes the dependent collection unavailable without false zero; independent sections survive; unusable database reads fail the full request. |
| Retry/read-only | Repeated endpoint reads do not add source/audit records. Frozen continuation retains exact totals with no overlap. Repeated timing samples measure the complete endpoint rather than one source adapter. |
| Transaction/rollback | Parallel initial/live requests share identical captures/results and meet the combined budget; concurrent source writes cannot mix counts, rows or child status inside a response. Source rollback leaves attention unchanged. |
| Persistence/schema | Current greenfield baseline used throughout; fixed query growth at 1/10/50 properties. Los Angeles midnight moves rent from Upcoming to Needs action while Tokyo is already due today, updating counts and rows together. No new cache or canonical table is introduced. |
| Backup/restore/runtime | Encrypted backup reconstructs all Home sections at a fixed clock from supported source writes. The restored runtime/source marker rejects a pre-backup continuation; restart/runtime, source-change and expiry conflict regressions pass. |
| Query/N+1 and latency | Assert endpoint ceilings and fixed initial/live/page SELECT counts; measure every collection and continuation, worker wait and read duration. Existing Task, rent, Maintenance, Lease, owner and Portfolio attention regressions remain passing. |

Focused validation: 191 distinct tests passed across Home contracts/composition/API/money/coverage and all six core attention-reader modules, including three new performance/transition/parallel cases. The final three-case performance run passed after adding all-collection measurements. Ruff check and format checks passed for both changed Python files; diff-whitespace validation passed. This is backend readiness evidence; frontend acceptance remains in Slices 12–18.

## Slice 12 asynchronous Home transport

Delivered October 14, 2026. Bootstrap returns required `serverTimeUtc` from Operator's injected clock, normalized to UTC; this adds no write or database query. Generated OpenAPI/TypeScript contracts remain reproducible without a workspace. The browser validates the server-time fact before admission and selects the complete UTC calendar month from it, then stores explicit `fromOn`/`throughOn`, `horizonDays` and optional canonical `propertyId` in the Home URL.

Full Home query keys contain workspace/runtime, property, horizon and money period. Independent live attention keys contain workspace/runtime and property only. Both use abort signals and the existing workspace-owned query client; no prior-scope placeholder data is applied. Typed response admission checks contract version and workspace/runtime/property scope. Missing `operator.home` disables both requests. Full/read and live/read captures stay separate; source failures preserve unavailable discriminants instead of fabricated zero counts.

Focused backend validation covered 185 distinct Operator/Home HTTP/endpoint cases: 183 passed in the initial run and the two timestamp-sensitive bootstrap assertions passed in the four-case bootstrap rerun after correction. The new injected-clock test verifies offset-to-UTC normalization and unchanged audit counts. Frontend validation is recorded [once in the browser matrix](../../ui/validation.md#dash-001-slice-12-transport). Source persistence and encrypted portability proofs remain the existing Operator tests; this slice adds no durable table, receipt or cache. Slice 13 owns the full Home layout and refresh/loading presentation.

## Slice 13 layout and latency boundary

Delivered October 14, 2026. Home retains the generated contracts and independent full/live query captures. Shared read handling now consumes a cancellable ten-second deadline, exposes elapsed wait and per-query retry, coalesces repeated refresh while a query is running, and retains prior data on failed refresh. Timeout cancels the client request; it does not claim SQLite worker cancellation. No new persistence, snapshot cache or command is added.

Appointment attention facts now include their owning issue ID and active state from the existing joined selection. The browser opens that issue's existing appointment context; no per-appointment lookup or query-count increase is introduced. Maintenance source, Home composition/performance and HTTP suites passed in two focused runs (35 and 62 cases, with shared Maintenance cases). These include encrypted restore, read-only behavior, snapshot consistency and the existing SELECT ceilings. Python lint/format checks passed. [The Slice 13 browser matrix](../../ui/validation.md#dash-001-slice-13-layout-and-latency) records the frontend evidence once; subsequent collection/action/freshness gates remain pending.

## Slice 14 first-page cursors and collection navigation

Delivered October 14, 2026. Available HTTP collection sections now emit `viewAllCursor`, a capture-bound first-page token whose `last` is null. A continuation retains the four-part final key. Both forms validate exact normalized filters, workspace/runtime, source marker and 15-minute lifetime within the same deferred transaction as selection. This allows View all to include the preview's first rows at its original instant, rather than skip them or silently take a fresh classification. Empty previews have a valid first-page token too. No extra SQL or durable state is introduced.

The five browser routes `/home/collections/{collection}` are explicitly registered in static delivery. Their queries pass only collection/property/horizon/limit/cursor to the source endpoint; money dates remain URL/return context. Source returns validate local Home routes and runtime identity before restoring scroll. Each collection page replaces the preceding page, with clear 409 recovery; Restart clears the bound cursor. The complete collection browser matrix is [recorded once here](../../ui/validation.md#dash-001-slice-14-collections-and-return-navigation).

| Backend validation | Result |
| --- | --- |
| First/next-page parity | Passed: preview first rows, totals and capture match a larger View all page after the clock advances; continuation rows do not overlap. Empty first-page cursor remains valid with no continuation. |
| Binding/failure/read-only | Passed: existing version/key/filter/source/runtime/expiry, snapshot concurrency, partial failure and repeated read-only endpoint regressions. Nullable last-key admission preserves all other checks. |
| Portability/schema | Passed: encrypted restore regenerates runtime-bound cursors and rejects the original token while reconstructing the same source facts. No canonical schema or compatibility migration. |
| Bounds/delivery | Passed: existing 1/10/50-property, 1,000-Task/expectation query ceilings and candidate bounds; five registered deep links serve trusted assets, and an unknown collection route returns 404. |

Focused backend validation: 146 Home HTTP/composition/contracts/performance/static-delivery cases passed, followed by 46 static-delivery cases after adding the unknown-route guard (147 distinct cases). Python Ruff checks passed for seven changed files; generated contracts and diff validation passed.

## Slice 15 expanded source workflows and recovery

Delivered October 14, 2026. `home-source-actions.tsx` consumes the eight registered `nextAction.kind`/source pairs above as navigation, not write authority. Expansions expose captured provenance/revision, related-source state, outstanding rent and bounded child reasons. Coverage labels include the area; appointment targets require the explicit owning issue and include `#appointment-{id}`. Opening an expansion does not fetch sensitive evidence or current detail. The owning page loads that context and determines permitted commands through its existing source API.

`children` and nested reminder previews remain limited to three with exact `childCount`; they are not the complete action inventory. Issue/concern expansions link to the source Task directory filtered by `entityType` and `entityId`, with 25-row continuation pages. Each Task opens its current reminder actions; the existing 100-row reminder-history bound remains explicitly disclosed. No generic Home Complete, Dismiss or Snooze command is introduced.

`SourceWorkflowLink` carries runtime-validated Home return/filter/scroll context through owning detail, child-directory paging, forms and result links without replacing the source workflow's own `returnTo`. Commands retain source-owned current revisions, confirmations, attempt keys, audit/evidence policies and immutable-result recovery. A stale Home capture never supplies permission to write. Reminder acknowledgement, appointment attendance and concern follow-up remain independent of parent resolution; report rejection is not a Finance receipt, and an open renewal option is not executed continuation.

| Contract boundary | Focused evidence |
| --- | --- |
| Current state / failure | Concurrent Task mutation rejects the old revision while retaining input; explicit source review enables a new attempt. Unavailable issue detail withholds lifecycle controls and preserves Home return navigation. |
| Retry / result identity | Interrupted Task completion and rent payment reconcile their original immutable results with one dispatch and no duplicate effect. Home adds no transaction or recovery protocol. |
| Read / persistence bounds | Disclosure adds no source-detail requests or aggregate SELECTs; 26 explicit follow-ups traverse source pages as 25+1 without gaps. No new Home endpoint, canonical schema, cache or backup format. Existing source rollback/portability proofs remain authoritative; no new archive round trip was run. |

Focused backend validation: **82 Home contract/API tests passed**. The **25-case packaged browser run**, including eight new workflow cases, and quality-check results are [recorded once in the Slice 15 browser matrix](../../ui/validation.md#dash-001-slice-15-source-workflows-and-recovery). Slice 17 delivers the subsequent automatic freshness/editor reconciliation boundary.

## Slice 16 money, inventory and review drill-downs

Delivered October 14, 2026. Money links use each existing `MoneyTarget` unchanged: `metric`, inclusive `fromOn`/`throughOn`, optional property scope and `propertyState=all`, plus the section's Finance `sourceRevision`. `/money?tab=reporting` opens `/api/money/sources` with those values; Finance owns contribution signs, exact amounts, cursor validation and 409 restart. No Home arithmetic constructs the reported total. Labels explicitly retain archived-property history and disclaim profit or owner entitlement.

Inventory counts now include `viewAllCursor`. `/api/operator/home/inventory?occupancy=unknown&limit=50&cursor=…` returns typed `HomeInventoryResponse`: workspace/runtime/scope, `asOf`, source revision, active-only lifecycle, selected occupancy, exact `matchingTotal`, bounded `items` and `nextCursor`. Each item carries Property/Space IDs and names, occupancy, IANA zone and captured effective local date. Portfolio's existing `inventory_spaces()` supplies SQL count, stable `(property_id, space_id)` order and LIMIT before hydration, on the caller's read transaction. First-page cursors have null `last`; subsequent cursors retain both IDs. Existing metadata endpoints still reject null keys. Scope, occupancy, active policy, runtime, source marker and 15-minute expiry bind the token. Normal startup, reads and paging create no durable record.

| Backend boundary | Focused evidence |
| --- | --- |
| Count/capture parity | Home unknown count and first page agree after the clock advances; vacant remains separately zero; pages expose source-local dates. |
| Query/page bounds | One versus 101 contributing Spaces uses a fixed SELECT budget (at most six); 100+1 pages retain exact totals and capture without duplicate IDs. SQL applies LIMIT; existing Portfolio tests cover active/archive/overlap semantics and caller rollback. |
| Invalid/failure/read-only | Typed occupancy/property/limit/extra-field rejection; missing property 404; malformed cursor 422; character/UTF-8-byte oversized cursor 413; changed occupancy/source 409; source failure 503 rather than a successful empty page. Repeated reads leave audit counts unchanged. |
| Finance/portability | Each Home metric's captured Finance revision opens a contribution page with the same total. Existing encrypted Home restore reconstructs inventory facts while regenerating tokens; an original inventory token is rejected after runtime changes. No baseline or backup-format changes. |

Focused backend validation: **189 distinct tests passed**: the 172-case Home/HTTP/composition/Finance/performance/Portfolio/static-delivery run, followed by 26 inventory/directory cases after adding UTF-8 cursor-byte checks (nine overlapping cases). Eleven new inventory endpoint cases cover the new read. Ruff check/format passed for all eleven changed Python files; generated contracts remain reproducible. The [Slice 16 browser matrix](../../ui/validation.md#dash-001-slice-16-money-inventory-and-review-drill-downs) records money, inventory, source-resolution and cross-zone presentation proof without duplicating it here. Slice 17 delivers the subsequent live-refresh behavior.

## Slice 17 live attention refresh and protected interaction state

Delivered October 14, 2026. The existing workspace-owned React Query key for live attention is the sole refresh channel: source command success invalidates it through the established query-client predicate, while Home adds visible-focus, visible minute and server-declared `nextTransitionAt` triggers. The transition delay is the earlier of the next transition and one minute; hidden documents do not poll, and visibility return uses a non-cancelling refetch so same-key triggers share the in-flight request. The browser does not infer source transitions or write a snapshot.

`HomeRead.stale` derives from the live query's invalidated/elapsed freshness window. The zero-action assurance therefore requires an available, settled, non-stale live response. Home retains the displayed attention collection while a replacement introduces new preview rows, a higher count, or would remove an expanded disclosure; the staged result is announced with its exact current total. Selecting **Show updated list** replaces the one complete collection response. Source command recovery, dirty source forms and their current revisions remain outside Home.

| Frontend boundary | Focused evidence |
| --- | --- |
| Transition / polling | A declared transition schedules exactly one live refetch at the frozen browser instant; a response without a transition receives the visible 60-second check. |
| Focus / concurrency | Repeated focus events during one active attention request keep one request for that query key. Existing timeout/retry and late-scope cancellation tests remain authoritative. |
| Interaction / assurance | An expanded row remains expanded while a staged response is held; new work is announced before replacement. In-flight, invalidated, timed-out and failed checks withhold all-clear language. |
| Boundaries | No new HTTP operation, write, cache, snapshot or cron job is introduced. Existing workspace/runtime admission, source command invalidation and source-owned recovery remain unchanged. |

Focused browser validation: **8 cases passed** in `home-layout.spec.ts`, including the two new transition/minute refresh cases. Packaged build, generated-contract reproducibility, lint, complete type checking and changed-file formatting passed. Global formatting remains blocked only by unchanged `demo/dataset.json` and `demo/README.md`.

## Slice 18 integrated live-read gate

Delivered October 14, 2026. Slice 18 adds no protocol, endpoint or persisted state. It records the acceptance decision against the existing live contracts: the operator’s source/action and collection responses remain authoritative; Home continues to apply only admitted workspace/runtime/scope results, and the existing source-command invalidation/recovery contracts remain in force.

Ten sequential packaged, supported-local browser samples measured initial Home p95 **881 ms**, collection p95 **341 ms**, live-attention refresh p95 **334 ms** and in-app shell navigation feedback p95 **98 ms**. The focused 1/10/50-property backend performance suite also passed, retaining Slice 11 query/worker/read-duration ceilings. Because these measurements meet the one-second read and 100-ms shell targets, no bottleneck authorizes a cache: conditional Slices 19–20 are explicitly skipped. Optional independent cron remains post-MVP.
