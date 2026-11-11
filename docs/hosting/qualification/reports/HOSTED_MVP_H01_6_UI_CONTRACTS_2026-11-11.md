# H01.6 — Synthetic UI/API states and delivery mapping

Delivered November 11, 2026 on `hosted_mvp`, starting from clean commit
`f749034d0302967a837d9bfe003519a0b6c440fe` (H01.5 delivered).
**Fixtures and presentation contracts only; no screens or usable workflow delivered.**

## Delivered boundary

The [fixture guide](../fixtures/README.md),
[versioned JSON corpus](../fixtures/H01_UI_CONTRACTS.json) and
[action map](../fixtures/ACTION_MAP.md) freeze **24 synthetic cases** across five
surfaces and **22 typed action mappings**. Case IDs/UUIDs/times are deterministic;
all people, emails, amounts, proof references and hashes are fictional, not evidence
of actual source state, authority, metering or qualification.

| Contract boundary | Implementation |
| --- | --- |
| Shared section/action/preservation/Free/protection primitives | `platform/hosted_contracts/ui_states.py` |
| Admin list/add/detail DTOs, raw bounded drafts and readiness | `modules/hosted_admin/application/ui_contracts.py` |
| Hosted Operator Settings/recovery DTOs and current-authority gates | `modules/hosted_access/application/ui_contracts.py` |
| Cross-module fixture/action composition | `bootstrap/hosted_ui_contracts.py` (not imported by runtime bootstrap) |

Paths are under `application/apps/server/app/`. Owners retain their application DTOs;
only bootstrap composes cross-module ports. Shared primitives import no owning module,
ORM, HTTP, cloud or filesystem implementation. No schema definition/DDL, production
route, runtime grant, command dispatch, polling loop or browser control is introduced.

Fixtures distinguish:

- Pending setup/requested enablement versus verified disabled source access; a
  setup-complete account may be source-disabled. Setup vocabulary follows the
  owning schema dictionary, rather than conflating disabled access with setup.
- Known zero versus unknown/null usage; stale retained data versus failed/loading
  sections; independently failed access/protection/maintenance and healthy siblings.
- Default Free 50,000,000 bytes/empty portfolio, optional explicit synthetic data and
  no expiry/read-only/demo/paid/scheduler/idle-wake input.
- Invalid raw email/slug/text with multiple field errors, conflict revisions and
  preserved values/focus/scroll; no coercion into a valid command while editing.
- Pending and unknown submissions with original operation/key/intent. Unknown cannot
  expose another create/confirm action; checks use owning original-result lookup.
- Bounded deployment/filter/capture/source/ordering-aware directory continuations,
  1-row page examples, reset on filter changes, and explicit asynchronous source
  refresh operation instead of synchronous per-row source/provider polling.
- Unqualified/current-identity-unavailable restore and minimal recovery mode; own-point
  selection, strong exact preview/point/hash confirmation and original restore lookup.
  Neither an Admin projection nor an ordinary Admin session grants customer restore.

Action mappings point to actual H01.4 ports/methods/payload classes and explicitly
name delivery owner, authority, confirmation, response and original-identity semantics.
Settings authenticates the operator before its owning adapter performs the private
source-service read; metadata does not pass a browser actor directly to that private
port. H03 similarly resolves managed browser proof before Login recent-authentication.
The two control-plane restore mappings belong only to H05's separate protected
Admin recovery entry point and cannot appear on the five surfaced snapshots.

These DTOs are presentation projections, not persisted rows or another schema master.
H04/H05 adapters own mapping to the allowed persistence operation families and scoped
receipts. Existing H01.4 port DTOs/current consumers are not rewired by H01.6.

## Focused validation

From `application/`:

```bash
.venv/bin/python -m pytest apps/server/app/platform/tests/test_hosted_ui_contracts.py -q --tb=short
.venv/bin/ruff check apps/server/app/platform/hosted_contracts/ui_states.py apps/server/app/modules/hosted_admin/application/ui_contracts.py apps/server/app/modules/hosted_access/application/ui_contracts.py apps/server/app/bootstrap/hosted_ui_contracts.py apps/server/app/platform/tests/test_hosted_ui_contracts.py
.venv/bin/ruff format --check apps/server/app/platform/hosted_contracts/ui_states.py apps/server/app/modules/hosted_admin/application/ui_contracts.py apps/server/app/modules/hosted_access/application/ui_contracts.py apps/server/app/bootstrap/hosted_ui_contracts.py apps/server/app/platform/tests/test_hosted_ui_contracts.py
```

**66 focused tests passed.** Ruff check and format check passed for all five new
Python files using `application/pyproject.toml`. No lint policy changed. Frontend
checks are not applicable: no frontend source/tooling changed. Documentation links,
action-table/fixture consistency, new-file whitespace and `git diff --check` passed.
No full suite, browser, database, archive, native VM, provider or cloud test was run.

| Validation area | Fixture evidence / actual owner obligation |
| --- | --- |
| Happy path | All 24 typed snapshots round-trip across five surfaces; defaults, all 22 command/read mappings and named owners validate. H03/H04/H05 deliver actual accessible workflows. |
| Invalid combinations | Unknown fields/controls, paid/expiry/scheduler/idle choices, fake known-zero sections, missing readiness/strong authentication/preview, cross-deployment/operator/intent data, stale cursor context and duplicated actions are rejected. |
| Retry/idempotency | Original reference/key/hash retained; unknown create/restore cannot admit a new submission identity or automatic replay. Real receipt uniqueness/dispatch reconciliation remains H04/H05. |
| Transaction rollback | No transaction/side effect exists; validation does not mutate source data. Actual command/audit/receipt rollback remains owning implementation proof. |
| Persistence/schema | Dictionary setup states and Free values checked; no table/DDL/baseline change and no current runtime dependency. Persistence adapters/structural validation remain H02–H05. |
| Backup/restore | Scoped own-point presentation, unavailable recovery and separate strong operator versus protected control authority only. No archive or restore run; H05 security/recovery/browser acceptance remains open. |
| Query budget | Bounded cursor/page and declared set-based/async strategy freeze the handoff. No SQL is measured; H04 must prove actual bounded queries and absence of per-row source calls. |
| UI/browser | Preservation flags and state snapshots are requirements, not rendered focus/scroll proof. H03 proves authentication/session behavior; H04 proves Admin-lite/Settings; H05 proves recovery UI, including keyboard/themes/narrow layouts and real rejection/unknown-outcome behavior. |

H01.1–H01.6 are delivered. H01.7 consolidated contract validation/handoff and every
fresh-target runtime/native/cloud/end-user release gate remain open. No UI work is
deferred to a separate backlog; owning H03–H05 acceptance remains required.
