# H01.1 — Implementation baseline and ownership inventory

Recorded November 10, 2026. **H01.1 delivered: inventory and ownership evidence only.**
H01.2–H01.7 and H02–H05 implementations remain outstanding. This report does not
qualify a hosted release, identity provider, storage limit, backup or live admission.

## Reproducible baseline

- Implementation-start commit: `f9d3707b966f664fe8037b5f1b557f72f74245ed` on `hosted_mvp`.
- Working tree at start: **clean** (`git status --porcelain=v1` returned no entries,
  including untracked files); captured before writing this report or editing design status.
- [Source manifest](HOSTED_MVP_H01_1_BASELINE_2026-11-10.json): 78 tracked
  inputs with Git blob IDs and SHA-256 of exact baseline bytes. Each was compared with
  `git show f9d3707b966f664fe8037b5f1b557f72f74245ed:path` before recording. Design/register hashes describe the
  **pre-edit baseline**, not the resulting H01.1 documentation.
- [Quota import manifest](../PROJECT_QUOTA_IMPORT_MANIFEST.json) and
  [reuse boundary](../HOSTED_PROJECT_QUOTA_REUSE.md) retain the upstream import at
  `cba6a7bf2561de06634abbddff0b60782949e6fc`. Imported sources, original reports and
  archived documents are unchanged. Three current imported source pins differ from
  historical qualification, as already recorded there; no new native pass is inferred.

Reproduce baseline verification from the repository root by reading each manifest
`path` at `implementation_start_commit` with `git show`, hashing its bytes with
SHA-256 and comparing its Git object ID with `git rev-parse f9d3707b966f664fe8037b5f1b557f72f74245ed:path`.
Do not compare future edited working-tree files with these historical pins and
silently rewrite the baseline. Record new evidence for changed implementations.

## Current-code reassessment

Every row in H01's current implementation assessment was checked against the baseline.
Paths below are relative to the repository root and pinned in the source manifest.

