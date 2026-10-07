# OPS-001 — Operator Support Design

## Status

All 13 design recommendations were accepted on October 7, 2026. The resolved decisions below govern implementation; approval does not mark OPS-001 complete. No application code is included.

## Purpose

`OPS-001` supplies the bounded, operator-facing compositions and durable preferences that UI-001 needs without moving domain authority into the browser. It owns workspace bootstrap, navigation/appearance preferences, property and owner directory/overview reads, global search, coverage/review provenance, and recovery for incomplete short forms.

## Boundaries

- Source modules remain authoritative for property, owner, lease, money, maintenance, communication, and task facts. OPS-001 composes their application ports only; it never imports their persistence adapters or models or issues per-row reads.
- Domain drafts (lease, inspection, settlement, and similar) remain source-owned. OPS-001 is only for incomplete browser-form recovery where no domain draft exists.
- Owner statements, fees, balances, and disbursements remain respectively OWNER-001/005/002 work. An overview reports available source facts, never an inferred owner entitlement.
- No React implementation is part of OPS-001.

## Bootstrap and preferences

`GET /api/operator/bootstrap` returns one bounded response: workspace readiness, validated identity and runtime epoch, write capability, recovery actions, enabled capability IDs, preference revision, navigation preference, appearance preference, and a contract version. Bootstrap returns a typed HTTP 200 readiness envelope. A non-ready workspace returns an explicit `unavailable` or `busy` state with only backend-supported recovery actions; it is never represented as an empty portfolio.

Persist one versioned workspace preference record:

| Field | Rule |
| --- | --- |
| `appearance` | `light` or `dark`. |
| `destination_order` | Valid permanent destination IDs, each at most once. |
| `hidden_destination_ids` | Hideable IDs only; Home and Settings cannot be hidden. |
| `revision` | Required optimistic-concurrency revision. |

`GET /api/operator/preferences` returns stored preferences or revision-0 defaults without a write. `PUT /api/operator/preferences` validates IDs, expected revision, and idempotency key atomically with audit and an operation result. Hidden destinations remain discoverable under More and never hide unresolved work from DASH-001.

## Directory, overview, and search reads

Provide set-based, cursor-paginated reads with matching totals, stable ID tie-breaks, `asOf`, and availability/provenance per section:

- `GET /api/operator/properties`: recognition identity, ownership context, occupancy/availability, attention state, applicable coverage summary, and explicit filter values. Search supports address, tenant, and owner text.
- `GET /api/operator/properties/{id}/overview`: identity, occupancy, owners, current lease, available money summary, next actions, coverage, and contextual routes. It does not claim unavailable information is zero.
- `GET /api/operator/owners` and `/owners/{id}/overview`: owner identity, related property summaries, actionable records, conversation/lease/maintenance summaries, and only available money facts, each labeled with provenance.
- `GET /api/operator/search`: bounded grouped results with source type/ID, label, context, archived marker, typed internal route target, stable cursor, and exact query echo. Results from hidden destinations remain eligible; archived records require an explicit include option.

Every cross-module call is through a consumer-neutral application read port and is batched by IDs. Server sections are `available` or `unavailable`; the UI may mark a retained prior result `stale` with its original timestamp/revision. Independent section failure cannot erase successful sections. A source failure affecting collection membership, filtering, ordering, or totals fails that collection. Every successful composition uses one deferred snapshot and captured instant.

## Coverage and review provenance

Derive an explicit coverage result per supported area: `area`, `applicability`, `state`, `cause`, source/evidence revision, `lastManualReviewAt`, `trigger`, and `resolutionRoute`. States are Recorded, Needs review, Missing required information, and Not applicable.

The initial supported areas are occupancy/availability, lease, rent, deposit, and maintenance. Triggers are relevant source changes or an explicit review date; a generic row update timestamp is insufficient. Manual review records actor, timestamp, basis, and the source revision reviewed. Not applicable requires an allowed reason and never bypasses required data. Coverage is operational visibility, not legal or physical-property compliance certification.

## Incomplete-form recovery

Persist a versioned, registered short-form recovery record through an atomic autosave and mark it saved only after acknowledgment: workflow/form key, related source identity, schema version, payload, revision, saved timestamp, and expiry policy. It excludes credentials, raw file bytes, and official domain state. APIs support list/load/update/discard with optimistic concurrency and idempotent mutation results. Records are limited to 64 KiB serialized UTF-8, 100 active records per workspace, and 30 days since acknowledged save; unresolved command outcomes are retained until reconciled and count toward the same capacity. A schema mismatch is recoverable but cannot silently replay an incompatible payload.

