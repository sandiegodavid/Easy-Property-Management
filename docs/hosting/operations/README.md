# Hosting operations

**First release: [Pilot 0 / H06](../design/mvp/delivery-plan.md#pilot-0--capacity-qualified-free-operators).** Invited Free operators within qualified capacity, Admin-lite/manual supported operations, nightly verified backups and rehearsed restore, always-running containers and one announced maintenance window. No Stripe, idle-wake or independent update scheduling. Later-stage requirements below apply when those features are admitted; they are not all Pilot 0 gates. No new executable deployment or passed proof is implied.

Current operating requirements live in the
[Hosted MVP design](../design/HOSTED_MVP_DESIGN.md). Its automation and portal workflows
must be implemented and qualified before these can be treated as available controls.
The [MVP acceptance register](../qualification/HOSTED_MVP_ACCEPTANCE.md) owns fresh proof.

| Task | Current specification |
| --- | --- |
| Add/invite/claim operator | [Automatic onboarding](../design/mvp/onboarding.md#admin-creation-and-automatic-onboarding); disabled until readiness and verified claim, no second routine approval |
| Plan, payment and usage changes | [Subscriptions/storage](../design/mvp/subscriptions-storage-and-runtime.md#subscription-and-storage-workflows); confirmed payment is separate from Applied |
| Sleep/wake and multiple devices | [Runtime/session behavior](../design/mvp/subscriptions-storage-and-runtime.md#idle-workspaces-sessions-and-multiple-devices) |
| Backup, operator-authorized restore, host loss and retirement | [Recovery](../design/mvp/recovery.md#backup-recovery-and-retirement); unattended keys and separate control-plane recovery |
| Independent operator updates | [Release upgrades](../design/mvp/releases.md#independently-scheduled-release-upgrades); pinned image, activity/schedule, write draining and safe recovery |
| Alerts, support and cost/capacity | [Monitoring](../design/mvp/operations-and-sources.md#monitoring-reliability-and-cost-qualification) |

## Infrastructure runbooks

| Task | Runbook |
| --- | --- |
| Understand private trees, writer exclusion and guarded containment | [Runtime supervision](runtime-supervision.md) |
| Configure, inspect and qualify gateway/egress/Tunnel services | [Network and host services](network-and-host-services.md) |
| Build, install or prepare the GCP/Linux environment | [Deployment runbooks](../deployment/README.md#infrastructure-runbooks) |

Tool source remains under `application/deploy/hosted-mvp/`; execute the documented
commands from the stated working directory. These are scoped infrastructure
procedures, not permission to enroll operators or enable later recovery/billing
workflows. The [foundation guides](../foundation/README.md) and acceptance register
separate delivered behavior from those remaining gates.

## Historical runbooks and records

[Ongoing Google runbook](GOOGLE_CLOUD_ONGOING_RUNBOOK.md),
[demo administrator runbook](HOSTED_DEMO_OPERATIONS.md) and
[demo operator guide](HOSTED_DEMO_OPERATOR_GUIDE.md) describe the older installed
process/volume/Access model. Do not use their A/B, manual passphrase, activation,
expiry or fixed quota instructions as fresh-MVP procedures. They are retained to
interpret named historical releases and incidents, not to imply those controls exist
in the new portal. [Cloudflare/VM record](CLOUDFLARE_OPERATIONS.md) retains dated results.

These scoped infrastructure runbooks do not close the remaining operational ownership,
external alert-delivery and restore-rehearsal launch gates. Monitoring healthy containers alone cannot
prove subscription enforcement, off-host recoverability or correct identity isolation.

Workspace recovery is selected/authorized by the operator, not approved by Admin. Pilot 0 may require manual technical execution of that exact request; platform/control recovery remains Admin-owned. Safety checks, scoped status and payment reconciliation still apply.
