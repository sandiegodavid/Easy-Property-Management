# H01.7 — Consolidated contract validation and H02 handoff

Completed November 11, 2026 on `hosted_mvp`. H01.1–H01.7 implementation preparation
is delivered and ready for contract review. **This report does not assert review
acceptance, native/cloud qualification, a usable hosted workflow or release approval.**

## Source and evidence identity

- H01 implementation baseline: `f9d3707b966f664fe8037b5f1b557f72f74245ed`, clean at
  H01.1 start; the [baseline inventory](HOSTED_MVP_H01_1_BASELINE_2026-11-10.md) and
  its 78 original input pins remain historical evidence.
- H01.7 start: clean `46462673cb92df7bdc2e58e4b56d715ce381eadc` on `hosted_mvp`.
- [Machine-readable validation evidence](HOSTED_MVP_H01_7_VALIDATION_2026-11-11.json)
  records the exact commands, all 35 H01 Python paths, tested input SHA-256 pins,
  environment, results, ownership/link checks and remaining gates. This is H01
  validation metadata, not a target-proof v1 report. Two source files
  differ from the H01.7 start commit; their tested working-tree hashes are explicit.
- Environment: Darwin 27.0.0 / arm64, Python 3.14.8, pytest 8.4.2, Pydantic 2.14.0,
  SQLAlchemy 2.1.4, Alembic 1.20.0 and Ruff 0.16.10. These are local contract-test
  tool versions, not a qualified Linux/Docker/cloud image.

The schema cross-check found one H01 contract inconsistency: the older
`AdminObservation.setup_state` included `ready`/`disabled` rather than the master's
`preparing`/`ready_for_claim`. It now uses the same six lifecycle states as the master
and `OperatorSummary`; the focused dictionary test checks both projections. Disabled
source access remains separate from setup and desired intent. This is a presentation
contract correction, not a business-data migration, changed access grant or new runtime
consumer. The second changed file adds that regression assertion.

## Consolidated focused results

From `application/`:

```bash
.venv/bin/python -m pytest apps/server/app/platform/tests/test_schema_resources.py apps/server/app/platform/tests/test_hosted_contracts.py apps/server/app/platform/tests/test_hosted_ports.py apps/server/app/platform/tests/test_hosted_proofs.py apps/server/app/platform/tests/test_hosted_ui_contracts.py apps/server/app/platform/tests/test_api_errors.py -q --tb=short
```

**423 passed, 0 failed, 0 skipped in 1.14s** after the lifecycle correction. This is
one consolidated focused contract run, not the full server suite or target proof run.

Ruff check and format check passed for **all 35 Python files changed since the H01
implementation baseline**, including tests, package markers and the five unavailable
migration environments, using `application/pyproject.toml`. The JSON evidence stores
the complete file list and exact argument arrays. To repeat the same lint scope from
`application/`:

```bash
.venv/bin/python - <<'PY'
import json
import subprocess
from pathlib import Path
report = Path('../docs/hosting/qualification/reports/HOSTED_MVP_H01_7_VALIDATION_2026-11-11.json')
evidence = json.loads(report.read_text())
for command in evidence['validation_commands'][1:]:
    subprocess.run(command, check=True)
PY
```

No rule thresholds/exclusions changed. Frontend lint/format/typecheck are **not
applicable**: H01 changed no React/TypeScript/JavaScript, frontend tooling or generated
contracts. New Python UI snapshots remain declarations/fixtures, not browser screens.

No additional legacy local/hosted suite was necessary: new contracts/scaffolds are
not wired into current bootstrap and original application consumers remain byte-for-byte
at the H01 baseline. The existing shared API-error test is included because new typed
bounds/conflicts rely on that mapper. Prior isolated legacy configuration/session/
budget/CLI results remain in their original H01 reports; they are not retested or
promoted into fresh-hosted qualification here.

## Documentation and ownership checks

The audit checked Markdown paths, generated heading anchors and preserved explicit
HTML anchors across the H01 design/reports, current split schema master, proof plans,
UI fixtures and resource guides. It also compared current table headings with H01.1's
ownership checklist and checked every proof-case ID against its procedure table.
Exact final counts are in the JSON evidence.

- All **37 schema table ownership entries** match the current master; H01 does not
  claim its proposed tables/constraints/initializers exist.
- **78 baseline Git blob/SHA-256 pins** verified against the original commit, with
  original application inputs unchanged.
- **13 quota-import/historical inputs** verified unchanged, including original reboot
  reports and archived runbooks. Three current imported source pins still differ from
  historical qualification as documented; no new native pass is inferred.
