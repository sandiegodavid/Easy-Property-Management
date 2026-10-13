# Operator compositions, coverage and form recovery

## Responsibility and bootstrap

Operator composes source-owned facts for property/owner directories and overviews, search and coverage. It owns preferences, manual coverage-review provenance and incomplete-form recovery. It cannot turn a presentation fact into a domain transition.

Bootstrap returns a typed ready/busy/unavailable envelope before domain reads, with validated workspace identity/runtime epoch, capabilities and truthful writer permission. Unavailable is never an empty portfolio. Supported recovery actions distinguish actual operations from local setup guidance. Ordinary operations enforce runtime readiness inside their application boundary.

## Preferences and navigation

Preferences persist light/dark, destination order and hideable destinations, with revision-zero defaults read without writing. Home/Settings are fixed. Hidden destinations remain under More and contextual links; obligations are still source facts. Preference changes use revision/key, atomic audit and original-result recovery.

## Directories and overviews

One deferred snapshot and one captured instant govern source selection, counts and hydration through neutral batched ports. Directory defaults are 50/max 100; contextual sections default 10/max 50, each with matching total/continuation and typed targets. Membership/filter/order failure fails that collection; independent section failures leave other sections available.

Owners are retained client-owner relationships, with current defaults and explicit former/archived history. Never invent a local-operator owner Party. Money requires explicit dates and describes selected Properties' whole-property activity, including mixed ownership. It never prorates shares or labels that activity as owner entitlement.

Cursors bind endpoint, workspace/runtime, filters, captured instant and read marker, with 15-minute lifetime. Changed views require a new first page. Server availability is available/unavailable; stale is a browser's retained older result with original timestamp.

## Coverage and search

Coverage uses source facts for occupancy, Lease, rent, deposit and Maintenance. Return applicability, state, causes, evidence revision, manual review provenance and a typed resolution target. Missing required information precedes needs-review/recorded; unavailable sources never count as complete. Non-applicability requires allowed reasons and cannot bypass required data. Coverage acknowledgment does not synchronize rent or verify a repair.

DASH-001's `SQLiteCoverageAttentionReader` selects portfolio-wide information review through source-owned SQL relations. Exact review and applicability counts precede bounded continuation; shared pure coverage rules preserve manual-review provenance and typed resolution targets. `HomeCompositionService` composes Home and complete live Needs action on one deferred transaction and instant, grouping explicit active follow-ups before SQL counts/limits and retaining terminal-parent Task context. Labels and child/reminder previews are bounded batch projections. `/api/operator/home`, `/api/operator/home/attention` and `/api/operator/home/items` are typed worker-executed reads; composite continuations freeze capture and reject changed filters, source markers, runtime identity or expiry. Bootstrap advertises `operator.home` only with the complete current adapter bundle. DASH-001 Slice 11 retains the integrated performance proof; its browser Home starts at Slice 12.

Search is bounded literal metadata matching with typed targets, independent source groups, explicit archived inclusion and full matching counts. Raw source evidence, documents, credentials and recovery payloads are excluded. Hidden destinations do not hide eligible results.

## Incomplete forms and attempts

Registered forms hold incomplete input before a domain draft/command exists, with source identity and schema version. Limits are 64 KiB serialized UTF-8, 100 active records and 30 days since acknowledged save. Credentials, raw file bytes and raw Intake evidence are excluded. Unresolved outcomes count toward capacity and cannot expire/discard automatically.

Save is acknowledged and revision-safe. Preparing an attempt validates complete fields and computes the source-owned semantic fingerprint; it does not dispatch the business command. Reconcile reads the owning immutable original receipt. Unknown outcomes retain the exact key before any new attempt. Domain drafts stay source-owned; attachment recovery retains metadata/hash and requires matching byte reselection.

## Implementation navigation

Directory/overview/search/coverage services are separate from recovery/preferences. Form registries are under `application/*_forms.py`, with receipt adapters in bootstrap. Use the actual registry instead of historical slice counts. HTTP routers expose `/api/operator` reads, review and recovery actions. [Frontend architecture](../ui/frontend-architecture.md) explains client state and dispatch ownership.

## Browser workflow boundary

Browser consumers implement bounded contextual directories/overviews, independent section continuations, metadata search, source-backed coverage review and appearance/navigation. Coverage review is an allowlisted recoverable form with source fingerprint and original receipt; acknowledgment never fills required gaps. Shared recovery composes registered source commands without dispatching generic domain retries. Home aggregation remains DASH-001. See the [workflow guide](../ui/workflows.md) and [browser validation](../ui/validation.md) for implementation and evidence entry points.

Search groups retain independent continuations and full counts. Restarting a stale group fetches a fresh first page with the same query/archive filter rather than reusing its original preview. Archived search results are opt-in, visibly labeled, and open retained contextual records. Hidden destinations remain reachable from eligible search/context links. Coverage distinguishes missing information, recorded facts, review causes and source-owned non-applicability; a review receipt is not a repair, financial verification or completed source command.

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

OPS-001 acceptance completed October 13, 2026: **519 focused backend tests, 20 packaged browser cases and 12 shared component/recovery cases passed**. The [completed acceptance matrix](../archive/designs/OPS-001_DESIGN_COMPLETED_2026-10-13.md) records composition/search/coverage/preferences/recovery, audit/retained-data, encrypted portability and quality-check limits. Home-specific tests and broader DASH-001 acceptance remain separately owned. The following executable specifications remain regression entry points.

- [test_ai_recovery.py](../../application/apps/server/app/modules/operator/tests/test_ai_recovery.py).
- [test_command_recovery.py](../../application/apps/server/app/modules/operator/tests/test_command_recovery.py).
- [test_concern_recovery.py](../../application/apps/server/app/modules/operator/tests/test_concern_recovery.py).
- [test_context_sources.py](../../application/apps/server/app/modules/operator/tests/test_context_sources.py).
- [test_coverage.py](../../application/apps/server/app/modules/operator/tests/test_coverage.py).
- [test_coverage_integration.py](../../application/apps/server/app/modules/operator/tests/test_coverage_integration.py).
- [test_coverage_attention.py](../../application/apps/server/app/modules/operator/tests/test_coverage_attention.py).
- [test_home_composition.py](../../application/apps/server/app/modules/operator/tests/test_home_composition.py).
- [test_home_api.py](../../application/apps/server/app/modules/operator/tests/test_home_api.py).
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
