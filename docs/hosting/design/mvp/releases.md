# Independent releases and operator update experience

[Hosted MVP design index](../HOSTED_MVP_DESIGN.md) · [Schema catalog](../../../DATABASE_SCHEMA.md)

Part of the accepted HOSTED-001 design. Requirements here do not establish implementation, deployment or qualification; Pilot 0 exceptions are in the [delivery plan](delivery-plan.md).

## Independently scheduled release upgrades

<a id="9-independently-scheduled-release-upgrades"></a>

Admin, Operator, Tenant and Owner have independently versioned, qualified release
artifacts and rollout operations. Upgrading one portal does not automatically upgrade
the others. Admin approves a target component release; Operator deployment remains
independent per operator workspace, while Admin and the initial Tenant/Owner portal
assets have deployment-wide assignments. Tenant/Owner release delivery is future
portal work, not Pilot 0 scope. Each artifact declares its API, source/runtime,
authentication and owned/readable schema compatibility in a pinned manifest.
All release assignments use the common component_deployments table described in the
[schema master](../../../DATABASE_SCHEMA.md); scope distinguishes per-workspace Operator
rows from deployment-wide Admin/Tenant/Owner rows. Operator identity records do not
carry a duplicate desired release.

Retain the shared modular business backend and one writer per workspace. Independent
portal releases do not require another writer, database copy or four microservices.
Tenant/Owner assets may be deployed independently through their qualified serving
boundary and call authorized source APIs; new server capabilities are delivered by
the owning runtime release. Test each portal against every admitted backend version
it may route to. Use compatible API evolution so component versions can coexist;
reject an unsupported pairing rather than force a silent all-portal update.

A schema change belongs to the store owner, not to a frontend artifact. Admin upgrades
may change only their owning control schemas through the qualified runner; Operator
runtime upgrades own business/access changes. Portal asset-only upgrades neither run
schema DDL nor restore databases. A genuinely incompatible shared dependency needs an
explicit reviewed prerequisite/maintenance plan and compatibility evidence; independent
release selection is not a promise of arbitrary version mixing or zero downtime.

### Operator-visible release projection

Admin owns reads and mutations of `component_deployments` through its application
boundary. Admin commands request assignments; trusted deployment tooling supplies
verified observations through that boundary. The Operator service never opens the
Admin database, and neither portal exposes a raw deployment row or direct row editor.

The status flow is **Admin-owned private control API → Operator backend → Operator
status API → browser**. Authenticate the private caller and scope its observation to
the registered deployment/operator/workspace binding, not a browser-selected target.
Return an allowlisted view such as verified current version, pending update status,
announced maintenance window and observation freshness. Exclude internal receipts,
resource references, fences and diagnostic details. Unknown running versions remain
unknown; a desired assignment is not evidence of a completed upgrade.

Refresh asynchronously with bounded caching and retry/backoff, without an Admin
round trip on each page read or business command. If the control API is unavailable,
retain last-known information with its freshness or show **Update status unavailable**.
Release-status reporting failure alone must not stop ordinary authorized operator
work. Existing access, compatibility and maintenance enforcement still applies:
a stale display projection cannot authorize an upgrade, grant access or remove a
maintenance gate. Exact private transport, projection payload, cache lifetime and
refresh limits require design in the owning delivery slices before implementation.

Acceptance must cover own-workspace scoping, cross-workspace denial, safe field
filtering, stale/unknown observations and control-service outage without blocking
otherwise eligible business work. A displayed status or cached successful observation
must not bypass a later disable, incompatible release or active maintenance gate.

### Operator scheduling boundary — detailed design deferred to H10

The scheduling behavior below is an H10 product/architecture requirement, not a
completed scheduling implementation design. Defer preference/request schemas, API
commands, scheduling algorithms and detailed interactions to H10. Pilot 0 retains
one announced shared maintenance window and no operator scheduling controls.

