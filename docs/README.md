# Developer documentation

Operators should start with the separate [operator manual](../manual/README.md), which covers installation/setup and task-based use. This directory is the developer reference.

## Start here

Read these in order for the whole project. Core UI-001 and DASH-001 Home delivery are complete; follow-up integrations remain active:

1. [Repository README](../README.md): setup, local workspace and development commands.
2. [Product brief](PRODUCT_BRIEF.md): intended users, operating vocabulary and product scope.
3. [Architecture](ARCHITECTURE.md): current module/data boundaries and composition.
4. [Current modules](#current-modules): implementation guides and code/test entry points.
5. [Active work](active/README.md): remaining delivery and proposed changes.

For a specific change, read its owning module, relevant shared platform contract and active feature design. Historical backlog designs are optional rationale, not the starting point.

## Current modules

| Area | Read first | Common deep dive |
| --- | --- | --- |
| Local data | [Workspace](modules/workspace.md) | Backup, restore, readiness and portable identity |
| History | [Audit](modules/audit.md) | Fail-closed events, privacy policies and read markers |
| Evidence | [Files](modules/files.md) | Publish/rollback, owning links, local/S3 integrity |
| People | [Parties](modules/parties.md), [Tenants](modules/tenants.md) | Identity, contacts, role guards and participants |
| Portfolio | [Portfolio](modules/portfolio.md) | Ownership, Property/Space revisions and occupancy timelines |
| Leasing | [Leases](modules/leases.md), [Inspections](modules/inspections.md) | Contract/physical lifecycle, condition evidence and comparison |
| Providers | [Providers](modules/providers.md) | Categories, services, prior work and reputation |
| Money | [Finance](modules/finance.md), [Owner accounting](modules/owner-accounting.md) | Rent, actual expenses, deposits, reports and owner claims |
| Owner operations | [Owner management](modules/owner-management.md) | Concern context, lifecycle and follow-up |
| Coordination | [Tasks](modules/tasks.md), [Communications](modules/communications.md) | Deadlines, waiting, reminders and manual interaction history |
| Source intake | [Intake](modules/intake.md) | Evidence envelope, provenance, deduplication and sensitive reads |
| Optional AI | [AI governance](modules/ai-governance.md) | Configuration, registries, review and uncertain external effects |
| Operator support | [Operator](modules/operator.md) | Composed reads, information review, search, preferences and recovery |
| Browser interface | [Operator experience](ui/operator-experience.md), [Frontend architecture](ui/frontend-architecture.md) | [Workflows](ui/workflows.md), [validation](ui/validation.md), state and dispatch |

## Shared contracts

- [Persistence, transactions and validation](platform/persistence.md).
- [API errors, reads and original-result recovery](platform/api-contracts.md).
- [Local transport, secrets and audit disclosure](platform/security-and-audit.md).
- [Code quality and validation commands](CODE_QUALITY.md).

## Delivery, decisions and research

[Feature backlog](FEATURE_BACKLOG.md) owns feature status, outcome and dependencies. [Current UI guides](ui/operator-experience.md), [workflows](ui/workflows.md), [frontend architecture](ui/frontend-architecture.md) and [validation evidence](ui/validation.md) describe completed core browser and Home delivery. [Active designs](active/README.md) contain proposed domain changes, UI-002 follow-up workflows and UI-003 connected-assistant work. The [agent triage design](active/agent-triage-design.md) is the accepted direction for remaining assistant-related backlog. Completion requires its acceptance gate, not merely a guide or design approval.

[Decisions](DECISIONS.md) preserves agreed rationale, including future product decisions. [Roadmap](ROADMAP.md) groups intended delivery. [Research](research/README.md) contains dated external investigations and experiments; findings need verification before implementing a changing provider/runtime capability.

## Historical material and traceability

[Archive](archive/README.md) retains completed designs, superseded partial-design snapshots and delivery/validation records. [Document inventory](DOCUMENT_INVENTORY.md) maps every relocated source to its current guide, active work and historical record. Partial snapshots are explicitly not completed features.

[pending_code_review_comments](pending_code_review_comments) remains the review queue; this documentation reorganization does not close findings. [Agent notes](agents) are working guidance, not a second source of current architecture.

## Documentation maintenance

When implementing a feature, update its module guide for verified behavior and keep the active design focused on the remaining difference. Update API/model/baseline/validators/generated contracts together where applicable. Record acceptance evidence in the active plan, then update backlog status. When acceptance is complete, archive the active feature design and link its outcome from the backlog to the current module guide.

Keep shared rules in platform guides, domain policy in the owning module and status/dependencies in the backlog. Link exact code/schema/test entry points instead of duplicating every field or full API schema. Preserve necessary rationale/history in the archive, and extract unfinished obligations before archiving a plan. An unverified design-versus-code discrepancy belongs in active work/review; it must not be described as current capability.

When an operator-facing route, action, setup command or capability changes, update the corresponding [manual chapter](../manual/README.md) and its [operation index](../manual/operation-index.md). Keep developer internals in these guides and operator task steps in the manual.

Use operator-facing feature names in current prose. For Information review, preserve internal `coverage` identifiers only when referring to code or contracts; follow the [terminology mapping](modules/operator.md#information-review-and-search).