- Six proof plans retain **67 planned cases**, not executed target checks; typed
  report validation rejects missing/unavailable evidence represented as a full pass.
- **24 synthetic UI snapshots and 22 action mappings** retain actual owning H03/H04/H05
  delivery, authority, confirmation and original-result semantics.
- New H01 non-test application Python adds no table creation/`create_all`/attachment
  initializer. The old inline hosted-access DDL remains an explicit H03/H04 atomic
  replacement obligation, not an exception approved for new implementation.
- Existing business resources, local runtime/deployment consumers and package/staging
  behavior are unchanged. Documentation/new-file whitespace and `git diff --check`
  passed. No VM, provider, real data, quota experiment or cloud resource was touched.

## Proven level versus remaining proof

| Validation area | H01 evidence | Owning implementation still required |
| --- | --- | --- |
| Happy path | Typed shared/owning values, request/result/manifest/report/UI fixtures validate. | H02–H05 real application/store/provider/runtime behavior. |
| Invalid combinations | Wrong IDs/scopes/roles/epochs/resources/components, malformed/bounded records, incompatible versions, unavailable prerequisites and unsafe UI states rejected by contracts. | Real current-authority/resource/constraint enforcement at actual effects. |
| Retry/idempotency | Deterministic semantic vectors, original-result comparison, unknown outcomes and retained submission identity in fixtures. | Atomic durable unique-key reservation, real lost-response/host-effect reconciliation and terminal result immutability. |
| Rollback | Unavailable scaffolds do not create/stamp/touch destinations; supplied connections remain owned/open; negative preflight has no fixture effect. | Actual baseline/domain/audit/receipt rollback, commit/fsync failures and cross-store recovery. No mock pass substitutes for these. |
| Persistence/schema | Independent unavailable resource sets; exact store/component ownership and compatibility shapes. | H02–H05 complete executable baselines, resource-derived structural/retained validators, protected initialization and real installed-component checks. |
| Backup/restore | Separate workspace/control authority, scope/key/destination/strong-confirmation contracts and reproducible recovery proof plan. | H05 actual keys/catalogs/capture/readback/retention/locator-switch/recovery-mode and host-loss proofs. No archive/restore executed. |
| Query budget | Bounded DTOs/cursors and explicit set-based/async handoff; legacy indexed-session invariant remains previous limited evidence. | H03/H04/H05 actual indexed/bounded repository query plans, no per-row source calls. |
| UI | Typed states/defaults/actions and context-preservation requirements, with named owners. | H03 authentication; H04 Admin-lite/Settings; H05 normal/minimal recovery, all with actual keyboard/themes/narrow/focus/scroll/browser acceptance. No separate UI backlog deferral. |

## H02 and subsequent delivery handoff

H02 may begin its **detailed design after H01 contract review acceptance**. This
implementation/validation task does not supply or assert that external acceptance.
H02 implementation still requires its own completed detailed design and safe setup.
Use the [proof specifications and packaging handoff](../specifications/README.md)
and [selective quota reuse boundary](../HOSTED_PROJECT_QUOTA_REUSE.md); do not import
or activate the older Admin stack merely because its namespace/primitives exist.

| Owner | Required next delivery before enabling its capability |
| --- | --- |
| H02 | Complete detailed design; separate immutable Admin/Operator/agent artifacts and actual schema-resource installation; private gateway/agent bindings, exact Linux/Docker/GCP sandbox/quota/reboot/capacity and private-transport proofs. Preserve the retained lab baseline and obtain deliberate native setup before experiments. |
| H03 | Complete managed identity/invitation/handoff/MFA/source session and private-auth design/implementation; replace inline access schema atomically with consumers; qualify current actor/epoch/revocation and actual authentication UI. |
| H04 | Complete Admin-lite/Free policy/operations/usage baselines and repositories; crash-safe reservations/admission, known/unknown projections, real retry/rollback/query-budget and usable Admin/Settings workflows. |
| H05 | Complete both independent recovery schemas/catalogs/keys/engine, strong current authority, safe staging/switch/security/host-loss proof and normal/minimal recovery UI; source-selected destinations, no offline customer restore/decrypt bypass. |
| H06 | Accept H02–H05 proofs, supported operational/support/maintenance/economic runbooks and real invited Free pilot evidence within qualified capacity; five is a proof target, not a cap. |

No H01 test authorizes live admission, quota activation, restores, billing, browser
controls or migration of old deployed data. All fresh-target release gates remain
open in the [acceptance register](../HOSTED_MVP_ACCEPTANCE.md). H01 is ready for its
contract-review handoff; H02 implementation has not started in this task.