Keep this extension separate from release assignment: future operator preferences
and scheduling requests have their own owning records and authorized commands.
Choosing a time does not directly edit `component_deployments`, select an arbitrary
release or mark a deployment applied. H10 can reference the existing scoped assignment,
revision and original operation identity without a duplicate release authority.
No speculative scheduling columns or placeholder preference records are needed now.

The following scheduling workflow applies to Operator releases. Admin/portal component
rollouts use their own canary, notices and bounded operation, without automatically
changing operator update preferences or stopping unrelated workspace writers.
Start with an internal canary and bounded batches; failures stop that component
rollout. No arbitrary published-tag auto-updates. Operators may run different eligible
versions temporarily; pin image/schema compatibility and retain needed rollback artifacts.

Operator Settings stores a preferred update window and explicit time zone. Suggest a
low-activity time; offer **Accept suggested time**, **Choose another time** and **Update
now** when scheduling is needed. Avoid prompting on every small release. Notify in
advance and support bounded deferral, initially up to seven days. Disclose an urgent
security exception; it does not permit unsafe interruption of a committed operation.

Prefer no human activity across devices for approximately 15 minutes, with no in-flight
owned work. Before interruption warn active/returning users, drain admitted commands,
resolve uncertain outcomes and preserve acknowledged unfinished forms. At a chosen time,
activity may require a visible deferral/finishing-work step; do not drop an active write.

The owning job establishes a verified pre-upgrade recovery point, fences/stops the sole
writer, applies required schema changes and starts the pinned image. Verify runtime,
source binding, data integrity and required smoke checks before reopening. Only that
job may remove its gate; a later disable always wins. Existing sessions may remain only
when still eligible; reload incompatible UI/assets safely without replaying old commands.
A returning operator sees Updating and a clear continuation path.

Operator-facing release status should be unobtrusive and match the interruption:

- Before maintenance, show a small notice with the window and expected interruption.
  Pilot 0 uses its announced shared window; individual scheduling belongs to H10.
- During interruption, show **Updating your workspace** and retain unfinished input.
  Explain that saved records are retained, but never imply unsaved input has been
  saved unless draft persistence was acknowledged. Block new submissions once the
  maintenance gate is active; source-side fencing remains authoritative across devices.
- After verified readiness, automatically reconnect using bounded retry/backoff and
  refresh reads only while current access/session authority remains valid. A revoked
  or expired session requires sign-in; a later Admin disable must not be bypassed.
  Resolve uncertain submissions through their original operation identity, never by
  automatically replaying them.
- If frontend assets changed, offer **Update ready — reload** after preserving the
  current draft. Do not force a reload that loses input. If the old UI is incompatible,
  prevent further commands and guide the operator through draft preservation and
  reload before editing resumes. Revalidate a restored draft against current records
  and form contracts; never silently submit it.
- If the update cannot complete, show a clear workspace-availability message, last
  known status and support option. Do not show success or an endless updating spinner
  when the outcome is failed or unknown. Keep technical progress, diagnostic details
  and rollback controls in Admin; expose only safe status to the operator.
- An inactive operator returning after a successful update can use the updated app
  without a blocking completion announcement. Offer concise release notes when a
  change affects their workflow; do not require acknowledgment for every release.

Automatic restore to the pre-upgrade point is allowed only while access remains fenced
and no operator writes were accepted afterward. Once business writes resume, preserve
them and require a controlled forward fix or reviewed recovery; blindly restoring an
older DB would erase legitimate work. Merely running the old image is not a schema-safe
rollback. An idle Free container can receive a new image assignment without starting
solely for rollout, but required schema validation must occur before serving it again.

Pilot 0 still uses one announced maintenance window and supported manual operations.
Its Admin and Operator artifacts/assignments are separate from H02, even if deployed
together in that window. H10 adds independent scheduling/automation; Tenant/Owner
backlogs supply their independently deployable artifacts when implemented. For a
component-only rollout, restore its prior compatible artifact without rolling back
shared business data. Runtime/schema recovery retains the existing pre-write rollback
and post-reopen data-preservation rules.

