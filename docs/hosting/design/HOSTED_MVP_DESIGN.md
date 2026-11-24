# Hosted MVP Design (`HOSTED-001`)

**Status:** Pilot 0 (`H01–H06`) **LIVE / GO** (2026-11-24). Slices `H07–H12` remain planned and are gated on the 4-week Pilot 0 repeat-use evaluation.

This is the master navigation index for the accepted `HOSTED-001` specification under [`mvp/`](mvp/delivery-plan.md). Together these focused guides define the long-term product and architecture requirements for `H01–H12`.

- For the **delivered Pilot 0 architecture and accepted decisions (`H01–H06`)**, see [../ARCHITECTURE.md](../ARCHITECTURE.md).
- For **live operational procedures and host constants**, see [../operations/README.md](../operations/README.md).
- For **qualification status and live Pilot 0 evidence**, see [../qualification/HOSTED_MVP_ACCEPTANCE.md](../qualification/HOSTED_MVP_ACCEPTANCE.md).

## Specification Guides

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
| Schema ownership and acceptance contract | [implementation-contracts.md](mvp/implementation-contracts.md) |
| Hosted MVP validation matrix | [validation.md](mvp/validation.md) |

## Related References

- [Database schema catalog](../../database/overview.md): owning stores and complete executable DDL dictionaries.
- [Feature backlog](../../FEATURE_BACKLOG.md): feature scope and priority.
- [Pilot 0 Exit Review](../qualification/reports/HOSTED_MVP_H06_10_EXIT_REVIEW.md) & [Cost & Ops Worksheet](../qualification/reports/PILOT_0_COST_AND_OPS_WORKSHEET.md).

<details>
<summary>Direct section lookup (preserves existing deep links)</summary>

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
- <a id="schema-ownership-and-acceptance-contract"></a>[Schema ownership and acceptance contract](mvp/implementation-contracts.md#schema-ownership-and-acceptance-contract)
- <a id="required-validation-matrix"></a>[Required validation matrix](mvp/validation.md#required-validation-matrix)

</details>
