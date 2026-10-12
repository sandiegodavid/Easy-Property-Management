# Providers, categories and reputation

## Responsibility and profiles

Providers reuses shared Party identity and owns provider state (`preferred`/avoid context and lifecycle), services, service areas, manual prior-work context, references and external reputation links. Issue-backed work history remains Maintenance-owned; imported/manual prior work is labeled as such.

## Categories and selection

Provider categories are a flat editable workspace catalog with stable seeded identities, independent revisions and archive/restore history. Providers have zero or more retained category assignments; zero is valid Uncategorized. Services remain separate free-form labels. Maintenance issue categories, Provider categories and service labels have no implicit equivalence.

Renaming changes current classification, while historical events and original command responses retain their facts. Category archival prevents new active use without deleting past assignments. Restoration preserves identity. Classification is advisory context, not an assignment eligibility engine.

## Profile and child workflows

Create a new Party/profile or designate an existing Party. Maintain profile, preferred contact, services, areas, history, references and reputation children through source-owned commands. Validate child membership before dispatch; archival retains history and observes active-role/reference guards. Profile/child command recovery and category recovery use their respective owning ledgers and revisions.

Reputation links are manually recorded safe URLs with source, notes and last-checked date. They are pointers rather than fetched ratings; no scraping or third-party synchronization occurs. General activity excludes sensitive notes and credential-like data. Search/list paging is bounded and source-side rather than hydrating each profile separately.

## API and integration

`/api/providers` owns profiles and children; `/api/provider-categories` owns the catalog; category assignment routes belong to the selected Provider. Both provide ID/key receipt reads. Maintenance displays saved service/area/category and avoid-state context, requires its own assignment decision and applicable override, and never rewrites Provider history to fit an issue.

Browser setup/management exists in the current frontend. Legal engagements and spreadsheet onboarding remain separate planned work.

## Browser workflow boundary

Provider browser workflows cover profiles, categories/assignments, services/areas, manual work history, references and reputation with revision-safe child operations, explicit source review and original receipts. Providers remains a configurable destination and is reachable within Maintenance. See the [workflow guide](../ui/workflows.md) and [browser validation](../ui/validation.md) for implementation and evidence entry points.

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

The following executable specifications are the starting point for focused validation. This documentation consolidation did not rerun them or establish feature completion.

- [test_category_command_readiness.py](../../application/apps/server/app/modules/vendors/tests/test_category_command_readiness.py).
- [test_child_command_readiness.py](../../application/apps/server/app/modules/vendors/tests/test_child_command_readiness.py).
- [test_command_readiness.py](../../application/apps/server/app/modules/vendors/tests/test_command_readiness.py).
- [test_slice20_router_boundaries.py](../../application/apps/server/app/modules/vendors/tests/test_slice20_router_boundaries.py).
- [test_vendors.py](../../application/apps/server/app/modules/vendors/tests/test_vendors.py).

Use the [shared validation matrix](../platform/persistence.md#validation-matrix) when changing this boundary. Core browser acceptance is recorded in [browser validation](../ui/validation.md); later capability acceptance remains in [active work](../active/README.md).
