# Hosting qualification reports

The historical technical records below apply only to their earlier demo topology.
H01 implementation reports record contract work, not fresh-target runtime acceptance.
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