The browser distinguishes dirty, saving, saved, failed, and conflicted. It must not claim a local draft is official; substantive domain drafts use their source contract instead.

## Resolved design decisions

### 1. Operator module ownership

Add an `operator` module with application services, typed API models, and OPS-owned persistence. Bootstrap wires source protocols and runtime identity. Platform remains responsible for generic database, errors, locks, and audit mechanics. Architecture assigns this responsibility to the `operator` module.

### 2. Workspace readiness and supported recovery

Bootstrap returns a typed 200 readiness envelope even when domain data cannot be opened, with `ready`, `busy`, or `unavailable`, a safe reason code, stable workspace identity only when validated, runtime epoch, and `canWrite = ready and writerLockAcquired`. Unavailable preferences are explicitly unavailable, not silently initialized. Ordinary OPS reads and writes enforce readiness inside their application boundary and return 503 before database access. Advertise recovery actions only when implemented, with action kind distinguishing an API operation from product-owner CLI/setup guidance. Do not advertise functional Create/Open picker buttons before a supported local-host mechanism exists.

### 3. One snapshot for composed reads

One deferred read transaction per composed response, one captured UTC instant, and source-owned application readers that accept the same connection and instant. OPS may query its own tables and invoke source protocols; source adapters own their tables and joins. Extend Finance through a transaction-aware summary boundary that preserves FIN-003 calculations and integrity checks. Do not call its independently transactional public methods and claim atomic cross-domain consistency. Counts, eligibility, page selection, and source hydration must use the same snapshot. Property-local date classification uses the captured instant and stored source zone.

### 4. Cursor freshness and partial failures

Bind opaque cursors to endpoint/version, normalized filters/sort, workspace ID, runtime epoch, source revision, captured instant, and last sort key plus ID. Use the AUDIT-001 opaque marker in the caller-owned snapshot; do not derive freshness from a generic row timestamp. Apply a 15-minute continuation lifetime and return typed 409 when expired or changed; retain filters for restart. Include relevant property-local date changes in invalidation. Independent overview sections may fail separately; a failure affecting membership, counts, ordering, or filters fails that collection rather than returning an incomplete successful page. Without a persisted cache, server sections are `available` or `unavailable`; `stale` describes a previously successful UI result with its original timestamp/revision, never fabricated server data. Unexpected bugs must not be hidden by broad exception handling.

### 5. Directory and nested collection bounds

Default 50/max 100 directory items; default 10/max 50 items per overview section, each with matching total, continuation, and a typed View all target. Use normalized display label/address plus ID for directory ordering. Recognition cards include bounded previews and full related counts, not entire relationship histories. Enumerate filters in OpenAPI, preserving PORT-003 occupancy, availability, and ownership values. Apply membership filters before pagination; never filter only a hydrated page. Include validated query echo and total under identical filters. Select by IDs and hydrate through fixed batches, not `get()` loops or full-portfolio list reads.

### 6. Owner relationships and money scope

Owners are client-owner Parties with retained Portfolio ownership relationships. Default directory to current effective relationships on each property's local date, with explicit former/archived options. Owner detail retains historical access even after the last relationship ends. Never fabricate a local-operator Party. Default owner operating overview to currently related properties; history is explicitly selectable and labels relationship intervals. Require `fromOn`/`throughOn` for money sections, or omit them with an explicit needs-period state. Show selected properties' whole-property FIN-003 activity, including mixed ownership, with scope and dates; never prorate by shares or label it money due to the owner. Historical owner-attributed funds remain later owner-accounting work. Large owner scopes need source-side set selection, not truncation at Finance's 100-property input limit.

### 7. Coverage derivation and applicability

Derive per-area results from facts; persist append-only OPS review/justified-non-applicability decisions rather than mutable copies of source facts. Scope occupancy, lease, rent, and deposit to a Space and relevant lease where applicable; Maintenance review is property-scoped. Return all causes and a leading state: missing required information before needs review before recorded; justified non-applicability is valid only when source rules allow it. Source failure produces unavailable coverage, never Missing or Recorded. The following rules govern the initial areas. Typed source fields and reason codes must implement these rules:

| Area | Relevant facts and trigger | Resolution |
| --- | --- | --- |
| Occupancy/availability | Unknown/conflicting current status; occupancy/availability or relevant effective-date transition | Source-owned status/review action |
| Lease | Source rules require lease context for occupied rental; missing/changed lease context | Link/record/review authoritative lease; do not assume every occupancy kind requires a lease |
| Rent | Executed lease with missing/unconfirmed expectations or relevant unsynchronized term changes | FIN-001 schedule review/synchronization; acknowledgment cannot replace synchronization |
| Deposit | Lease-required deposit terms versus recorded account/tracking context; relevant term/account/settlement changes | FIN-008 setup/review; no-deposit terms may justify Not applicable; do not require full receipt before it is due |
| Maintenance | Recorded issues and last explicit property review; relevant issue/outcome changes or operator-selected review date | Review source issues and explicitly acknowledge current property knowledge; no issues is not proof of no problems |

