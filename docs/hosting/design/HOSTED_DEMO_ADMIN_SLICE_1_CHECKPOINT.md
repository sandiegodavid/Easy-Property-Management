# Hosted Admin Slice 1 checkpoint

Updated October 27, 2026. Slice 1 repository implementation and focused validation are complete. Changes remain uncommitted on the current branch. No live host, service, Cloudflare, invitation or workspace was changed.

Use the [registered instance tooling runbook](../operations/HOSTED_INSTANCE_TOOLING.md) for the installation/adoption/maintenance procedure, boundaries and test matrix. The [Admin design](HOSTED_DEMO_ADMIN_DESIGN.md) retains the later authority, engine, UI, onboarding recovery and capacity qualification slices.

## Delivered repository boundaries

- Protected current-format SQLite inventory with stable instance/allocation identities, uniqueness, retained allocations, revisions, exact schema validation and append-only audit.
- Root-only bounded discovery and digest-bound adoption of effective configuration, release/tool digests, mount/image and source access bindings; explicit discrepancy reporting and protected configuration baselines. Recovery and historical acceptance remain unverified unless separately evidenced.
- Shared maintenance lock/journal and fixed installed-wizard dispatch; operation-bound lock validation, bounded status lookup, failure preservation, explicit resume, abandoned-holder reconciliation and recorded root-intervention reconciliation. No arbitrary exec/path override is exposed.
- Registered-instance selections throughout Mac/VM deployment, reset/rollback, cleanup and backup tooling. Temporary-root C uses its allocated nonstandard port and preserves A/B. Cleanup retains stopped-instance and baseline/rollback references.
- Recovery backup flow uses one operation output, private derived staging, explicit external archive revalidation, the existing encrypted reference and publication services, failure fencing, and explicit access restoration. Unsupported installed runtimes fail before fencing.
- Installation/transition instructions and focused validation matrix are linked from hosting operations and design documents.

## Validation

From `application/`:

```bash
PYTHONPATH=. .venv/bin/pytest scripts/tests/test_host_inventory.py scripts/tests/test_host_admin.py scripts/tests/test_release_wizards.py scripts/tests/test_release_cleanup.py scripts/tests/test_release_demo.py apps/server/app/modules/hosted_access/tests/test_cli.py -q
```

Result: **169 passed**. This includes the system-helper Python 3.12 syntax checks and shell syntax/help/guard coverage. Changed-file `ruff check`, `ruff format --check` (11 Python files) and `git diff --check` all passed. No full application suite or browser suite was run for this private tooling boundary.

Work was saved and stopped at the requested usage guard: five-hour remaining usage reached 3% (below the 5% stop threshold); weekly remaining usage was 18%.

## Deployment work remains separate

No tooling has been installed on the VM and no live A/B adoption is claimed. Before operational use, qualify sudo/runuser/lock-descriptor inheritance and interruption handling on Linux, adopt the observed A/B configuration, validate retained recovery/rollback points, and record exact installed digests and discrepancies. Keep the existing operator capacity ceiling and tunnel boot policy. C provisioning/invitations, the Admin browser/session/broker boundary and onboarding recovery evidence belong to the later slices.
