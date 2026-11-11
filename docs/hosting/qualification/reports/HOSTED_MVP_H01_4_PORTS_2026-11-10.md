# H01.4 — Owning ports and compatibility manifests

Completed November 11, 2026 on `hosted_mvp`; implementation began November 10
from clean commit
`b3ca0a5973115e094b838a5464befefe11e8db2e` (H01.3 delivered).
**Application contracts only: no production adapters/routes, stores or host effects.**

## Ownership and typed command coverage

Every port exposes typed `execute`, bounded `observe` and original-operation lookup.
Inputs use concrete discriminated action records under H01.3's checked intent hash,
expected revision and access epoch. Results are typed original-outcome envelopes,
not ORM rows, arbitrary JSON, shell output or credential-bearing grants. Ports do not
open another owner's store or imply a cross-store transaction.

Paths below are relative to `application/apps/server/app/modules/`:

| Owning application contract | Covered Pilot 0 actions | Invocation / observation boundary |
| --- | --- | --- |
| `hosted_admin/application/pilot_contracts.py` | Create assignment, provision, repair runtime, reissue invitation, disable, enable, rebind, prepare/confirm retirement, async source refresh, maintenance release and announcement | Current managed Admin/MFA proof; deployment scope for initial assignment/announcement and matching component scope for release. Safe setup/desired/effective access, usage/release/protection summaries; never workspace restore catalog/authority. |
| `host_agent/application/contracts.py` | Prepare resources, initialize/repair/start/stop container, apply qualified limits, stage restore, switch binding, retire resources | Authenticated private service caller; registered resource/image/release/profile IDs only. Stage/switch requires the matching operator or Admin recovery service, not ordinary Admin orchestration. Inventory resolves actual paths, project IDs and immutable images. |
| `hosted_access/application/source_contracts.py` | Initialize disabled binding, claim, enable, disable, revoke sessions, maintenance fence/drain, verify restore binding, reserve/reconcile usage | Authenticated Admin/source service; restore binding belongs to operator recovery. One exact workspace, current source epoch and owning receipts. Readiness/effective access/usage observations stay source-owned. |
| `hosted_access/application/login_contracts.py` | Validate identity, consume invitation, issue/redeem handoff, issue/revoke session, recent authentication | Trusted managed-proof context pins assignment, registered origin and browser binding. No raw JWT/email-link/cookie in persistent commands/results. H03 verifies current provider proof and handles ephemeral token delivery at its transport boundary. |
| `workspace/application/recovery_contracts.py` | Own-point observations, preview/confirm restore, internal capture/checkpoint reconciliation and authenticated catalog reconstruction | Current operator or supported local OS-owner authority for catalog/preview; restore needs exact-intent confirmation plus strong operator step-up or local ownership. Private operator backup service alone captures/reconciles. Source chooses staging destinations; no destination/path input. |
| `hosted_admin/application/recovery_contracts.py` | Control-point observations, preview/confirm control restore, internal control capture/checkpoint reconciliation | Protected current bootstrap/MFA recovery authority independent of main Admin principal/session rows; separate private Admin backup system caller. Deployment scope only, no customer-workspace restore authority. |

There are **47 concrete action variants**. Provisioning includes immutable release,
initial-data/seed selection and typed warm-memory/CPU/workspace/control/scratch
byte/inode commitments; empty is the default and cannot carry a seed bundle. No
new operator mode or seed-stage replay journal is introduced. Repairs retain registered
binding/release/generation identity and cannot supply empty-business initialization.

Shared invocation/query types are in
[authority.py](../../../../application/apps/server/app/platform/hosted_contracts/authority.py).
Invocation guards check role shape, deployment/workspace binding and exact confirmation
where required. **These are not authenticators.** H02/H03/H05 must resolve protected
proof references, verify current provider/channel identity, MFA/step-up freshness,
actual enabled state, live fences and authorization before using these ports.
No caller can obtain authority merely by constructing one of these Python models.

