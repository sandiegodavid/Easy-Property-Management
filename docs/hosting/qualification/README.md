# Hosting qualification

**First release: [Pilot 0 / H06](../design/mvp/delivery-plan.md#pilot-0--capacity-qualified-free-operators).** Invited Free operators within qualified capacity, Admin-lite/manual supported operations, nightly verified backups and rehearsed restore, always-running containers and one announced maintenance window. No Stripe, idle-wake or independent update scheduling. Later-stage requirements below apply when those features are admitted; they are not all Pilot 0 gates. No new executable deployment or passed proof is implied.

Start with the [fresh MVP acceptance register](HOSTED_MVP_ACCEPTANCE.md). The
[Hosted MVP design](../design/mvp/delivery-plan.md#suggested-delivery-and-acceptance-order)
owns the required validation matrix and staged delivery. Requirements are not passed
checks; record exact image/schema/host/provider configuration and limitations for each run.

The [older demo register](HOSTED_DEMO_PUBLIC_ACCESS_PLAN.md) is a historical checkpoint
for its named topology. It is not the current rollout checklist. Its
[supporting reports](reports/README.md) and [raw evidence](../evidence) retain their
original scope; do not promote their results into Docker, managed login, automatic
billing, new quota or unattended recovery acceptance without new proofs.

Mocked/component/native/deployed tests must remain distinguishable. New operational
records need explicit dates, artifact identities, outcomes and remaining limits;
provider reachability or a successful login does not establish complete readiness.

## Project-quota reuse input

[H02 project-quota reuse](HOSTED_PROJECT_QUOTA_REUSE.md) inventories the selected code/harness/tests and historical reboot reports imported from Admin_UI_Workflow. Three imported Python source pins differed from the historical 8A run; subsequent current-source native Docker/GCP evidence is linked in the H02 handoff below. This import does not activate runtime quotas or replace H02 design.

## H01.5 proof specifications and report tooling

The [six reproducible specifications](specifications/README.md) assign packaging,
runtime/limits, identity, usage, recovery and operations/economics to H02–H06. Their
67 required cases define inputs, negative controls, observations and retained failures.
The shared report validator and read-only CLI establish format/coverage only; all
native/cloud/provider/end-user gates remain unestablished. Executors are explicitly
unavailable. See the [report format](specifications/REPORT_FORMAT.md),
[packaging handoff](specifications/PACKAGING_HANDOFF.md) and
[H01.5 evidence](reports/HOSTED_MVP_H01_5_PROOFS_2026-11-11.md).

## H01.6 UI/API contract fixtures

[24 synthetic snapshots and delivery requirements](fixtures/README.md) freeze
Admin-lite and hosted Operator Settings/recovery behavior. The
[action map](fixtures/ACTION_MAP.md) pins owning ports/commands, authority and
confirmation; actual screens/browser acceptance remain H03–H05. See
[focused evidence](reports/HOSTED_MVP_H01_6_UI_CONTRACTS_2026-11-11.md). Fixtures
and preservation flags do not establish usable workflows or grant access.

## H01 consolidated preparation result

[H01.7 validation and handoff](reports/HOSTED_MVP_H01_7_HANDOFF_2026-11-11.md) records
the combined focused contract results and [tested inputs/commands](reports/HOSTED_MVP_H01_7_VALIDATION_2026-11-11.json).
H01.1–H01.7 preparation is delivered, ready for contract review. No target proof is
promoted: H02 needs its detailed design, and actual H02–H06 qualification/end-user
acceptance remains open. Current runtime and local installation are unchanged.

## Infrastructure qualification

Use the [topic-based foundation guides](../foundation/README.md), particularly
[qualification and handoff](../foundation/qualification-and-handoff.md), for delivered
scope and remaining gates. The [evidence index](reports/README.md#infrastructure-evidence-by-topic)
maps each topic to original dated reports, exact pins and retained failures.

The [acceptance register](HOSTED_MVP_ACCEPTANCE.md#h02-consolidated-infrastructure-acceptance)
distinguishes scoped infrastructure delivery from unavailable whole-runtime/final
image proofs. Identity, real admission/usage, UI, recovery and final release gates
still precede customer invitations. The qualification VM/disks are stopped and retained.
