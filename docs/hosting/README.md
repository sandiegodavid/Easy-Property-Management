# Hosting documentation

Updated November 10, 2026. Start with the confirmed fresh hosted-MVP direction.
Documentation describes requirements and evidence separately; it does not establish
implementation or permission to deploy, charge or admit real customer data.

## Current direction

- [Hosted MVP design](design/HOSTED_MVP_DESIGN.md): accepted architecture, product
  plans, Admin/operator workflows, identity/subdomains, subscriptions, recovery,
  independent updates, budgets and validation gates.
- [Hosting Plan](Hosting_Plan.md): concise overview and product/delivery boundaries.
- [MVP acceptance register](qualification/HOSTED_MVP_ACCEPTANCE.md): current target's
  implementation and release-proof gates. No completed MVP qualification is inferred
  from the previous demo.

Initial platform: Google Compute Engine/Docker/persistent SQLite and files,
Cloudflare edge/Tunnel/R2, managed identity and Stripe subscriptions. Admin chooses
operator count within qualified capacity; Empty workspace is the default. Imports
are deferred but available to all tiers when implemented; tenant/owner portals follow hosting in the immediate backlog.
Launch and 100-operator gross budget targets are $250 and $300/month before credits.

## Implement first

Start [HOSTED-001 H01](design/HOSTED_MVP_DESIGN.md#implementation-slices). Pilot 0 releases at H06 to five invited Free operators: Admin-lite, verified nightly off-host backups/rehearsed restore, warm runtimes, one maintenance window and recorded manual operating cost. No Stripe, idle-wake or per-operator scheduling. H07–H12 deliver the subsequent full platform described above. [PORTAL-001/002](../active/PORTALS_IMPLEMENTATION_PLAN.md) follow it, with shared FIN-009 and PAY-001/002 sources.

## Find the right document

| Area | Use |
| --- | --- |
| [Design index](design/README.md) | Current MVP specification and clearly superseded demo designs |
| [Deployment index](deployment/README.md) | Fresh-target prerequisites versus older release-specific procedures |
| [Operations index](operations/README.md) | Current intended workflows and limitations of older executable runbooks |
| [Qualification index](qualification/README.md) | New acceptance gates versus dated reports/raw evidence |
| [SQLite upgrade research](research/SQLITE_SCHEMA_UPGRADE_WORKFLOW_2026-10-31.md) | Technical research to evaluate under current release/recovery rules; not independently adopted |
| [Archive](archive/README.md) | Preserved original plans and historical exports |

## Historical deployment and evidence

The October A/B process/Unix-user/loop-image installation, Cloudflare Access
customer login, manual backups and invitation/expiry procedures describe a different
release/topology. Their counts, prices, paths, quotas and test outcomes are historical,
not current operator limits or deployable MVP instructions. Inspect an actual host
before drawing conclusions about its present state; old prose is not live inventory.

[Deployment record](operations/CLOUDFLARE_OPERATIONS.md),
[demo checkpoint](qualification/HOSTED_DEMO_PUBLIC_ACCESS_PLAN.md),
[supporting reports](qualification/reports/README.md) and [raw evidence](evidence/)
remain available with their original tested scope. Do not silently relabel evidence
or alter historical fixtures to make them match the new design.

Maintain the MVP design for accepted requirements, the acceptance register for new
proof and limitations, and dated records for actual deployment results. Preserve
sensitive configuration/credentials outside documentation. Backlog changes require
separate authorization; this alignment changes documentation only.