Adapters must reserve original keys and commit request/audit/receipt in their owning
short transaction, with effects outside it. Matching retries return the original
identity/result; changed semantics conflict; timeout/unknown requires original receipt
inspection. Read/status lookup is authenticated too. The deterministic in-memory test
double proves contract behavior only, not rollback, persistence or native deduplication.

## Versioned compatibility and qualification

[compatibility.py](../../../../application/apps/server/app/platform/hosted_contracts/compatibility.py)
pins component/release, registered artifact reference, exact artifact SHA-256 and
OCI manifest digest when applicable; exact API/source/agent/inventory versions;
owned/readable schema revisions; native/provider evidence bound to that exact artifact.
There are no wildcard versions, tags as image-selection inputs or default approvals.

Admin OCI owns main Admin plus separate Admin recovery schemas. Operator OCI owns
business/access/operator-recovery schemas. Future Tenant/Owner web bundles own no
schemas and declare business-source compatibility, not direct database access or
upgrade rights. Admin manifests do not claim another service's private stores;
inventory compatibility is an agent protocol/schema pin, not an Admin SQL connection.
Duplicate/conflicting ownership and unsupported component/artifact pairings fail.
Operator assignments are workspace-scoped; Admin/Tenant/Owner assignments are shared.
Wrong release/component, source/API/agent/inventory or schema versions reject before
fixture dispatch. Missing/failed qualification is explicitly unavailable, never passed.

H02 must authenticate/protect manifest and qualification references, package separate
artifacts and prove private transport. Fixture evidence is synthetic and is not an
actual qualification result. No Tenant/Owner release is registered or activated here.

## Focused validation

From `application/`:

```bash
.venv/bin/python -m pytest apps/server/app/platform/tests/test_hosted_ports.py apps/server/app/platform/tests/test_hosted_contracts.py apps/server/app/platform/tests/test_api_errors.py -q --tb=short
```

Result: **202 focused tests passed in 0.55s** on November 11, 2026. This includes all 47 owning action fixtures,
matching retry/original lookup and wrong-actor denial before any fixture effect;
manifest round-trips, component scopes, exact version/schema/digest mismatches,
unavailable qualification, restore-role/confirmation separation, source-selected
restore destinations, raw path/image rejection and unavailable-not-zero observations.

Ruff check and format check passed on all **13 changed/new Python files**, including
package markers, using `application/pyproject.toml`; no rule exclusions added.
The checked file list is the union of `git diff --name-only -- application/` and
`git ls-files --others --exclude-standard -- application/`, filtered to `.py` and
made relative to `application/`, passed to `.venv/bin/ruff check` and
`.venv/bin/ruff format --check` from that directory.
Frontend checks are not applicable. Documentation links, new-file whitespace and
`git diff --check` passed. Existing runtime/schema/bootstrap consumers are unchanged;
no full suite, real store, VM, provider or cloud test was run.

| Validation area | Evidence / remaining gate |
| --- | --- |
| Happy path / invalid input | Typed consumer/provider action and outcome fixtures, bounded observations, authority/scope separation and unsupported pairing rejection. Actual adapters remain H02–H05. |
| Retry / idempotency | In-memory original identity/result retained once for matching retry; mismatched request semantics remain H01.3 conflict. Durable uniqueness/effect reconciliation is not established. |
| Transaction rollback | No real transaction/effect performed; failed preflight leaves the fixture effect counter/receipt map unchanged. Owning real rollback remains open. |
| Persistence/schema | No schema creation or table changes. Manifest/schema pins are compatibility contracts, not structural DB validation. |
| Backup/restore | Separate customer/control authority and safe source-selected destination contracts only; H05 security/integrity/crash/host-loss proofs remain open. |
| Query budget | Page bounds and unavailable observations validate; no per-row provider/SQL call exists in these contracts. Owning real query plans remain open. |
| UI | No placeholder route, runnable recovery command or control exposed. H01.6 fixtures and H03–H05 usable workflows remain open. |

Next: H01.5 proof/report/packaging specifications, then H01.6–H01.7. All hosted
runtime/native/cloud/end-user release gates remain unestablished. Existing active old
consumers remain until their replacements are integrated; remove obsolete code then.