Use area-specific evidence revisions so an unrelated repair or preference edit does not invalidate a rent review. Global audit revision remains useful for cursor invalidation, not coverage-trigger policy.

### 8. Revision-safe coverage reviews

Define typed review commands keyed by subject and area with expected evidence revision, actor `local_operator`, review basis/reason, optional explicit next-review date, and idempotency key. Validate current source facts and append the decision plus audit in one immediate transaction. Changed evidence returns 409; identical replay returns the original result; changed payload with the same key returns 409. A review records the operator's acknowledgment, not a domain approval or repair/lease/finance transition. Dates use the subject property's zone. OPS exposes reusable coverage reads to DASH-001; it does not own Home urgency or queue placement.

### 9. Search scope and disclosure

Initial search registry includes properties/spaces, related client owners, tenant identities, leases, recorded communication metadata, maintenance issues, and tasks. Add provider and later legal/HOA/import/AI types only through registered completed source contracts. Search normalized identity/context labels with literal, case-insensitive matching; escape SQL wildcard characters. No LLM, separate search service, raw document indexing, applicant financial evidence, raw Intake text, recovery payloads, or credentials. Source adapters return approved metadata and typed identity/section targets; UI maps targets through its route registry, never arbitrary URLs. Use default 10/max 50 results per type with independent per-type continuation/counts; a failed group is unavailable. Source-side filter contracts must support property-directory tenant/owner matching and owner-directory property-address matching. Query limit: 240 characters, minimum two non-whitespace characters.

### 10. Preferences and capability evolution

Use stable IDs shared by backend validation and UI registry, with a versioned backend capability descriptor. Default to the UI-001 order and light appearance. Home and Settings are fixed and cannot be hidden/reordered outside their positions. Validate duplicate/unknown IDs and hideability; omitted customizable IDs append in default order. Capability absence hides entry points without deleting saved preferences, and hidden available destinations stay in More/search/context. A missing preference row represents defaults at revision 0 without a GET write. Updates include expected revision, idempotency key, one atomic audit, and explicit conflict response. Add a dedicated typed preference GET as well as bootstrap projection.

### 11. Recovery schemas, limits, and unknown outcomes

Register supported short-form schemas with field allowlists and a source/domain-draft exclusion rule. Bounds: 64 KiB serialized UTF-8 per record, 100 active records per workspace, and 30 days from acknowledged save. Exclude credentials, raw files, sensitive applicant evidence, and raw Intake evidence; use validated IDs for already saved resources. Store base source revision, attempt key/request fingerprint, and owning receipt/replay reference when a supported consequential command needs outcome recovery. Records with unknown outcomes count toward the 100-active-record limit, cannot expire or be discarded automatically until reconciled, and block new recovery admission if capacity is exhausted. Recovery never authorizes committing a domain action. Before reuse, revalidate current capability, source lifecycle/revision, and schema. Incompatible records permit safe inspection/discard, not automatic submission. Expiry is disclosed and performed by a bounded explicit/background operation, never a read-side write.

### 12. Atomic mutations, errors, and portability

Preferences, coverage decisions, and recovery mutations use one immediate transaction for validated change, revision advance, durable operation result, and audit. Replay checks precede revision conflict; identical key/payload returns the recorded result without duplicate audit, mismatch returns 409. Define receipt/replay lookup and retention explicitly; operation-result retention is at least 30 days and never shorter than a linked unresolved attempt. Use `platform/api_errors.py`: 413 for oversized content, 422 malformed fields, 404 unknown records, 409 revision/evidence/key conflicts, 503 unavailable/busy workspace, and safe 500 integrity/read failures. Strict request schemas reject unknown fields. Keep payload contents out of logs and audit snapshots; audit metadata, reasons, revisions, and identity instead. Add OPS-owned tables/checks/indexes to the latest greenfield baseline and retained-workspace validators. Portable backup includes preferences, reviews, recovery records, and receipts; restore preserves workspace facts but regenerates runtime epoch and revalidates recovered payloads. No legacy format or migration compatibility work.

### 13. Query budgets and acceptance gates

Establish budgets before adapter implementation, measuring every SQL statement including markers and counts. Initial ceilings: 30 SELECTs for each directory response, 50 for a property/owner overview, and 4 per registered search type plus 2 shared queries. Counts do not grow with page size, child count, or portfolio size; nested arrays retain explicit caps. Revise a budget only with documented query-plan evidence. Implement indexes for actual filters/sorts and validate plans on populated fixtures. Response size and hydration must also remain bounded; a fixed query count does not excuse reading every record.

