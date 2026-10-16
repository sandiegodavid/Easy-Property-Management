# Operator compositions, information review and form recovery

## Responsibility and bootstrap

Operator composes source-owned facts for property/owner directories and overviews, search and information review. It owns preferences, manual information-review provenance and incomplete-form recovery. It cannot turn a presentation fact into a domain transition.

Bootstrap returns a typed ready/busy/unavailable envelope before domain reads, with validated workspace identity/runtime epoch, capabilities and truthful writer permission. Unavailable is never an empty portfolio. Supported recovery actions distinguish actual operations from local setup guidance. Ordinary operations enforce runtime readiness inside their application boundary.

## Preferences and navigation

Preferences persist light/dark, destination order and hideable destinations, with revision-zero defaults read without writing. Home/Settings are fixed. Hidden destinations remain under More and contextual links; obligations are still source facts. Preference changes use revision/key, atomic audit and original-result recovery.

## Directories and overviews

One deferred snapshot and one captured instant govern source selection, counts and hydration through neutral batched ports. Directory defaults are 50/max 100; contextual sections default 10/max 50, each with matching total/continuation and typed targets. Membership/filter/order failure fails that collection; independent section failures leave other sections available.

Owners are retained client-owner relationships, with current defaults and explicit former/archived history. Never invent a local-operator owner Party. Money requires explicit dates and describes selected Properties' whole-property activity, including mixed ownership. It never prorates shares or labels that activity as owner entitlement.

Cursors bind endpoint, workspace/runtime, filters, captured instant and read marker, with 15-minute lifetime. Changed views require a new first page. Server availability is available/unavailable; stale is a browser's retained older result with original timestamp.

## Information review and search

**Information review** is implemented internally as `coverage`. Use Information review for the feature in the frontend, operator manual and current developer prose, with area titles such as **Maintenance information review** and **Occupancy information review**. Reserve `coverage` for references to actual code, API fields, routes and persisted identifiers, including `/coverage/...`, `/api/operator/coverage/...`, `CoverageResult` and `coverage.review`; these identifiers remain unchanged. Historical designs and acceptance records retain their original terminology. Information review describes recorded information sufficiency and review needs, not insurance/service coverage, continuous monitoring, legal-compliance certification or a guarantee that no property problems exist.

Information review uses source facts for occupancy, Lease, rent, deposit and Maintenance. Return applicability, state, causes, evidence revision, manual review provenance and a typed resolution target. Missing required information precedes needs-review/recorded; unavailable sources never count as complete. Non-applicability requires allowed reasons and cannot bypass required data. Information review acknowledgment does not synchronize rent or verify a repair.

DASH-001's `SQLiteCoverageAttentionReader` selects portfolio-wide information review through source-owned SQL relations. Exact review and applicability counts precede bounded continuation; shared pure information-review rules preserve manual-review provenance and typed resolution targets. `HomeCompositionService` composes Home and complete live Needs action on one deferred transaction and instant, grouping explicit active follow-ups before SQL counts/limits and retaining terminal-parent Task context. Labels and child/reminder previews are bounded batch projections. `/api/operator/home`, `/api/operator/home/attention` and `/api/operator/home/items` are typed worker-executed reads; composite continuations freeze capture and reject changed filters, source markers, runtime identity or expiry. Bootstrap advertises `operator.home` only with the complete current adapter bundle. The [Slice 11 backend proof](../archive/validation/DASH-001_CONTRACT_EXAMPLES_COMPLETED_2026-10-14.md#slice-11-backend-readiness-and-performance-proof) measures fixed query costs and sub-second local HTTP reads with 1/10/50 properties and 1,000 Tasks/expectations. The browser latency gate passed in Slice 18; current frontend behavior and evidence are described below.

Search is bounded literal metadata matching with typed targets, independent source groups, explicit archived inclusion and full matching counts. Raw source evidence, documents, credentials and recovery payloads are excluded. Hidden destinations do not hide eligible results.

## Incomplete forms and attempts

Registered forms hold incomplete input before a domain draft/command exists, with source identity and schema version. Limits are 64 KiB serialized UTF-8, 100 active records and 30 days since acknowledged save. Credentials, raw file bytes and raw Intake evidence are excluded. Unresolved outcomes count toward capacity and cannot expire/discard automatically.

