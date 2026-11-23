# Hosting operations

Operational runbooks for the **HOSTED-001** infrastructure, managed identity, and Admin
recovery. Tool source lives under `application/deploy/hosted-mvp/`.

## Runbooks

| Task | Runbook |
| --- | --- |
| Private workspace/control/scratch trees, writer exclusion, and guarded containment | [Runtime supervision](runtime-supervision.md) |
| Gateway, central egress proxy, Cloudflare Tunnel, and host services | [Network and host services](network-and-host-services.md) |
| Managed identity qualification, native/GCP checks, outage tests, and configuration sealing | [Managed identity operations and qualification](identity-qualification-and-operations.md) |
| Recover an Admin principal or TOTP factor offline | [Admin account recovery](admin-account-recovery.md) |
| Build, install, or prepare the GCP/Linux host | [Deployment runbooks](../deployment/README.md) |

## Target Operating Specifications (`design/mvp/`)

| Area | Specification |
| --- | --- |
| Add / provision / invite / claim operator | [Onboarding](../design/mvp/onboarding.md) · [H04 Admin-lite design](../design/HOSTED_MVP_H04_DESIGN.md) |
| Plans, Free 50 MB storage, and future paid subscriptions | [Subscriptions, storage, and runtime](../design/mvp/subscriptions-storage-and-runtime.md) |
| Nightly off-host backups, operator-authorized restore, and host-loss recovery (H05) | [Recovery](../design/mvp/recovery.md) |
| Independent component release upgrades (H10) | [Releases](../design/mvp/releases.md) |
| Monitoring, alerts, support, and cost/capacity tracking | [Operations and sources](../design/mvp/operations-and-sources.md) |

> Workspace restore is operator-authorized, not Admin-approved. Backup protection and
> positive business ingress remain closed until H05 completes.
