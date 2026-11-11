# Hosting designs

The [fresh hosted MVP design](HOSTED_MVP_DESIGN.md), consolidated November 10, 2026,
is the current accepted hosting direction. It owns scope, architecture, tiers,
identity, Admin/operator workflows, automation and validation gates. The
[Hosting Plan](../Hosting_Plan.md) summarizes it; the
[MVP acceptance register](../qualification/HOSTED_MVP_ACCEPTANCE.md) tracks proof.

The MVP design is a navigation index backed by focused guides in `mvp/`. Start with
[scope](mvp/scope.md), [architecture and access](mvp/architecture-and-access.md),
then the [delivery plan](mvp/delivery-plan.md). Use [recovery](mvp/recovery.md),
[storage/subscriptions](mvp/subscriptions-storage-and-runtime.md) and
[releases](mvp/releases.md) for specific workflows. The
[schema catalog](../../DATABASE_SCHEMA.md) links to separate per-store dictionaries.

| Reference | Status |
| --- | --- |
| [Hosted MVP design](HOSTED_MVP_DESIGN.md) | Current design; implementation/deployment not established by documentation |
| [Earlier demo design](HOSTED_DEMO_DESIGN.md) | Superseded as the current hosting direction; preserved for the earlier synthetic topology |
| [Earlier demo Admin proposal](HOSTED_DEMO_ADMIN_DESIGN.md) | Superseded proposal; its manual approval, expiry, capacity and tooling choices are not the fresh target |

The [SQLite upgrade research](../research/SQLITE_SCHEMA_UPGRADE_WORKFLOW_2026-10-31.md)
remains a candidate technical input, subordinate to current one-writer, recovery,
release-compatibility and post-reopen data-preservation requirements. [HOSTED-001](../../FEATURE_BACKLOG.md) now schedules H01–H12; Pilot 0 at H06 is the first release milestone, not completion of the whole target. No implementation status is established by documentation.

## H01 implementation handoff

- [H01 detailed design](HOSTED_MVP_H01_DESIGN.md): current-code inventory, deployment/source contracts, Admin-lite UI and proof plans.
- [Database schema master](../../DATABASE_SCHEMA.md): shared store ownership and table/column dictionary; proposed hosted schema is not implemented.