Save is acknowledged and revision-safe. Preparing an attempt validates complete fields and computes the source-owned semantic fingerprint; it does not dispatch the business command. Reconcile reads the owning immutable original receipt. Unknown outcomes retain the exact key before any new attempt. Domain drafts stay source-owned; attachment recovery retains metadata/hash and requires matching byte reselection.

## Implementation navigation

Directory, overview, search and information-review services are separate from recovery/preferences. Form registries are under `application/*_forms.py`, with receipt adapters in bootstrap. Use the actual registry instead of historical slice counts. HTTP routers expose `/api/operator` reads, review and recovery actions. [Frontend architecture](../ui/frontend-architecture.md) explains client state and dispatch ownership.

## Browser workflow boundary

Browser consumers implement bounded contextual directories/overviews, independent section continuations, metadata search, source-backed information review and appearance/navigation. Information review is an allowlisted recoverable form with source fingerprint and original receipt; acknowledgment never fills required gaps. Shared recovery composes registered source commands without dispatching generic domain retries. Home aggregation is delivered under DASH-001. See the [workflow guide](../ui/workflows.md) and [browser validation](../ui/validation.md) for implementation and evidence entry points.

Home transport uses separate workspace/runtime/property-bound full and live queries, with the full query also bound to horizon and explicit money dates. Bootstrap's injected `serverTimeUtc` selects the default complete month. URL normalization, abort signals and response identity checks prevent obsolete scope results from being applied; missing readiness suppresses reads. Home presents work, appointments, information review and supporting money/inventory sections through shared disclosure and async components. Manual refresh retains original timestamps/input; delayed feedback, cancellable timeouts, independent retry and persistent new-attention announcements keep unavailable/stale results distinct from zero. [Collection routes](../ui/validation.md#dash-001-slice-14-collections-and-return-navigation) retain the preview capture, exact totals, default 50/max-100 bounds and typed source-return/scroll context. Changed or expired cursors require Restart; scope/horizon changes start a fresh page. [Expanded source actions](../ui/validation.md#dash-001-slice-15-source-workflows-and-recovery) expose bounded nested Task/reminder links, all-follow-up paging and source-specific review routes. Owning workflows reload current facts and authorize commands; Home return context survives their forms and recovery. Home never issues a generic lifecycle command.

Live attention refreshes on entry, visible focus/return, source-command invalidation, source-declared transitions and each visible minute, coalescing same-key requests. Stale, pending or failed checks suppress the zero-action assurance. New work is announced before replacement; expanded disclosures can retain the previous collection until the operator chooses the staged result. Source forms and original-result recovery remain in their owning workflows. Each other section retains its own capture time.

