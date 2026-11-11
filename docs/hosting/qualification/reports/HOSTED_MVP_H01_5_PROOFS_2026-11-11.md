# H01.5 — Proof specifications, reports and packaging handoff

Delivered November 11, 2026 on `hosted_mvp`, starting from clean commit
`4f2c1e6014566dffb80a397f5081be54059c9fbd` (H01.4 delivered).
**Specifications/report tooling only. No native/cloud/provider or end-user proof run.**

## Delivered proof plans

[Six paired procedures/case manifests](../specifications/README.md) cover every H01
proof family with **67 required cases**. Each has an accountable H02/H03/H04/H05
owner, contributors, separate execution scopes, setup/safety prerequisites, exact
reserved invocation, deterministic/pinned workload, negative controls, required
observations, cleanup and retained-failure rules. H06 contributes operational acceptance.

| Plan | Cases | Accountable owner |
| --- | --- | --- |
| [Image/schema packaging](../specifications/image_schema.md) | 9 | H02 |
| [Private runtime/physical limits](../specifications/runtime_limits.md) | 11 | H02, H04 supports |
| [Identity/handoff](../specifications/identity_handoff.md) | 11 | H03 |
| [Usage accounting](../specifications/usage_accounting.md) | 10 | H04, H02 supports |
| [Recovery](../specifications/recovery.md) | 17 | H05, H02/H03 support |
| [Operations/economics](../specifications/operations_economics.md) | 9 | H04, H06 supports |

The [common report format](../specifications/REPORT_FORMAT.md) and
[executable models](../../../../application/apps/server/app/platform/hosted_proofs/models.py)
bind exact specification SHA/revision/owner, source/tool/image/schema/workload/sanitized
configuration pins, environment/level, immutable invocation inputs, ordered timestamps,
actual case observations, safe artifact references/digests and remaining limits.
No missing negative control, unresolved evidence reference, unavailable input pin,
invented measurement or partial result can become a validated full pass. A valid
component report remains component scope, not native/Docker/GCP/provider qualification.
Report validity is not evidence authenticity or release authorization.

The non-privileged `python -m app.platform.hosted_proofs` interface supports read-only
`describe`/`validate`. Validation exit codes distinguish valid passed claim (0),
invalid document (1) and valid failed/not-run/unavailable (2). `execute` is a reserved
future owner-driver interface and always returns `proof_executor_unavailable` (3)
before reading any supplied path, writing output or invoking a tool. It cannot
format/mount, reboot, provision, access a database/provider or restore customer data.
No production route, dynamic executable plugin or generic shell parameter was added.

H02–H05 must implement/review their actual driver/input/setup commands before enabling
execution. Qualification only follows real retained evidence and owning review in
the [acceptance register](../HOSTED_MVP_ACCEPTANCE.md). No sample passed target report
is committed; all synthetic report values exist only in focused tests.

## Packaging and historical boundary

The [packaging handoff](../specifications/PACKAGING_HANDOFF.md) records inspection of
current `stage_schema_resources.py`, `verify_installation.py` and `build_wheel.sh`:
staging copies business resources only; installed verification checks public assets
and business revision discovery, not complete independent hosted resources/structure.
H02 must package declared per-component resources and exact compatibility manifests,
then prove fresh initialization, read-only matching validation, no-checkout installation
and missing/wrong-resource rejection. The H01.2 scaffolds remain unavailable baselines.
Current local scripts, wheel metadata and runtime consumers are unchanged.

Imported quota primitives, source/import manifest, before/after-reboot reports and
historical documents remain byte-for-byte unchanged. No retained Lima VM or live demo
host was inspected or modified; no root/native/destructive/provider/cloud operation
was performed. Historical failures and mismatched source pins are not relabelled.

## Focused validation

From `application/`:

```bash
.venv/bin/python -m pytest apps/server/app/platform/tests/test_hosted_proofs.py -q --tb=short
.venv/bin/ruff check apps/server/app/platform/hosted_proofs/__init__.py apps/server/app/platform/hosted_proofs/models.py apps/server/app/platform/hosted_proofs/cli.py apps/server/app/platform/hosted_proofs/__main__.py apps/server/app/platform/tests/test_hosted_proofs.py
.venv/bin/ruff format --check apps/server/app/platform/hosted_proofs/__init__.py apps/server/app/platform/hosted_proofs/models.py apps/server/app/platform/hosted_proofs/cli.py apps/server/app/platform/hosted_proofs/__main__.py apps/server/app/platform/tests/test_hosted_proofs.py
```

**71 focused tests passed in 0.29s.** Ruff check and format check passed on all five
new Python files using `application/pyproject.toml`. No rule exclusions added.
Frontend checks are not applicable; no frontend source/tooling changed. Documentation
links/anchors, case-manifest/procedure coverage, historical hashes, new-file whitespace
and `git diff --check` passed. No full suite or installed release build was required.

| Validation area | H01.5 evidence / remaining delivery |
| --- | --- |
| Happy path | All six specs and passed/failed/not-run/unavailable report shapes round-trip; actual read-only module entry point works from another CWD. No proof executes. |
| Invalid combinations | Missing/extra/duplicate cases and pins, wrong owner/spec/revision, unresolved evidence, false scope/environment, invalid timestamps, fabricated unrun measurements, bool version, omitted limits, duplicate/oversize/deep JSON and unsafe extra fields rejected. |
| Idempotency/retry | Describe/validate do not alter report bytes or register acceptance. Unavailable execution never allocates even when retried. Owning effect retry proofs remain assigned in each plan. |
| Transaction rollback | No store/transaction/effect exists in this tooling; failed validation/unavailable execution writes no target. Real per-owner rollback/commit/fsync cases remain H02–H05. |
| Persistence/schema | No database DDL/baseline or installed-resource claim. Reports are typed bounded JSON evidence; actual schema/packaging proofs remain H02–H05. |
| Backup/restore | H05 plan includes independent catalogs/authority, encrypted readback, damaged stores, strong confirmation, switch crashes and host loss. No actual archive/restore/key operation run. |
| Query budget | No SQL/provider clients or per-row source calls in the package. Actual bounded Admin/source/catalog query plans remain owning implementation gates. |
| UI | Identity/recovery/operational plans require actual deployed-browser proof where relevant; H01.6 fixtures and H03–H05 usable UI remain open. |

H01.1–H01.5 are delivered; H01.6–H01.7 and every fresh runtime/native/cloud/end-user
release gate remain open. The next slice is H01.6, not automatic activation of proof
drivers, release qualification or live admission.
