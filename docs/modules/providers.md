# Providers, categories and reputation

## Responsibility and profiles

Providers reuses shared Party identity and owns provider state (`preferred`/avoid context and lifecycle), services, service areas, manual prior-work context, references and external reputation links. Issue-backed work history remains Maintenance-owned; imported/manual prior work is labeled as such.

## Categories and selection

Provider categories are a flat editable workspace catalog with stable seeded identities, independent revisions and archive/restore history. Providers have zero or more retained category assignments; zero is valid Uncategorized. Services remain separate free-form labels. Maintenance issue categories, Provider categories and service labels have no implicit equivalence.

Renaming changes current classification, while historical events and original command responses retain their facts. Category archival prevents new active use without deleting past assignments. Restoration preserves identity. Classification is advisory context, not an assignment eligibility engine.

Settings → Provider categories exposes active and archived groups separately, with source-owned effective Provider counts and add/rename/description/order/archive/restore commands. Providers keeps the same administration view for contextual access. Normal category pickers exclude archived entries. The directory has one active-category picker plus Categorized/Uncategorized coverage; new Provider creation supports multiple categories atomically. Category and assignment commands use their respective displayed revisions and original-key receipts. Archive retries retain the original reason; changed-reason retries conflict, and unchanged patches do not create business mutation audits.

Categories organize the directory and later recommendations; Services describe specific offerings or practice areas. Legal / Attorney is a seeded category, not a legal engagement or a Maintenance assignment. Provider archival removes effective classification/counts while retaining assignments for historical detail; restoration recovers eligible classification.

## Profile and child workflows

Create a new Party/profile or designate an existing Party. Maintain profile, preferred contact, services, areas, history, references and reputation children through source-owned commands. Validate child membership before dispatch; archival retains history and observes active-role/reference guards. Profile/child command recovery and category recovery use their respective owning ledgers and revisions.

Reputation links are manually recorded safe URLs with source, notes and last-checked date. They are pointers rather than fetched ratings; no scraping or third-party synchronization occurs. General activity excludes sensitive notes and credential-like data. Search/list paging is bounded and source-side rather than hydrating each profile separately.

The Reputation links section provides explicit external-review actions for active safe HTTPS pointers. Links open a new tab with opener isolation and no referrer. Reading, saving and reviewing local history make no external requests. Each record exposes bounded contextual audit history on demand, including original URLs/notes; the summary returns a count, while general activity redacts URLs and notes. Archived links remain available through the Provider history toggle and restore retains their IDs. URL and note text is displayed verbatim.

## API and integration

`/api/providers` owns profiles and children; `/api/provider-categories` owns the catalog; category assignment routes belong to the selected Provider. Both provide ID/key receipt reads. Maintenance displays saved service/area/category and avoid-state context, requires its own assignment decision and applicable override, and never rewrites Provider history to fit an issue.

Browser setup/management exists in the current frontend. Legal engagements and spreadsheet onboarding remain separate planned work.

## Browser workflow boundary

Provider browser workflows cover profiles, categories/assignments, services/areas, manual work history, references and reputation with revision-safe child operations, explicit source review and original receipts. Providers remains a configurable destination and is reachable within Maintenance. See the [workflow guide](../ui/workflows.md) and [browser validation](../ui/validation.md) for implementation and evidence entry points.

Provider detail labels manual prior work separately from Maintenance-owned issue journals. The directory supports combined name/context, complete service/area label, reference, lifecycle and preferred/avoid filters. Designating a shared identity retains its Party ID and revision; Provider archive/restore preserves that identity and independently retained children.

## Implementation map

- [Domain values and invariants](../../application/apps/server/app/modules/vendors/domain).
- [Use cases and application ports](../../application/apps/server/app/modules/vendors/application).
- [HTTP contracts](../../application/apps/server/app/modules/vendors/api).
- [Persistence and source adapters](../../application/apps/server/app/modules/vendors/infrastructure).

Persistence identities below are read from the current models. Column definitions, checks and indexes live in the linked models and the [current baseline](../../application/database/sqlite-migrations/versions/0001_initial_schema.py); update them together.

| Tables | Model definitions |
| --- | --- |
| `provider_profiles`, `provider_command_operations`, `provider_category_command_operations`, `provider_categories`, `provider_category_assignments`, `provider_services`, `provider_service_areas`, `provider_work_history`, `provider_references`, `provider_reputation_links` | [sqlalchemy_models.py](../../application/apps/server/app/modules/vendors/infrastructure/sqlalchemy_models.py) |

## Validation

VEND-001 and VEND-002 acceptance was completed on October 12, 2026. Their [profile acceptance record](../archive/designs/VEND-001_DESIGN_COMPLETED_2026-10-12.md) and [reputation acceptance record](../archive/designs/VEND-002_DESIGN_COMPLETED_2026-10-12.md) record focused results and check limitations. VEND-CAT-001's [October 13 acceptance](../archive/designs/VEND-CAT-001_DESIGN_COMPLETED_2026-10-13.md) records catalog/assignment/browser completion, 111 focused Provider backend tests, retained seed/audit validation, constant-budget paging and encrypted catalog/assignment/receipt preservation.

- [test_category_command_readiness.py](../../application/apps/server/app/modules/vendors/tests/test_category_command_readiness.py).
- [test_child_command_readiness.py](../../application/apps/server/app/modules/vendors/tests/test_child_command_readiness.py).
- [test_command_readiness.py](../../application/apps/server/app/modules/vendors/tests/test_command_readiness.py).
- [test_slice20_router_boundaries.py](../../application/apps/server/app/modules/vendors/tests/test_slice20_router_boundaries.py).
- [test_vendors.py](../../application/apps/server/app/modules/vendors/tests/test_vendors.py).

Use the [shared validation matrix](../platform/persistence.md#validation-matrix) when changing this boundary. Core browser acceptance is recorded in [browser validation](../ui/validation.md); later capability acceptance remains in [active work](../active/README.md).
