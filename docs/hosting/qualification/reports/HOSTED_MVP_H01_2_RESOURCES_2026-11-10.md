# H01.2 — Independent schema-resource scaffolding

Delivered November 10, 2026 on `hosted_mvp`, starting from clean commit
`9bf8c646ffd71a7cf706c33225aca5e768239762` (H01.1 delivered).
**Scaffolding and failure contracts only. No hosted schema or runtime is initialized.**

## Delivered resources and boundaries

The [resource guide](../../../../application/database/README.md) defines accountable
connection owners, revision namespaces, per-store configuration/runner handoff,
initialization outcomes and component packaging requirements. The master dictionary
remains the sole table/column design reference.

| Resource directory under `application/database/` | Namespace | Owning implementation |
| --- | --- | --- |
| `admin-migrations/` | `admin_` | H04 composes main Admin; H02 release/H03 identity contributions |
| `admin-recovery-migrations/` | `admin_recovery_` | H05 |
| `host-inventory-migrations/` | `host_inventory_` | H02 |
| `hosted-access-migrations/` | `access_` | H03, with H04 usage/policy contributions |
| `recovery-migrations/` | `recovery_` | H05 |

Each directory contains its own `alembic.ini`, unavailable `env.py`, README and
`versions/README.md`. No revision Python file exists: no empty baseline, revision
stamp, table definition, default database URL or implicit access grant is supplied.
Paths resolve relative to the installed configuration, not the shell directory.

[Shared discovery and safe failure](../../../../application/apps/server/app/platform/schema_resources.py)
returns one scaffold configuration, or `schema_resources_unavailable` for missing,
incomplete or mismatched resources. Unknown store IDs fail before dispatch. A
configuration object is not schema readiness. Each Alembic environment raises the
same typed unavailable error before SQL generation, engine/file creation or use of a
supplied connection. Even explicit stamp/ensure-version attempts cannot create a
version-only file. No production initializer, launcher or command is registered.

The guide distinguishes schema creation from protected identity/policy/release data
initialization. Future initializers must reject wrong-store/revision/structure and
partial initialization, return a read-only match only after full validation, preserve
failed state, and never invent operator/workspace identity or grant access. H01.2
cannot prove an actual matching store because no owning baseline exists yet.

Business resources, configuration, schema staging/installation scripts and current
hosted-access consumers are unchanged. No older Admin implementation is imported.
There is no DDL in the discovery module, cross-store ATTACH or alternate schema
creator. The inline hosted-access schema remains actively consumed until H03/H04
replace it atomically; unused superseded code is removed with its replacement, not
retained as compatibility scaffolding.

## Focused verification

From `application/`:

```bash
.venv/bin/python -m pytest apps/server/app/platform/tests/test_schema_resources.py -q --tb=short
```

**84 passed in 0.34s.** These prove unavailable-resource behavior, not real baseline
constraints, successful initialization, rollback after DDL or installed-wheel readiness.

```bash
.venv/bin/python -m pytest apps/server/app/modules/hosted_access/tests/test_configuration.py apps/server/app/modules/hosted_access/tests/test_cli.py -q --tb=short
```

**23 passed in 1.35s.** Existing configuration/launcher regression checks only; not
new hosted identity/container qualification. Total: **107 focused tests passed**.

```bash
.venv/bin/ruff check apps/server/app/platform/schema_resources.py apps/server/app/platform/tests/test_schema_resources.py database/admin-migrations/env.py database/admin-recovery-migrations/env.py database/host-inventory-migrations/env.py database/hosted-access-migrations/env.py database/recovery-migrations/env.py
.venv/bin/ruff format --check apps/server/app/platform/schema_resources.py apps/server/app/platform/tests/test_schema_resources.py database/admin-migrations/env.py database/admin-recovery-migrations/env.py database/host-inventory-migrations/env.py database/hosted-access-migrations/env.py database/recovery-migrations/env.py
```

Ruff check and format check passed for **all seven changed Python files**, using
`application/pyproject.toml`. Frontend checks are not applicable: no frontend changes.
Documentation links and `git diff --check` passed. No full suite, build, native quota
harness, VM, provider call, customer database or cloud deployment was used.

## Validation matrix and remaining handoff

| Area | Proven here | Still required |
| --- | --- | --- |
| Happy path | All five independent configurations discover correctly from another CWD; unique namespaces, empty revisions and no default URL. | H02–H05 real fresh schema/data initialization and readiness. |
| Invalid combinations | Missing sets/files/versions, malformed/mismatched/false-ready configuration, unknown store ID and business-resource fallback are rejected. | Owning exact schema/identity/permission/foreign-key checks and installed-component mismatch rejection. |
| Idempotency/retry | Repeated attempts preserve existing empty, foreign-store, version-only and interrupted destination bytes. | Actual already-matching read-only initializer and explicit protected data replay contracts. |
| Transaction rollback | Supplied connection receives no SQL, remains open and retains its active transaction when execution is rejected. | Owning baseline/commit failure and cleanup/partial-file rollback proofs. |
| Persistence/schema | Upgrade, stamp and ensure-version, online and offline, all fail before database creation or revision output. Business resources unchanged. | H02–H05 executable resources, resource-derived structural validators and full retained validation; no migration compatibility. |
| Backup/restore | No business/control store is opened or replaced by scaffolding. | H05 independent recovery initialization, authenticated restore and packaging/recovery proofs. |
| Query budget | Unavailable scaffold environment issues zero statements through a supplied connection. | Actual source indexed reads and bounded Admin/recovery queries in owning repositories. |
| Packaging | Component resource sets, paths, immutable manifests and missing-resource failure requirements documented. | H01.5 proof specifications; H02 real artifact staging/installation tests. Existing wheel is not qualified by these tests. |
| UI | No screen/control or production route is added or enabled. | H03/H04 usable identity/Admin-lite/Free Settings and H05 recovery UI. |

Next: H01.3 shared bounded values and operation envelopes. H01.3–H01.7 remain open.
H02–H05 must replace each unavailable environment with its complete owning runner,
baseline and validators; remove the corresponding scaffold-only code when unused.
All fresh-target runtime, native, cloud and end-user release gates remain unestablished.