| Boundary and inspected source | Observed behavior | Disposition and delivery owner |
| --- | --- | --- |
| `hosted_access/application/configuration.py` | Only `hosted_demo`; maximum 14-day account window, eight-hour session cap, 50 MiB file limit and 250 MiB workspace-volume constant. Session expiry is also capped by assertion and demo expiry in `application/service.py`. | **Replace** expiring demo/account and capability policy with fresh Free pilot contracts: H03 identity/session policy, H04 Free 50 MB logical allowance; H02 physical enforcement. Do not confuse MB allowance with old MiB volume size. |
| `hosted_access/infrastructure/schema.py`, `session_store.py` | Runtime inline Alembic `Operations.create_table`, revision `hosted_0001`, five access tables plus version; exclusive private-file initialization inserts a disabled operator. Reflection checks table set, revision and binding, not the complete proposed master. Pending enrollment requires explicit activation; generation/not-before fence sessions and restore-marker changes clear authority. | **Reuse concepts**, **replace schema/claim implementation** atomically in H03/H04. This is one per-workspace access DB despite `administration_database` naming, not central Admin. H03 owns resource move and new access/claim schema; H04 contributes usage and Free policy. H01.2 scaffolding must not switch current consumers. |
| `hosted_access/infrastructure/cloudflare_identity.py` | RS256 Access assertion verification, exact issuer/audience/email claims, bounded key discovery/cache/refresh and safe error translation. | **Reuse security properties**, **replace provider composition** in H03 with qualified managed Google/email-link identity and browser-bound handoff; existing verifier is not proof of the new login. |
| `hosted_access/application/storage_budget.py`, `infrastructure/storage_budget.py` | Process-local lock/reservation counter, conservative body-copy/headroom admission; Linux root-owned fixed ext4 loop-image identity and staging checks, statvfs facts. | **Reuse fail-closed/error/cleanup intent**; H02 replaces/proves runtime physical mechanism; H04 implements reproducible logical accounting and crash-safe reservations. No current durable Free usage ledger. |
| `hosted_access/infrastructure/recovery_publication.py`, `application/recovery_publication.py` | Private bounded JSON ledger with atomic replace/fsync, encrypted archive upload/full digest readback before pruning, daily retention; 512 MiB archive cap. Existing offline backup/recovery bundle tooling is a legacy path, not target restore authorization. | **Reuse verification/failure concepts** only; H05 adds private recovery SQLite, consistent capture/checkpoints, unattended keys, scoped authenticated restore and separate Admin recovery. No old JSON ledger or offline customer restore path is adopted as the new authority. |
| `database/sqlite-migrations/versions/0001_initial_schema.py`, `env.py`, `platform/product_migrations.py` | Business Alembic baseline and module structural/retained validation remain domain-owned. | **Reuse unchanged**; no H01 business-table edits, auth/billing additions or cross-store foreign keys. H02 packages the declared component resources; H03–H05 deliver their independent baselines. |
| `deploy/hosted-demo/epm-hosted@.service`, `bootstrap/hosted_access.py` | Unprivileged systemd process and private paths, old loop-volume source composition; explicit middleware/session/draft wiring. No Docker host agent or central Admin service. | **Reference/reuse fencing intent**; **new** H02 container, gateway, protected inventory, immutable component packaging and restricted private agent; H03 authenticates private source/identity transport. Do not relax existing local middleware. |
| `apps/web/src/app/hosted-session.tsx`, `apps/web/tests-hosted/` | Explicit session bootstrap/pause, stale-read sequence guard, focus/visibility checks, expiry and explicit continuation; Cloudflare/pending-approval copy and legacy read-only fixtures. | **Reuse input/session-change fencing**; H03 replaces login/claim and policy fixtures, H04 adds actual Admin-lite/Free Settings, H05 recovery UI. Old browser assertions cannot qualify new production roles or containers. |
| `scripts/stage_schema_resources.py`, `verify_installation.py`, `build_wheel.sh` | Staging copies business `sqlite-migrations`/`alembic.ini`; installation verifies compiled assets and current business revision, not independent Admin/access/inventory/recovery resources or compatibility manifests. | **New H02 packaging work**, specified by H01.2/H01.4/H01.5. Leave local install behavior operational; existing wheel is not a fresh-MVP artifact. |
| `modules/hosted_admin/` | Selectively imported quota primitives, systemd/seccomp sandbox, adversarial workload and opt-in harness/tests only; no Admin application/router/schema. | **Reuse only through H02 detailed design and requalification**. No older Admin stack imported, registered or used as evidence of missing Pilot 0 features. |

## Replacement and unused-code removal

Remove superseded implementations, imports, fixtures and tooling in the same owning
slice that replaces their supported callers; do not retain an unused compatibility
path. Verify production/bootstrap/CLI, demo/local launch and test callers before deletion.
The inspected old components are **still referenced**, not unused at this baseline:
`bootstrap/api.py` calls `compose_hosted_access`; that composition constructs the
old session, identity and storage adapters; `session_store.py` invokes the inline
schema; `app/__main__.py` imports the legacy administration, offline backup and
recovery publication/bundle commands. `scripts/hosted_browser_server.py` also consumes
the old configuration/session/identity/budget adapters.

H02 removes superseded deployment/physical adapters once replacement callers work;
H03 removes replaced inline schema and identity/session/approval paths with their
consumers; H04 removes replaced demo policy and in-memory admission paths; H05 removes
superseded JSON-ledger/offline customer recovery paths and fixtures. Preserve any
shared primitive still required by supported local/domain behavior or qualification.
No runtime code is deleted in H01.1 because no inspected replacement is wired in yet.

## Store and schema ownership checklist

The links are the master dictionary's table headings; column definitions are not
copied here. **Owner** is the accountable delivery slice; contributors do not create
another schema authority. Every proposed table below is currently **not delivered**.
H01.2 establishes resource scaffolding only, not initialized empty baselines.

