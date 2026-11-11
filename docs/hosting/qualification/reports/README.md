# Hosting qualification reports

Earlier-demo technical records apply only to their named historical topology.
H01 implementation reports record contract work, not fresh-target runtime acceptance.
Current H02 reports establish only their stated component/native/cloud scope.
Start with the [MVP acceptance register](../HOSTED_MVP_ACCEPTANCE.md) and
[current design](../../design/HOSTED_MVP_DESIGN.md). The
[older demo register](../HOSTED_DEMO_PUBLIC_ACCESS_PLAN.md) explains the historical
results only; no report is promoted to the new topology by this alignment.

| Report | What it establishes |
| --- | --- |
| [Linux quota](HOSTED_DEMO_LINUX_QUOTA_2026-10-23.md) | Unprivileged SQLite FULL, rollback and retained recovery space on a bounded image |
| [Systemd and uploads](HOSTED_DEMO_SYSTEMD_UPLOAD_2026-10-23.md) | Service sandbox, actual multipart admission, byte integrity and original-result reads |
| [R2 recovery and remount](HOSTED_DEMO_RECOVERY_2026-10-23.md) | Real encrypted off-host round-trip, complete retained-data/file comparison and a fresh bounded restore |
| [Installed release and boot](HOSTED_DEMO_INSTALLED_RELEASE_2026-10-23.md) | Combined artifact, service environment, exact mount and approved scratch boot checks |
| [Cost/latency planning basis](HOSTED_DEMO_COST_LATENCY_REVIEW_2026-10-23.txt) | Accepted optimization choices and measurement requirements; no live benchmark |

Each report identifies its fixture, release, result and limits. Raw before/after
observations remain under [evidence](../../evidence/); full original narrative is preserved
in the [planning/report archive](../../archive/planning-and-reports-2026-10-24/).

## Imported project-quota evidence

The unchanged HOSTED_ADMIN_8A_2026-11-01 before/after-reboot JSON reports are historical Admin_UI_Workflow evidence. See the [reuse guide](../HOSTED_PROJECT_QUOTA_REUSE.md) and [import manifest](../PROJECT_QUOTA_IMPORT_MANIFEST.json) for source-pin differences; they are not current Docker/GCP acceptance.

## Current H01 preparation evidence

[H01.5 specifications/report tooling](HOSTED_MVP_H01_5_PROOFS_2026-11-11.md) records
focused format/coverage tests and the owner handoff. Future H02–H05 proof reports use
the [v1 report contract](../specifications/REPORT_FORMAT.md), retain actual scope/pins/
failures and require owning review. Unrun/unavailable results are not passes; a valid
report is not release authorization. Existing historical reports remain unchanged.

[H01.6 UI/API contract fixtures](HOSTED_MVP_H01_6_UI_CONTRACTS_2026-11-11.md) record
synthetic state/default/action validation only; actual UI and deployed-browser
qualification remain H03/H04/H05 delivery gates.

## Consolidated H01 handoff

[H01.7 report](HOSTED_MVP_H01_7_HANDOFF_2026-11-11.md) and
[source/command validation manifest](HOSTED_MVP_H01_7_VALIDATION_2026-11-11.json)
record the complete local H01 contract preparation result, not a target qualification
report. H01 contract review acceptance is not asserted; all runtime/native/cloud/
provider/browser gates remain open for their named owners.

## Infrastructure evidence by topic

Read the [foundation guides](../../foundation/README.md) for current behavior and
operations. The records below preserve original dates, source/artifact pins, failures
and scope; their numbered filenames are provenance, not a reading sequence. Earlier
partial manifests remain historical and never inherit a newer acceptance result.

| Topic | Current guide | Original evidence records |
| --- | --- | --- |
| Packaging and launch | [Guide](../../foundation/packaging-and-launch.md) | [Build/install observations](HOSTED_MVP_H02_4_HANDOFF.md), [artifact pins](HOSTED_MVP_H02_4_VALIDATION.json), [protected launch/browser observations](HOSTED_MVP_H02_7_HANDOFF.md), [native installed candidates](HOSTED_MVP_H02_9_VALIDATION.json) |
| Inventory and commands | [Guide](../../foundation/inventory-and-host-commands.md) | [Input/decision baseline](HOSTED_MVP_H02_1_HANDOFF.md), [structural validation](HOSTED_MVP_H02_2_HANDOFF.md), [schema pins](HOSTED_MVP_H02_2_VALIDATION.json), [effect/transport observations](HOSTED_MVP_H02_3_HANDOFF.md), [effect pins](HOSTED_MVP_H02_3_VALIDATION.json) |
| Runtime and capacity | [Guide](../../foundation/runtime-and-capacity.md) | [Guarded runtime](HOSTED_MVP_H02_5_HANDOFF.md), [native result](HOSTED_MVP_H02_5_NATIVE.json), [measured workloads](HOSTED_MVP_H02_10_HANDOFF.md), [candidate budget](HOSTED_MVP_H02_10_CAPACITY_PROFILE.json), [measurements](HOSTED_MVP_H02_10_VALIDATION.json) |
| Networking and access | [Guide](../../foundation/networking-and-access.md) | [Network/secret observations](HOSTED_MVP_H02_6_HANDOFF.md), [network pins](HOSTED_MVP_H02_6_FINAL_VALIDATION.json), [exact GCP/IAM/stream evidence](HOSTED_MVP_H02_9_VALIDATION.json) |
| Development and host operations | [Guide](../../foundation/development-and-host-operations.md) | [Lab/reboot observations](HOSTED_MVP_H02_8_HANDOFF.md), [lab pins](HOSTED_MVP_H02_8_VALIDATION.json), [host setup/reboot/reset](HOSTED_MVP_H02_9_HANDOFF.md), [host pins/receipts](HOSTED_MVP_H02_9_VALIDATION.json) |
| Qualification and handoff | [Guide](../../foundation/qualification-and-handoff.md) | [Consolidated checks/limits](HOSTED_MVP_H02_11_HANDOFF.md), [commands/source/validation](HOSTED_MVP_H02_11_VALIDATION.json), [v1 native subset](HOSTED_MVP_H02_11_RUNTIME_SUBSET.json), [v1 final image/all-store unavailable report](HOSTED_MVP_H02_11_IMAGE_ALL_STORES.json) |

The final two proof reports validate in v1 format but retain overall `unavailable`:
whole-workflow/concurrent admission and final owning resources/assets are missing or
unrun. Scoped infrastructure delivery grants no qualified release or customer access.
Complete identity, admission/usage, UI, recovery and final artifact/Pilot 0 gates before
invitations. The [acceptance register](../HOSTED_MVP_ACCEPTANCE.md) owns those gates.
