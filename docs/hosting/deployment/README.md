# Hosting deployment

**First release: [Pilot 0 / H06](../design/mvp/delivery-plan.md#pilot-0--capacity-qualified-free-operators).** Invited Free operators within qualified capacity, Admin-lite/manual supported operations, nightly verified backups and rehearsed restore, always-running containers and one announced maintenance window. No Stripe, idle-wake or independent update scheduling. Later-stage requirements below apply when those features are admitted; they are not all Pilot 0 gates. No new executable deployment or passed proof is implied.

The fresh target is specified in the
[Hosted MVP design](../design/mvp/architecture-and-access.md#architecture-and-trust-boundaries).
Use the [MVP acceptance register](../qualification/HOSTED_MVP_ACCEPTANCE.md) before
claiming deployment readiness. A current executable Docker/managed-auth/subscription
installation runbook has **not** been delivered by this documentation task.

A fresh deployment must install pinned images and protected persistent resources,
qualify the host agent/quota boundary, establish exact subdomain routing and central
login, configure independent Admin authority, and verify operator plus control-plane
recovery before invitations. Configure billing/mail and record gross cost before
charging. The [design's sequence](../design/mvp/delivery-plan.md#suggested-delivery-and-acceptance-order)
is a delivery plan, not shell commands to run against a live VM.

## Earlier release-specific references

- [Google demo deployment](GOOGLE_CLOUD_DEMO_DEPLOYMENT.md): older fixed A/B processes,
  loop volumes and Cloudflare Access enrollment. Not the new Docker deployment guide.
- [Demo configuration contract](HOSTED_DEMO_CONFIGURATION.md): old release JSON/routes,
  manual CLI and session assumptions. New configuration/contracts must be implemented
  and validated rather than copied blindly.
- [Recorded deployment](../operations/CLOUDFLARE_OPERATIONS.md): dated actual inventory,
  not current host discovery or authority to reuse its resources.

Retain historical procedures for diagnosis of their named release only. No provider
move, VM operation, schema change or migration is performed by this alignment.