| Store | Single accountable owner | Authority and resource handoff |
| --- | --- | --- |
| Existing business SQLite | Existing domain modules (H02 packaging only) | `application/database/sqlite-migrations/` unchanged; no Admin/auth authority. |
| Main Admin SQLite | H04 | `admin-migrations/`; H02 contributes release resources; H03 contributes identity/session resources. H04 composes the complete Pilot 0 store. |
| Protected host inventory SQLite | H02 | `host-inventory-migrations/`; private agent owns bindings/effect receipts, H04 consumes typed commands. |
| Per-operator access SQLite | H03 | `hosted-access-migrations/`; H04 contributes source policy/accounting resources and admission. No direct Admin access. |
| Per-operator recovery SQLite | H05 | `recovery-migrations/`; independent from business/access stores, normal and minimal authenticated recovery. |
| Admin recovery SQLite | H05 | `admin-recovery-migrations/`; main-Admin-independent current bootstrap/MFA, catalog/operations/audit. |
| Off-host immutable manifests and protected keys/configuration | H05 | Not additional SQL stores; verified object/key custody and host-loss recovery inputs. H02 protects runtime bindings; H03 supplies current identity proofs. |

All proposed resource directories above are under `application/database/` and **absent
at this baseline**. Only the business resource set exists. Persisted identities,
release assignments, resource bindings and receipts belong to their named stores;
observed runtime/quota facts and async protection/usage projections are not alternate
editable authority. No cross-store transaction or foreign key is implied.