DASH-001 acceptance is recorded in the [completed design](../archive/designs/DASH-001_DESIGN_COMPLETED_2026-10-14.md) and [browser matrix](../ui/validation.md#dash-001-slice-18-integrated-experience-and-latency-gate). Measured live reads passed the local latency gate, so conditional snapshot Slices 19–20 were skipped. No Dashboard cache or scheduled worker is installed. Optional cron remains a post-MVP performance-gated proposal in the historical design; legal/HOA, showings, assistant health and estimated-value extensions retain their own backlog scope.

Search groups retain independent continuations and full counts. Restarting a stale group fetches a fresh first page with the same query/archive filter rather than reusing its original preview. Archived search results are opt-in, visibly labeled, and open retained contextual records. Hidden destinations remain reachable from eligible search/context links. Information review distinguishes missing information, recorded facts, review causes and source-owned non-applicability; a review receipt is not a repair, financial verification or completed source command.

[Home metric/inventory drill-downs](../archive/validation/DASH-001_CONTRACT_EXAMPLES_COMPLETED_2026-10-14.md#slice-16-money-inventory-and-review-drill-downs) retain the counted source scope: money opens Finance contributions with period, archive policy and captured revision; `/home/inventory` pages the exact active vacant/unknown Spaces through Portfolio's caller-transaction reader. Inventory tokens freeze the preview instant and reject changed sources/runtime. Information review resolution uses current owning context; agenda times show source-local time and zone alongside UTC. No new Home write or durable data is introduced.

## Implementation map

- [Domain values and invariants](../../application/apps/server/app/modules/operator/domain).
- [Use cases and application ports](../../application/apps/server/app/modules/operator/application).
- [HTTP contracts](../../application/apps/server/app/modules/operator/api).
- [Persistence and source adapters](../../application/apps/server/app/modules/operator/infrastructure).

Persistence identities below are read from the current models. Column definitions, checks and indexes live in the linked models and the [current baseline](../../application/database/sqlite-migrations/versions/0001_initial_schema.py); update them together.

| Tables | Model definitions |
| --- | --- |
| `operator_preferences`, `operator_recovery_records`, `operator_operations`, `operator_coverage_reviews` | [sqlalchemy_models.py](../../application/apps/server/app/modules/operator/infrastructure/sqlalchemy_models.py) |

## Validation

OPS-001 acceptance completed October 13, 2026: **519 focused backend tests, 20 packaged browser cases and 12 shared component/recovery cases passed**. The [completed acceptance matrix](../archive/designs/OPS-001_DESIGN_COMPLETED_2026-10-13.md) records composition, search, information review, preferences and recovery, audit/retained-data, encrypted portability and quality-check limits. DASH-001 Home acceptance completed October 14, 2026; its evidence is linked above. The following executable specifications remain regression entry points.

- [test_ai_recovery.py](../../application/apps/server/app/modules/operator/tests/test_ai_recovery.py).
- [test_command_recovery.py](../../application/apps/server/app/modules/operator/tests/test_command_recovery.py).
- [test_concern_recovery.py](../../application/apps/server/app/modules/operator/tests/test_concern_recovery.py).
- [test_context_sources.py](../../application/apps/server/app/modules/operator/tests/test_context_sources.py).
- [test_coverage.py](../../application/apps/server/app/modules/operator/tests/test_coverage.py).
- [test_coverage_integration.py](../../application/apps/server/app/modules/operator/tests/test_coverage_integration.py).
- [test_coverage_attention.py](../../application/apps/server/app/modules/operator/tests/test_coverage_attention.py).
- [test_home_composition.py](../../application/apps/server/app/modules/operator/tests/test_home_composition.py).
- [test_home_api.py](../../application/apps/server/app/modules/operator/tests/test_home_api.py).
- [test_home_performance.py](../../application/apps/server/app/modules/operator/tests/test_home_performance.py).
- [test_directories.py](../../application/apps/server/app/modules/operator/tests/test_directories.py).
- [test_endpoint_contracts.py](../../application/apps/server/app/modules/operator/tests/test_endpoint_contracts.py).
- [test_file_recovery.py](../../application/apps/server/app/modules/operator/tests/test_file_recovery.py).
- [test_finance_command_forms.py](../../application/apps/server/app/modules/operator/tests/test_finance_command_forms.py).
- [test_financial_batches.py](../../application/apps/server/app/modules/operator/tests/test_financial_batches.py).
- [test_identity_recovery.py](../../application/apps/server/app/modules/operator/tests/test_identity_recovery.py).
- [test_inspection_recovery.py](../../application/apps/server/app/modules/operator/tests/test_inspection_recovery.py).
- [test_intake_recovery.py](../../application/apps/server/app/modules/operator/tests/test_intake_recovery.py).
- [test_inventory_recovery.py](../../application/apps/server/app/modules/operator/tests/test_inventory_recovery.py).
- [test_operator.py](../../application/apps/server/app/modules/operator/tests/test_operator.py).
- [test_overviews.py](../../application/apps/server/app/modules/operator/tests/test_overviews.py).
- [test_provider_recovery.py](../../application/apps/server/app/modules/operator/tests/test_provider_recovery.py).
- [test_recovery_composition.py](../../application/apps/server/app/modules/operator/tests/test_recovery_composition.py).
- [test_search.py](../../application/apps/server/app/modules/operator/tests/test_search.py).
- [test_synchronization_recovery.py](../../application/apps/server/app/modules/operator/tests/test_synchronization_recovery.py).

Use the [shared validation matrix](../platform/persistence.md#validation-matrix) when changing this boundary. Core browser acceptance is recorded in [browser validation](../ui/validation.md); later capability acceptance remains in [active work](../active/README.md).
