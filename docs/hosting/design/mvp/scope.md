# Scope and development

[Hosted MVP design index](../HOSTED_MVP_DESIGN.md) · [Schema catalog](../../../DATABASE_SCHEMA.md)

Part of the accepted HOSTED-001 design. Requirements here do not establish implementation, deployment or qualification; Pilot 0 exceptions are in the [delivery plan](delivery-plan.md).

In this guide: [Purpose and scope](#purpose-and-scope) · [Relationship to the repository](#relationship-to-the-repository) · [Included and deferred capabilities](#included-and-deferred-capabilities) · [Development and production deployment boundary](#development-and-production-deployment-boundary) · [Local development and Linux qualification environments](#local-development-and-linux-qualification-environments)

## Purpose and scope

<a id="1-purpose-and-scope"></a>

Give independent property managers an ordinary browser application, administered
through an Admin portal, with isolated workspaces and automated provisioning,
subscriptions, backups and release management. Start with a few operators and grow
toward 100 as demand and measured capacity justify it. Do not provision for 100 on
day one. Target US customers/properties under the existing product scope; no additional
storage/backup residency requirement was introduced in this discussion.

One verified operator identity owns one workspace and one subscription. Their
multiple devices have the same full business permissions. No shared logins, staff
roles, multiple-workspace switching or shared-portfolio collaboration in this MVP.
Full permission remains subject to authentication, account state, maintenance,
record revisions and storage admission; it never grants host administration.

### Relationship to the repository

The [product brief](../../../PRODUCT_BRIEF.md), [application architecture](../../../ARCHITECTURE.md),
[current UI guide](../../../ui/operator-experience.md) and [backlog](../../../FEATURE_BACKLOG.md)
provide business/application context. Existing demo documents retain their original
scope and evidence; they are not silently rewritten by this proposal. In particular,
the older two-operator, fixed-volume, manual onboarding/recovery and Cloudflare Access
customer-login design is not the target for this fresh commercial offering.

The current `hosted_mvp` checkout contains the local modular monolith, hosted-access
foundations and older deployment tooling. It does not already provide this Docker
control plane, automated subscription lifecycle or complete unattended recovery.
The prior conversation's implementation claims on other branches are not evidence
that those changes exist here. Use only current schemas for initial deployment;
future upgrades of actual customer workspaces still require safe schema evolution.

### Included and deferred capabilities

| Included in this hosting design | Outside this task |
| --- | --- |
| Admin portal, managed identity, invitations and automated provisioning | New property-management business workflows |
| Operator subscription UI/billing, storage metering/enforcement | Import implementation, including Universal Reader |
| Automated backup, recovery tooling, usage/health monitoring | Tenant/owner portals and property-payment implementation |
| Independently scheduled operator upgrades and controlled recovery | Local/cloud synchronization and offline hosted writes |
| Multi-device access to one operator workspace | Teams, enterprise SSO, customer-managed encryption keys and zero-knowledge encryption |

Imports will be supported on **all tiers** when delivered through their functional
backlog. Do not advertise unimplemented imports as available. Tenant access/payments
are intended future paid benefits, but are deferred and cannot be sold as currently
available. Initially, paid plans must stand on storage and stronger recovery alone.

Preserve the shared business core for optional free, single-operator local use.
Local launch has no hosted login or subscription enforcement. Hosting-specific
identity, control-plane and billing services are separate compositions. Do not add
synchronization or require a cloud account to perform local manual workflows.

Delivery begins with [Pilot 0](delivery-plan.md#pilot-0--capacity-qualified-free-operators), before paid
plans and broader automation. Its explicit operating rules override the later billing,
update-scheduling and idle-wake defaults for that stage only. The remaining sections
define the subsequent hosted MVP target, not prerequisites to build every automation
before learning from the pilot.

### Development and production deployment boundary

| Portal | Local development | Production hosted | Production local installation |
| --- | --- | --- | --- |
| Admin | Supported | Supported | Not supported |
| Operator | Supported | Supported | Supported, single operator |
| Tenant | Supported | Supported after PORTAL-001 qualification | Not supported |
| Owner | Supported | Supported after PORTAL-002 qualification | Not supported |

Local development of Admin/Tenant/Owner is for building and testing their hosted
workflows, not a customer-facing local deployment option. Retain separate actors,
stores and authorization boundaries in the development composition. Use isolated
synthetic workspaces, local test origins and explicit development configuration;
any test identity/provider/mail/payment adapters must be development-only, with
no production credentials, real payment dispatch or connection to production stores.
The production local composition serves only the Operator portal and its supported
local workflows; it must not register Admin/Tenant/Owner APIs or grant their roles.
This restriction concerns portal-specific actors/endpoints; local Operator property,
tenant and owner management workflows remain available.
Hosted deployment serves the respective portals under their existing origin/identity
boundaries; development does not weaken production login, MFA or grants.

H02/H03 and each portal's detailed design must specify local launch/configuration,
test-origin and fixture contracts plus production rejection tests. This development
support does not add production tenant/owner portals to Pilot 0 or make unqualified
payment features available locally.

### Local development and Linux qualification environments

Use Docker Desktop on the Mac for routine hosted-container development and browser/API
integration testing. Existing native Python/Vite local-Operator development remains
supported. Container build/launch configuration still requires H02's detailed design;
this environment choice does not imply those workflows are already implemented.

Retain the separate Lima ARM64 `epm-quota-test` VM as the isolated native Linux
qualification lab for filesystem quotas, privileged host-agent boundaries, sandbox
escape tests and actual reboot persistence. Keep it stopped when unused. No extra VM
is needed for ordinary portal work, and Docker Desktop tests do not replace native
quota or exact Google-host qualification. See the [quota reuse guide](../../qualification/HOSTED_PROJECT_QUOTA_REUSE.md#development-versus-native-qualification).

Preserve upstream evidence/source pins and existing lab trees. Before installing
Docker, changing the kernel/filesystem/tooling or otherwise altering the retained lab,
retain a recoverable baseline and record a new environment/source identity; rerun the
applicable native tests. H02 must specify any such changes before implementation.
Use synthetic data and isolated source snapshots; do not share production workspaces,
cloud credentials or Mac virtual environments with the qualification guest.