| Master table heading | Owner | Delivery boundary |
| --- | --- | --- |
| [`alembic_version` — each SQLite store](../../../DATABASE_SCHEMA.md#alembic_version--each-sqlite-store) | Per owning store | H02: inventory/release resources; H03: access/auth resources; H04: Admin-lite/usage resources; H05: both recovery stores. Business revision remains domain-owned. H01.2 only scaffolds. |
| [`control_meta` — H04 initialization](../../../DATABASE_SCHEMA.md#control_meta--h04-initialization) | H04 | Owning slice delivers baseline, initializer, structural/retained validation and focused persistence proofs. |
| [`storage_policies` — H04 Free policy](../../../DATABASE_SCHEMA.md#storage_policies--h04-free-policy) | H04 | Owning slice delivers baseline, initializer, structural/retained validation and focused persistence proofs. |
| [`qualified_releases` — H02 release qualification](../../../DATABASE_SCHEMA.md#qualified_releases--h02-release-qualification) | H02 | Owning slice delivers baseline, initializer, structural/retained validation and focused persistence proofs. |
| [`component_deployments` — H02 shared Admin; H04 Operator assignments](../../../DATABASE_SCHEMA.md#component_deployments--h02-shared-admin-h04-operator-assignments) | H02 | H02 owns shared/component scope and compatibility; H04 inserts per-workspace Operator assignments. |
| [`operators` — H03/H04 assignment and desired state](../../../DATABASE_SCHEMA.md#operators--h03h04-assignment-and-desired-state) | H04 | H03 supplies verified identity binding; H04 owns assignment/readiness and desired state. |
| [`invitations` — H03](../../../DATABASE_SCHEMA.md#invitations--h03) | H03 | Owning slice delivers baseline, initializer, structural/retained validation and focused persistence proofs. |
| [`admin_principals` — H03](../../../DATABASE_SCHEMA.md#admin_principals--h03) | H03 | Owning slice delivers baseline, initializer, structural/retained validation and focused persistence proofs. |
| [`admin_sessions` — H03](../../../DATABASE_SCHEMA.md#admin_sessions--h03) | H03 | Owning slice delivers baseline, initializer, structural/retained validation and focused persistence proofs. |
| [`login_handoffs` — H03 central login](../../../DATABASE_SCHEMA.md#login_handoffs--h03-central-login) | H03 | Owning slice delivers baseline, initializer, structural/retained validation and focused persistence proofs. |
| [`operations` — H04 supported manual effects](../../../DATABASE_SCHEMA.md#operations--h04-supported-manual-effects) | H04 | Owning slice delivers baseline, initializer, structural/retained validation and focused persistence proofs. |
| [`operation_events` — H04](../../../DATABASE_SCHEMA.md#operation_events--h04) | H04 | Owning slice delivers baseline, initializer, structural/retained validation and focused persistence proofs. |
| [`admin_audit` — H03/H04](../../../DATABASE_SCHEMA.md#admin_audit--h03h04) | H04 | H03 supplies authentication events; H04 owns the common mutation/audit boundary. |
| [`workspace_recovery_status` — H05](../../../DATABASE_SCHEMA.md#workspace_recovery_status--h05) | H05 | Owning slice delivers baseline, initializer, structural/retained validation and focused persistence proofs. |
| [`admin_recovery_meta` — H05](../../../DATABASE_SCHEMA.md#admin_recovery_meta--h05) | H05 | Owning slice delivers baseline, initializer, structural/retained validation and focused persistence proofs. |
| [`control_recovery_operations` — H05](../../../DATABASE_SCHEMA.md#control_recovery_operations--h05) | H05 | Owning slice delivers baseline, initializer, structural/retained validation and focused persistence proofs. |
| [`control_recovery_points` — H05](../../../DATABASE_SCHEMA.md#control_recovery_points--h05) | H05 | Owning slice delivers baseline, initializer, structural/retained validation and focused persistence proofs. |
| [`control_restore_operations` — H05](../../../DATABASE_SCHEMA.md#control_restore_operations--h05) | H05 | Owning slice delivers baseline, initializer, structural/retained validation and focused persistence proofs. |
| [`control_backup_state` — H05](../../../DATABASE_SCHEMA.md#control_backup_state--h05) | H05 | Owning slice delivers baseline, initializer, structural/retained validation and focused persistence proofs. |
| [`control_recovery_audit` — H05](../../../DATABASE_SCHEMA.md#control_recovery_audit--h05) | H05 | Owning slice delivers baseline, initializer, structural/retained validation and focused persistence proofs. |
| [`host_identity`](../../../DATABASE_SCHEMA.md#host_identity) | H02 | Owning slice delivers baseline, initializer, structural/retained validation and focused persistence proofs. |
| [`resource_bindings`](../../../DATABASE_SCHEMA.md#resource_bindings) | H02 | H04 records admitted provisioning results via the H02 agent; no direct Admin SQL. |
| [`project_assignments` — H02 if project quotas qualify](../../../DATABASE_SCHEMA.md#project_assignments--h02-if-project-quotas-qualify) | H02 | Conditional on H02 qualification; do not infer selection from historical reports. |
| [`host_receipts`](../../../DATABASE_SCHEMA.md#host_receipts) | H02 | H02 owns effect identity/reconciliation; H04 orchestrates supported manual operations. |
| [`access_meta` — H03/H04](../../../DATABASE_SCHEMA.md#access_meta--h03h04) | H03 | H03 owns access identity/epoch; H04 supplies applied Free-policy and usage bindings. |
| [`access_sessions` — H03](../../../DATABASE_SCHEMA.md#access_sessions--h03) | H03 | Owning slice delivers baseline, initializer, structural/retained validation and focused persistence proofs. |
| [`access_receipts` — H03/H04](../../../DATABASE_SCHEMA.md#access_receipts--h03h04) | H03 | H03 owns source access receipts; H04 contributes policy/admission effects through the same contract. |
| [`access_audit` — H03](../../../DATABASE_SCHEMA.md#access_audit--h03) | H03 | Owning slice delivers baseline, initializer, structural/retained validation and focused persistence proofs. |
| [`usage_state` — H04](../../../DATABASE_SCHEMA.md#usage_state--h04) | H04 | Owning slice delivers baseline, initializer, structural/retained validation and focused persistence proofs. |
| [`usage_reservations` — H04](../../../DATABASE_SCHEMA.md#usage_reservations--h04) | H04 | Owning slice delivers baseline, initializer, structural/retained validation and focused persistence proofs. |
| [`draft_leases` — H03 reuse existing unfinished-form fencing](../../../DATABASE_SCHEMA.md#draft_leases--h03-reuse-existing-unfinished-form-fencing) | H03 | Owning slice delivers baseline, initializer, structural/retained validation and focused persistence proofs. |
| [`recovery_meta` — H05](../../../DATABASE_SCHEMA.md#recovery_meta--h05) | H05 | Owning slice delivers baseline, initializer, structural/retained validation and focused persistence proofs. |
| [`recovery_operations` — H05](../../../DATABASE_SCHEMA.md#recovery_operations--h05) | H05 | Owning slice delivers baseline, initializer, structural/retained validation and focused persistence proofs. |
| [`recovery_points` — H05](../../../DATABASE_SCHEMA.md#recovery_points--h05) | H05 | Owning slice delivers baseline, initializer, structural/retained validation and focused persistence proofs. |
| [`backup_state` — H05](../../../DATABASE_SCHEMA.md#backup_state--h05) | H05 | Owning slice delivers baseline, initializer, structural/retained validation and focused persistence proofs. |
| [`restore_operations` — H05](../../../DATABASE_SCHEMA.md#restore_operations--h05) | H05 | Owning slice delivers baseline, initializer, structural/retained validation and focused persistence proofs. |
| [`recovery_audit` — H05](../../../DATABASE_SCHEMA.md#recovery_audit--h05) | H05 | Owning slice delivers baseline, initializer, structural/retained validation and focused persistence proofs. |

## Command-family ownership checklist

Every Pilot 0 family in H01's contract table is covered below. H01.3/H01.4 implement
shared values/ports only; the delivery owner implements authorization, persistence,
receipts and usable workflow. All fresh-target commands remain **not delivered**.

| Command family and included Pilot 0 actions | Single owner | Dependencies / effect authority |
| --- | --- | --- |
| Admin assignment and provisioning: create assignment, start/inspect supported provision, optional seed, readiness/retry/original-result lookup | H04 | H02 agent/resources and releases; H03 exact identity. Immutable initial-data request; failed seed stays disabled, no seed-stage replay journal. |
| Admin account lifecycle: invitation reissue, desired disable/enable with fresh checks, explicit identity rebind, prepare/confirm retirement | H04 | H03 owns invitation/identity/source epoch and session revocation; H02 owns admitted resource cleanup. Unknown completion stays visible. |
| Admin operational reads: bounded list/detail, readiness/usage inspection and asynchronous source refresh | H04 | Set-based registry projections, never per-row synchronous source/provider calls; unknown is not zero. |
| Runtime repair, supported manual release/announced maintenance orchestration and original operation status | H04 | H02 performs fenced compatible runtime replacement without business initialization; H03 enforces access/drain. H05 alone authorizes subsequent restore. |
| Restricted host effects: reserve/prepare resources, initialize/start/stop container, inspect ownership/mount/image/ceilings, apply qualified limits and reconcile original effect | H02 | Protected resource/image IDs only; no arbitrary shell/path/tag input. H04 orchestrates but cannot mutate inventory directly. |
| Restricted restore/retirement host effects: stage/switch/retain registered targets, reviewed retirement cleanup | H02 | H05 owns restore authorization/phase semantics; H04 owns retirement intent. No agent-issued business restore grant. |
| Hosted source access: initialize disabled binding, inspect effective epoch/readiness, verified claim/enable, disable/revoke, maintenance fence/drain and original receipt | H03 | H04 supplies applied policy and readiness orchestration; source effective authority cannot be overwritten by stale Admin completion. |
| Hosted source accounting: inspect usage, reserve/reconcile bounded Free growth and publish safe observations | H04 | H02 physical limits; H03 source binding/epoch. Crash-safe logical ledger is new work. |
| Managed login: validate identity/invited assignment, consume invitation, issue/redeem single-use browser/origin-bound handoff, issue/revoke source session | H03 | Admin MFA/bootstrap and operator actors separate; hash capabilities, no token URLs/logs. |
| Operator recovery: own-point list, consequence preview, recent strong authentication, exact confirmation, admit/query original restore and verify source binding | H05 | H03 step-up proof/current source epoch; H02 registered destinations. Admin cannot approve/substitute own-workspace restore authority. |
| Workspace backup engine: schedule capture, encrypt/upload/readback, catalog/checkpoint, safe retention, authenticated separate-target restore and recovery mode | H05 | Independent of central Admin and business startup; access/recovery stores never rolled back with business history. |
| Admin backup/recovery: protect registry/inventory/config, confirm platform/control restore, catalog/checkpoint/status and original recovery operation/audit | H05 | Current protected bootstrap/MFA independent of main Admin DB; H02 exclusive host effects, H03 principal proof; no customer restore/decrypt bypass. |

All families share original identity/hash/revision/epoch fences and bounded
pending/running/needs_attention/unknown/succeeded/failed results. H01.3 owns common
value contracts; H01.4 assigns the typed ports. No timeout licenses a fresh effect.
Unsupported/private/unqualified operations remain unavailable, not placeholder routes.

## UI-state and action ownership checklist

These are delivery assignments, **not implemented screens or passing browser proofs**.
H01.6 will freeze synthetic fixtures; actual end-to-end acceptance stays with each owner.

| Surface / states / operator actions | Single owner | Dependencies and limits |
| --- | --- | --- |
| Admin sign-in/session: managed MFA, unauthenticated/denied/expired/revoked, explicit sign-in/continuation | H03 | Separate Admin principal and host-only session; local synthetic identity adapter must not enable production bypass. |
| Operator login/claim: invitation pending/consumed/invalid, exact identity, handoff replay/rejection, disabled/revoked/expired session, simultaneous devices | H03 | No second manual approval after verified eligible claim; fences preserve input and require explicit continuation, never automatic command replay. |
| Admin list: pending/readiness versus effective access, Free allowance/usage known/stale/unknown, release, operation state, independent loading/failure | H04 | H03 session; H02 readiness; H05 async backup age/protection. Bounded 50-row cursors/set-based reads, not health checkmarks for unavailable sources. |
| Add operator: name/email/slug/support, default Free/empty, qualified release and optional synthetic data, validation/conflict/unknown submission | H04 | H03 exact claim and H02 qualified capacity. Preserve values/focus/scroll; no expiry, read-only, paid checkout or idle-wake choices. |
| Admin detail: readiness/status lookup, supported retry, invitation reissue, enable/disable/rebind, retirement, maintenance and runtime repair | H04 | Confirmation and current fences; H02 effects, H03 identity. No Docker shell/path editor or recovery-authorization shortcut. |
| Operator Settings: Free pilot/50 MB usage/freshness, support and announced maintenance; independently failed/loading sections | H04 | Hide unavailable upgrades/scheduling/wake; source unknown usage cannot admit unlimited writes. |
| Operator protection, point selection, restore preview/recent-auth/confirmation/progress, minimal recovery mode and runtime-repair assistance | H05 | H03 current strong authority; no Admin approval or offline customer bypass. Unavailable evidence/runtime/auth keeps restore unavailable. |
| Admin protection projection, main-DB-independent recovery sign-in/preview/confirmation/progress and platform recovery status | H05 | H03 qualified current bootstrap/MFA; H04 hosts non-authoritative async summary. Restored principals/sessions are not recovery authority. |
| Cross-cutting async behavior: pending/running/needs-attention/unknown versus completed outcome, stale source, invalid retained input, section retry | H04 | H03 owns session/actor fencing; H05 owns recovery progress. Accessible keyboard/theme/narrow/focus/scroll acceptance per delivered surface. |

## Existing tests to replace or adapt

All paths in this table are beneath `application/`. Keep current tests operational
until the consuming implementation changes atomically. Replacement means new target
expectations, not deletion of security/rollback/query-budget invariants.

| Existing tests / fixtures | Owning change | Required treatment |
| --- | --- | --- |
| `apps/server/app/modules/hosted_access/tests/conftest.py`, `test_configuration.py`, `test_admin_lifecycle.py` | H03/H04 | Replace expiring `hosted_demo` deployment, manual activation/reenrollment and old capability assumptions; retain exact-origin, private-binding and fail-closed disable checks. |
| `.../hosted_access/tests/test_sessions.py`, `test_draft_leases.py` | H03 | Replace old table/revision/session/claim fixtures with owning resources; retain indexed read, hash-only secrets, atomic rollback, explicit takeover, stale revision, revocation and restart invariants. |
| `.../hosted_access/tests/test_identity.py`, `test_transport.py` | H03 | Cloudflare assertion/key-discovery and manual-enrollment expectations are old-provider contracts. New managed identity/handoff/MFA tests must retain origin/CSRF/cookie/role/cross-workspace denial, bounds and safe errors. |
| `.../hosted_access/tests/test_storage_budget.py`, `test_linux_storage_qualification.py`, `test_request_body.py` | H02/H04 | Fixed 250 MiB loop/statvfs and in-memory reservation assertions do not prove logical 50 MB accounting; replace owning policy/mechanism fixtures and add crash-safe proofs, retain bounded body/cleanup/error behavior. Native opt-in test is not run here. |
| `.../hosted_access/tests/test_composition.py`, `test_cli.py` | H02/H03/H04 | Adapt explicit hosted composition and launcher restrictions with their owning changes. Keep local mode independent, all business paths guarded, actor/recovery-lease fencing and unsupported Admin routes absent from Operator. |
| `.../hosted_access/tests/test_offline_backup.py`, `test_recovery_bundle.py`, `test_recovery_publication.py` | H05 | Legacy offline/R2/JSON-ledger contracts cannot qualify internal authenticated recovery. Replace target authority/catalog/engine tests; retain integrity, private binding, readback-before-prune and failure-preservation negative controls. |
| `apps/web/tests-hosted/session.spec.ts`, `read-only.spec.ts`, `scripts/hosted_browser_server.py` | H03/H04 | Replace Cloudflare approval, expiring demo and read-only pilot expectations; retain secure cookies/CSRF, session pause/no replay, input retention/takeover, cross-workspace denial and safe quota retry. Add real Admin-lite/Free UI tests; none run here. |
| `apps/server/app/modules/hosted_admin/tests/test_project_quota.py` | H02 | Retain imported primitive tests as limited regression inputs, not proof of containers/cloud/source policy. Requalify changed primitives and complete Docker/native/GCP boundary before activation. |

## Verification and handoff

From `application/`:

```bash
.venv/bin/python -m pytest apps/server/app/modules/hosted_access/tests/test_configuration.py apps/server/app/modules/hosted_access/tests/test_sessions.py apps/server/app/modules/hosted_access/tests/test_storage_budget.py apps/server/app/modules/hosted_access/tests/test_cli.py -q --tb=short
```

Result: **42 passed in 6.19s** on the development Mac. These are existing old-composition
regressions, not new hosted-MVP acceptance. No runtime source/config/schema changed.

| Validation area | H01.1 result and limit |
| --- | --- |
| Inventory / happy path | Every H01 current-code assessment rechecked; pinned inputs and accountable ownership recorded. |
| Invalid combinations / idempotency / rollback | Existing configuration/session/budget/launcher regressions passed; new action contracts and owning transaction proofs remain H01.3–H01.7/H02–H05. |
| Persistence/schema | All master table headings mapped exactly once; no column duplication, schema creation/stamping or local behavior change. Baseline blobs/hashes and quota import verified. |
| Backup/restore | Historical reports preserved byte-for-byte; new catalog/security/native/host-loss proofs not run or established. |
| Query budget | Existing session indexed-read assertion included; new Admin bounded/set-based list and source-refresh proofs not established. |
| UI | State/action delivery owners recorded; no UI source or browser run, no usable workflow claimed. |
| Lint / formatting | Python/frontend checks not applicable: documentation/JSON evidence only; `git diff --check` passed. |
| Evidence consistency | Passed: 78 baseline blob/SHA-256 pins, 13 unchanged quota-import inputs, 37 exact master-heading mappings and 68 relative links/anchors; proposed resources remain absent and application sources unchanged. |

Next: execute H01.2 resource scaffolding, then H01.3–H01.7 in order. This report does
not authorize schema rewiring, importing the older Admin stack, starting/modifying
the retained VM, provisioning cloud resources or enabling hosted admission/restore.
