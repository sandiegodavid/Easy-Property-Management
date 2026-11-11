# Hosting deployment

**First release: [Pilot 0 / H06](../design/mvp/delivery-plan.md#pilot-0--capacity-qualified-free-operators).** Invited Free operators within qualified capacity, Admin-lite/manual supported operations, nightly verified backups and rehearsed restore, always-running containers and one announced maintenance window. No Stripe, idle-wake or independent update scheduling. Later-stage requirements below apply when those features are admitted; they are not all Pilot 0 gates. This is a release gate; the scoped infrastructure host runbooks below does not enable invitations.

The fresh target is specified in the
[Hosted MVP design](../design/mvp/architecture-and-access.md#architecture-and-trust-boundaries).
Use the [MVP acceptance register](../qualification/HOSTED_MVP_ACCEPTANCE.md) before
claiming deployment readiness. The
[GCP setup runbook](gcp-host-setup.md) and
[completed handoff](../qualification/reports/HOSTED_MVP_H02_9_HANDOFF.md) cover the
fresh closed infrastructure host and completed approved old-host reset. A complete
managed-auth/subscription/operator-admission installation workflow remains with its
owning slices; this host proof does not establish that workflow.

A fresh deployment must install pinned images and protected persistent resources,
qualify the host agent/quota boundary, establish exact subdomain routing and central
login, configure independent Admin authority, and verify operator plus control-plane
recovery before invitations. Configure billing/mail and record gross cost before
charging. The [design's sequence](../design/mvp/delivery-plan.md#suggested-delivery-and-acceptance-order)
is a delivery plan, not shell commands to run against a live VM.

## Infrastructure runbooks

Run commands from `application/` unless the runbook explicitly changes directory.
Tool source remains in `application/deploy/hosted-mvp/`; documentation lives here.

| Task | Runbook |
| --- | --- |
| Build separate images and install the offline agent | [Packaging and installation](packaging-and-installation.md) |
| Validate protected launch bindings and unavailable status | [Protected hosted launch](protected-launch.md) |
| Use Docker Desktop, retained Linux labs and reboot proofs | [Development and native qualification](linux-development-and-qualification.md) |
| Prepare the retained GCP filesystem/services and qualify the host | [GCP host setup and qualification](gcp-host-setup.md) |
| Inspect private runtime, guardian and network services | [Operations runbooks](../operations/README.md#infrastructure-runbooks) |

These procedures preserve closed ingress and explicit qualification scope. They do
not supply the later identity/admission/recovery workflow or authorize invitations.
Use the [foundation guides](../foundation/README.md) for architectural context and
measured limits rather than reading historical implementation steps.

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
