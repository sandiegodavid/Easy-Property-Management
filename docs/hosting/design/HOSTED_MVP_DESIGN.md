# Hosted MVP design

Accepted direction consolidated November 10, 2026.

**Status: design only.** This document records the confirmed fresh hosted-MVP
proposal. It does not implement features, authorize deployment or real charges,
mark backlog items delivered. [HOSTED-001](../../FEATURE_BACKLOG.md#now--hosted-mvp-then-tenant-and-owner-portals) now schedules implementation; this document does not authorize deployment or live charges by itself. Prices, allowances
and capacity/recovery targets below require the stated measurement and launch gates.

## Start here

This is the entry point for the accepted HOSTED-001 design. Detailed requirements live in the focused documents below; together they form one design, not alternative proposals. Scope and backlog order are unchanged.

For a first read: **scope → architecture and access → delivery plan**. For implementation, follow the [H01 detailed design](HOSTED_MVP_H01_DESIGN.md), then complete each later slice’s detailed design before coding.

| Topic | Document |
| --- | --- |
| Scope and development | [scope.md](mvp/scope.md) |
| Plans, budgets and demand gates | [plans-and-budgets.md](mvp/plans-and-budgets.md) |
| Architecture, identity and access enforcement | [architecture-and-access.md](mvp/architecture-and-access.md) |
| Operator provisioning and onboarding | [onboarding.md](mvp/onboarding.md) |
| Subscriptions, storage and runtime behavior | [subscriptions-storage-and-runtime.md](mvp/subscriptions-storage-and-runtime.md) |
| Per-tier physical storage sizing acceptance | [Measured peaks, margins and exhaustion checks](mvp/subscriptions-storage-and-runtime.md#per-tier-physical-storage-sizing-acceptance) |
| Backup, recovery and retirement | [recovery.md](mvp/recovery.md) |
| Independent releases and operator update experience | [releases.md](mvp/releases.md) |
| Monitoring, operations and source references | [operations-and-sources.md](mvp/operations-and-sources.md) |
| Delivery plan and Pilot 0 | [delivery-plan.md](mvp/delivery-plan.md) |
| H02 quota reuse and schema implementation contracts | [implementation-contracts.md](mvp/implementation-contracts.md) |
| Hosted MVP validation matrix | [validation.md](mvp/validation.md) |

## Related references

- [Database schema catalog](../../database/README.md): owning stores and complete table/column definitions.
- [H01 detailed design and implementation plan](HOSTED_MVP_H01_DESIGN.md).
- [Infrastructure design](HOSTED_MVP_H02_DESIGN.md) and [topic-based foundation guides](../foundation/README.md): delivered scoped container/storage/gateway behavior, operating procedures, exact evidence and remaining release gates.
- [Acceptance register](../qualification/HOSTED_MVP_ACCEPTANCE.md): actual proof status, separate from design requirements.
- [Feature backlog](../../FEATURE_BACKLOG.md): feature scope and priority.

Maintain each requirement in its focused owning document; keep this page as navigation. Historical section links below lead to their current location.

<details>
<summary>Direct section lookup (also preserves previous deep links)</summary>

- <a id="1-purpose-and-scope"></a>[Purpose and scope](mvp/scope.md#purpose-and-scope)

- <a id="relationship-to-the-repository"></a>[Relationship to the repository](mvp/scope.md#relationship-to-the-repository)

- <a id="included-and-deferred-capabilities"></a>[Included and deferred capabilities](mvp/scope.md#included-and-deferred-capabilities)

- <a id="development-and-production-deployment-boundary"></a>[Development and production deployment boundary](mvp/scope.md#development-and-production-deployment-boundary)

- <a id="local-development-and-linux-qualification-environments"></a>[Local development and Linux qualification environments](mvp/scope.md#local-development-and-linux-qualification-environments)

- <a id="2-plans-and-financial-envelope"></a>[Plans and financial envelope](mvp/plans-and-budgets.md#plans-and-financial-envelope)

- <a id="provisional-product-catalog"></a>[Provisional product catalog](mvp/plans-and-budgets.md#provisional-product-catalog)

- <a id="operating-budgets-and-demand-validation"></a>[Operating budgets and demand validation](mvp/plans-and-budgets.md#operating-budgets-and-demand-validation)

- <a id="3-architecture-and-trust-boundaries"></a>[Architecture and trust boundaries](mvp/architecture-and-access.md#architecture-and-trust-boundaries)

- <a id="initial-deployment-and-growth"></a>[Initial deployment and growth](mvp/architecture-and-access.md#initial-deployment-and-growth)

- <a id="public-subdomains-and-authentication"></a>[Public subdomains and authentication](mvp/architecture-and-access.md#public-subdomains-and-authentication)

- <a id="4-state-ownership-and-dependable-automation"></a>[State ownership and dependable automation](mvp/architecture-and-access.md#state-ownership-and-dependable-automation)

- <a id="access-intent-local-enforcement-and-external-containment"></a>[Access intent, local enforcement and external containment](mvp/architecture-and-access.md#access-intent-local-enforcement-and-external-containment)

- <a id="5-admin-creation-and-automatic-onboarding"></a>[Admin creation and automatic onboarding](mvp/onboarding.md#admin-creation-and-automatic-onboarding)

- <a id="6-subscription-and-storage-workflows"></a>[Subscription and storage workflows](mvp/subscriptions-storage-and-runtime.md#subscription-and-storage-workflows)

- <a id="upgrades-downgrades-and-payment-failures"></a>[Upgrades, downgrades and payment failures](mvp/subscriptions-storage-and-runtime.md#upgrades-downgrades-and-payment-failures)

- <a id="what-storage-means-and-how-it-is-enforced"></a>[What storage means and how it is enforced](mvp/subscriptions-storage-and-runtime.md#what-storage-means-and-how-it-is-enforced)

- <a id="operator-account-ui"></a>[Operator account UI](mvp/subscriptions-storage-and-runtime.md#operator-account-ui)

- <a id="7-idle-workspaces-sessions-and-multiple-devices"></a>[Idle workspaces, sessions and multiple devices](mvp/subscriptions-storage-and-runtime.md#idle-workspaces-sessions-and-multiple-devices)

- <a id="8-backup-recovery-and-retirement"></a>[Backup, recovery and retirement](mvp/recovery.md#backup-recovery-and-retirement)

- <a id="internal-workspace-backup-and-recovery"></a>[Internal workspace backup and recovery](mvp/recovery.md#internal-workspace-backup-and-recovery)

- <a id="authenticated-recovery-mode-and-failure-handling"></a>[Authenticated recovery mode and failure handling](mvp/recovery.md#authenticated-recovery-mode-and-failure-handling)

- <a id="clean-runtime-rebuild-then-authenticated-restore"></a>[Clean runtime rebuild, then authenticated restore](mvp/recovery.md#clean-runtime-rebuild-then-authenticated-restore)

- <a id="recovery-security-release-gate"></a>[Recovery security release gate](mvp/recovery.md#recovery-security-release-gate)

- <a id="separate-admin-backup-and-recovery-store"></a>[Separate Admin backup and recovery store](mvp/recovery.md#separate-admin-backup-and-recovery-store)

- <a id="9-independently-scheduled-release-upgrades"></a>[Independently scheduled release upgrades](mvp/releases.md#independently-scheduled-release-upgrades)

- <a id="10-monitoring-reliability-and-cost-qualification"></a>[Monitoring, reliability and cost qualification](mvp/operations-and-sources.md#monitoring-reliability-and-cost-qualification)

- <a id="12-primary-source-constraints-used-in-this-design"></a>[Primary-source constraints used in this design](mvp/operations-and-sources.md#primary-source-constraints-used-in-this-design)

- <a id="11-suggested-delivery-and-acceptance-order"></a>[Suggested delivery and acceptance order](mvp/delivery-plan.md#suggested-delivery-and-acceptance-order)

- <a id="pilot-0--capacity-qualified-free-operators"></a>[Pilot 0 — capacity-qualified Free operators](mvp/delivery-plan.md#pilot-0--capacity-qualified-free-operators)

- <a id="implementation-slices"></a>[Implementation slices](mvp/delivery-plan.md#implementation-slices)

- <a id="h02-project-quota-reuse-contract"></a>[H02 project-quota reuse contract](mvp/implementation-contracts.md#h02-project-quota-reuse-contract)

- <a id="schema-ownership-and-acceptance-contract"></a>[Schema ownership and acceptance contract](mvp/implementation-contracts.md#schema-ownership-and-acceptance-contract)

- <a id="required-validation-matrix"></a>[Required validation matrix](mvp/validation.md#required-validation-matrix)

</details>