## Required design validation matrix

| Area | Required scenarios and outcomes |
| --- | --- |
| Happy paths | Property/owner search, recognition, filters, former relationships, bounded overview sections, explicit-period money and drill-down, preferences, coverage review, recovery resume |
| Invalid combinations | Unknown IDs/capabilities, duplicate destinations, hidden Home/Settings, invalid area/subject, unjustified Not applicable, incompatible recovery schemas, oversized payload 413, malformed input 422 |
| Idempotency/retry | Lost mutation response replays once; key/payload mismatch 409; stale revision 409; unknown domain outcome reconciles through owning receipt before a new attempt |
| Transaction rollback | Fail audit/receipt during save: no preference/review/recovery mutation remains; source evidence changes before review: no stale acknowledgment commits |
| Snapshot/partial failure | Write between source reads cannot produce mixed successful facts; counts match slices; membership-source failure fails directory; independent overview failure preserves other sections without zero substitution |
| Persistence/schema | Latest baseline initializes; malformed retained records fail validation; review history/receipts remain consistent; defaults require no read writes; expiry cannot silently discard unknown outcomes |
| Backup/restore | Preserve preferences/reviews/recovery and operation results; exclude secrets; invalidate old epoch/cursors; do not silently submit restored drafts |
| Query/size budgets | Large portfolios, co-owners, child histories, and multiple source types stay within fixed budgets and caps; no per-row service calls or full-list filtering |
| Time/freshness | Property-local midnight, scheduled source changes, review date reached, runtime stop/failed refresh, workspace switch/restore, expired continuation: explicit refresh/unavailable behavior |
| Privacy/disclosure | Search metadata cannot leak sensitive evidence; source disclosure audit failure denies evidence; recovery/log/audit outputs omit excluded content |

## Implementation baseline and dependencies

Baseline inspected October 7, 2026 at `98bdb4a`. These observations describe existing code, not the approved target implementation.

- No Operator module or `/api/operator/*` router is composed in `application/apps/server/app/bootstrap/api.py:646–668`. Preferences, coverage reviews, recovery records, and cross-domain search require new OPS-owned contracts and persistence.
- PORT-003 already offers bounded `PortfolioService.page_properties()` in `application/apps/server/app/modules/portfolio/application/service.py:423`. Its page has totals and batched occupancy facts. It does not yet supply the full OPS directory search, coverage, or cross-domain filters. Reuse its source semantics; do not scan `list_properties()` to implement the directory.
- FIN-003 already supplies typed `MoneySummaryReader` in `application/apps/server/app/modules/finance/application/money_ports.py:39`, with explicit period/scope, separate deposit facts, revision-bound cursors, and readiness enforcement. Its public methods open their own snapshots. A common OPS snapshot needs an additional reusable Finance application boundary, not direct Finance-table access.
- Existing Portfolio context readers accept a caller-owned connection and batches; source-owned Portfolio/Lease location relations support composable reads. These are useful precedents, but existing service methods and protocols do not collectively provide all directory, overview, search, and coverage facts.
- Party identity search is currently list-returning (`application/apps/server/app/modules/parties/application/service.py:358`), not a complete paginated owner directory. An owner directory must derive relationships from Portfolio, not equate every Party with an owner.
- COM-001 and OWNER-004 already have bounded source lists, but calling each service per property would violate the composition contract. Add only the necessary reusable, batched application facts.
- TASK-002 is an explicit backlog dependency, but waiting/follow-up fields are absent from the current Task domain model. Treat its completion as a readiness gate, not an already available source.
- Existing dependencies cover the principal required sources. AUDIT-001 supplies auditing; LOCAL-001/002 and PORT-001/002 are transitive foundations. FIN-002 arrives through FIN-003; TASK-001 through TASK-002. No dependency on later OWNER-001/002/005, DASH-001, or UI-001 should be added. LEGAL-001, HOA-001, import, provider, and AI integrations are capability-gated extensions, not new OPS prerequisites. The initial mandatory search registry excludes these extensions; completed source contracts may register them later without blocking OPS-001.

## Verification and definition of done

Verify bounded query counts for populated directories/overviews, matching totals and cursors, no per-row fan-out, `asOf` consistency, partial availability, tenant/owner/address search, owner-history preservation, preference conflicts, coverage trigger/review history, and restart/form-conflict recovery. OPS-001 is complete when these typed APIs and audited mutable records are implemented without browser-side domain derivation.
