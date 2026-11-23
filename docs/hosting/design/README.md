# Hosting designs

The [Hosted MVP design](HOSTED_MVP_DESIGN.md) is the authoritative architecture and
product specification for **HOSTED-001** (H01–H12). It is a navigation index backed by
focused guides in `mvp/`:

- **Core**: [scope](mvp/scope.md) · [architecture and access](mvp/architecture-and-access.md) · [delivery plan](mvp/delivery-plan.md)
- **Workflows**: [onboarding](mvp/onboarding.md) · [subscriptions, storage, and runtime](mvp/subscriptions-storage-and-runtime.md) · [recovery](mvp/recovery.md) · [releases](mvp/releases.md)
- **Controls**: [operations and sources](mvp/operations-and-sources.md) · [plans and budgets](mvp/plans-and-budgets.md) · [implementation contracts](mvp/implementation-contracts.md) · [validation](mvp/validation.md)

## Delivered Slice Designs (H01–H04)

| Slice | Design | Status & Final Exit Evidence |
| --- | --- | --- |
| **H01** | [HOSTED_MVP_H01_DESIGN.md](HOSTED_MVP_H01_DESIGN.md) | **Done** — [H01.7 handoff](../qualification/reports/HOSTED_MVP_H01_7_HANDOFF_2026-11-11.md) |
| **H02** | [HOSTED_MVP_H02_DESIGN.md](HOSTED_MVP_H02_DESIGN.md) | **Done** — [Foundation guides](../foundation/README.md) · [H02.11 handoff](../qualification/reports/HOSTED_MVP_H02_11_HANDOFF.md) |
| **H03** | [HOSTED_MVP_H03_DESIGN.md](HOSTED_MVP_H03_DESIGN.md) | **Done** — [H03.12 exit review](../qualification/reports/HOSTED_MVP_H03_12_EXIT_REVIEW_2026-11-22.md) · [Provider research](../../research/HOSTED_MVP_H03_IDENTITY_RESEARCH.md) |
| **H04** | [HOSTED_MVP_H04_DESIGN.md](HOSTED_MVP_H04_DESIGN.md) | **Done** — [H04.9 Free sizing](../qualification/reports/HOSTED_MVP_H04_9_FREE_SIZING.json) · [H04.10 exit review](../qualification/reports/HOSTED_MVP_H04_10_EXIT_REVIEW_2026-11-22.md) |

## Next Up

- **H05 (Nightly verified off-host recovery)**: design pending; see [recovery requirements](mvp/recovery.md) and [H04/H05 handoff gates](../qualification/reports/HOSTED_MVP_H04_10_EXIT_REVIEW_2026-11-22.md#handoff-to-h05).
- **Schema reference**: [Database schema master](../../database/overview.md).
- **Research input**: [SQLite upgrade workflow](../research/SQLITE_SCHEMA_UPGRADE_WORKFLOW_2026-10-31.md) (candidate input for H10, subordinate to one-writer and recovery rules).
