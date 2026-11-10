# Hosting operations

**First release: [Pilot 0 / H06](../design/HOSTED_MVP_DESIGN.md#pilot-0--five-invited-free-operators).** Five invited Free operators, Admin-lite/manual supported operations, nightly verified backups and rehearsed restore, always-running containers and one announced maintenance window. No Stripe, idle-wake or independent update scheduling. Later-stage requirements below apply when those features are admitted; they are not all Pilot 0 gates. No new executable deployment or passed proof is implied.

Current operating requirements live in the
[Hosted MVP design](../design/HOSTED_MVP_DESIGN.md). Its automation and portal workflows
must be implemented and qualified before these can be treated as available controls.
The [MVP acceptance register](../qualification/HOSTED_MVP_ACCEPTANCE.md) owns fresh proof.

| Task | Current specification |
| --- | --- |
| Add/invite/claim operator | [Automatic onboarding](../design/HOSTED_MVP_DESIGN.md#5-admin-creation-and-automatic-onboarding); disabled until readiness and verified claim, no second routine approval |
| Plan, payment and usage changes | [Subscriptions/storage](../design/HOSTED_MVP_DESIGN.md#6-subscription-and-storage-workflows); confirmed payment is separate from Applied |
| Sleep/wake and multiple devices | [Runtime/session behavior](../design/HOSTED_MVP_DESIGN.md#7-idle-workspaces-sessions-and-multiple-devices) |
| Backup, restore, host loss and retirement | [Recovery](../design/HOSTED_MVP_DESIGN.md#8-backup-recovery-and-retirement); unattended keys and separate control-plane recovery |
| Independent operator updates | [Release upgrades](../design/HOSTED_MVP_DESIGN.md#9-independently-scheduled-release-upgrades); pinned image, activity/schedule, write draining and safe recovery |
| Alerts, support and cost/capacity | [Monitoring](../design/HOSTED_MVP_DESIGN.md#10-monitoring-reliability-and-cost-qualification) |

## Historical runbooks and records

[Ongoing Google runbook](GOOGLE_CLOUD_ONGOING_RUNBOOK.md),
[demo administrator runbook](HOSTED_DEMO_OPERATIONS.md) and
[demo operator guide](HOSTED_DEMO_OPERATOR_GUIDE.md) describe the older installed
process/volume/Access model. Do not use their A/B, manual passphrase, activation,
expiry or fixed quota instructions as fresh-MVP procedures. They are retained to
interpret named historical releases and incidents, not to imply those controls exist
in the new portal. [Cloudflare/VM record](CLOUDFLARE_OPERATIONS.md) retains dated results.

Actual MVP executable runbooks, operational ownership, external alert delivery and
restore rehearsal are launch gates. Monitoring healthy containers alone cannot
prove subscription enforcement, off-host recoverability or correct identity isolation.
