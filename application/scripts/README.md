# Application scripts

Index of executable scripts and script helpers in this directory. Run examples
from **`application/`**, unless noted otherwise. Prefer the npm entry points when
available. Generated command lists and other non-script files are omitted.

For the complete setup workflow, use the [installation manual](../../manual/installation.md)
or [wheel deployment manual](../../manual/deployment.md). For application behavior,
use the [operator manual](../../manual/README.md) and [module guides](../../docs/README.md#current-modules).

## Environment

- Prepare the project Python environment and Node dependencies first. These scripts
  do not install backend dependencies automatically.
- Frontend tooling requires Node.js **22.13 or newer** with npm. Wheel packaging
  also requires `uv` on PATH and cached Python build requirements.
- `python.mjs`, `generate-contracts.mjs` and `build_wheel.sh` select Python from
  `EPM_PYTHON`, then `application/.venv/bin/python`, then the repository's
  `.venv/easy-property-management/bin/python`. Use an absolute path for `EPM_PYTHON`.
- For installed-wheel helpers, use the **installed release's interpreter**, not
  the checkout Python launcher. Replace `/absolute/path/...` examples with actual
  paths; keep workspaces and recovery archives outside the checkout.

## Build and frontend delivery

### `build_wheel.sh`

[Source](build_wheel.sh). Runs frontend lint/format/type and contract checks,
builds the frontend, packages Python and public assets, and verifies the resulting
wheel in `dist/`.

```bash
bash scripts/build_wheel.sh
bash scripts/build_wheel.sh --install-deps
bash scripts/build_wheel.sh --help
```

`--install-deps` runs `npm ci` first. The script locates `application/` itself and
can be called from the repository root as `bash application/scripts/build_wheel.sh`.
Packaging uses `uv --offline`; the build cache must be prepared. A deployment also
needs [matching schema resources](../../manual/deployment.md#release-contents-required-before-deployment).

### `package_web.py`

[Source](package_web.py). Packages an existing `apps/web/dist` build with the
backend in a temporary source tree, writing the wheel to `dist/`. It validates
public asset types and rejects symlinks/unexpected files; tests are excluded.

```bash
npm run package:web
# Packaging only, after npm run build:
node scripts/python.mjs scripts/package_web.py
```

The npm command builds first. The Python script only packages; it does not install
the wheel, stage checkout assets or initialize a workspace.

### `stage_frontend.py`

[Source](stage_frontend.py). Replaces generated `apps/server/app/web_build` with
validated assets from `apps/web/dist`, preparing the replacement before switching.
Stop the checkout server first.

```bash
npm run build
node scripts/python.mjs scripts/stage_frontend.py
```

Use this for [checkout-based serving](../../manual/installation.md), not release installation.

## Installation and workspace selection

### Google Cloud ongoing-release wizards

From the repository root on the Mac, run
`bash application/scripts/epm-release-mac.sh`. It builds/checksums the release and
uploads it plus a standalone VM wizard through IAP, then prints the exact VM command.
On the VM choose `install`, then `deploy` A, then `deploy` B after acceptance.
The VM wizard also supports `inspect`, `resume` and explicit `rollback`.

Sources: [Mac](epm-release-mac.sh), [VM](epm-release-vm.sh).
Use the [ongoing runbook](../../docs/hosting/operations/GOOGLE_CLOUD_ONGOING_RUNBOOK.md#interactive-wizards-recommended)
for prerequisites, saved selections, safeguards and recovery limitations. Both scripts
accept `--help`. Do not run them through a pipe or run the VM wizard as root.

### `stage_schema_resources.py`

[Source](stage_schema_resources.py). Stages a matching release's `alembic.ini` and
complete `database/sqlite-migrations` tree beside the installed application.

```bash
/absolute/path/to/release/venv/bin/python scripts/stage_schema_resources.py \
  /absolute/path/to/release/schema-resources
```

Requires the application inside a dedicated virtual environment. Rejects symlinks
and existing resource destinations; use a fresh environment for a new release.
See [wheel deployment](../../manual/deployment.md).

### `verify_installation.py`

[Source](verify_installation.py). Verifies installed frontend assets and schema
discovery, then prints package version, module location and schema revision.

```bash
/absolute/path/to/release/venv/bin/python scripts/verify_installation.py
```

Run after installation and schema staging. It does not open a workspace or replace
browser, retained-data or restore acceptance. See the [Workspace guide](../../docs/modules/workspace.md).

### `configure_workspace.py`

[Source](configure_workspace.py). Creates a private locator with `localWorkspacePath`
and `fileStorageProvider: local`. Requires absolute paths and refuses to overwrite
an existing locator; missing configuration parent directories are created privately.

```bash
python scripts/configure_workspace.py \
  --config /absolute/path/to/config.json \
  --workspace /absolute/path/to/workspace
```

It does not initialize or restore data. Follow with the appropriate application
`workspace-status`, `initialize-workspace` or `restore` command. See
[data and recovery](../../manual/data-and-recovery.md) and [Workspace](../../docs/modules/workspace.md).

## Contracts and type checking

### `generate-contracts.mjs`

[Source](generate-contracts.mjs). Generates the composed OpenAPI snapshot,
TypeScript API types, browser workflow definitions and dispatch adapter.

```bash
npm run contracts:generate
npm run contracts:check
```

Writes `packages/contracts/openapi.json` and the generated `schema.ts`,
`workflows.json` and `workflow-dispatch.ts` under `packages/contracts/src/generated/`.
`--check` (the second npm command) compares existing files without rewriting them;
missing/stale output fails. Generation does not initialize a workspace or open SQLite.

### `export_openapi.py`

[Source](export_openapi.py). Prints sorted OpenAPI JSON to stdout and checks unique
operation IDs. A temporary locator and connection guard prevent workspace creation
or SQLite access. Normally called by the contract generator.

```bash
node scripts/python.mjs scripts/export_openapi.py
```

Redirect stdout to a chosen file if needed. See the [Operator contract](../../docs/modules/operator.md)
for browser-command/recovery composition.

### `workflow-contracts.mjs`

[Source](workflow-contracts.mjs). **Imported helper; no standalone CLI.** Exports
`workflowDefinitions`, `workflowContracts(openapi)` and `workflowDispatch(openapi)`.
It derives forms and dispatch source from OpenAPI, validates registered recovery
contracts and adapts browser-facing fields. It does not write files itself.

After changing its allowlist or mappings, run **`npm run contracts:generate`**.
Check the [Operator guide](../../docs/modules/operator.md) and the owning
[module contract](../../docs/README.md#current-modules) when adding workflows.

### `typecheck.mjs`

[Source](typecheck.mjs). Checks the complete frontend project configured by
`tsconfig.json`, including generated contracts, using the TypeScript compiler API.
Reports diagnostics without emitting build files; an empty source set fails.

```bash
npm run typecheck
```

## Browser acceptance and fixtures

The fixture servers below contain synthetic identities, clocks or test-control
routes. Use disposable data only; **never deploy them as product servers**.
Tests using packaged assets require the current combined wheel:

```bash
npm run package:web
```

### `web_acceptance.mjs`

[Source](web_acceptance.mjs). Runs Playwright web acceptance, stopping on failure.
Without arguments, sorted web spec files run in separate Playwright invocations,
giving unrelated suites fresh disposable server/workspace state. With arguments,
the entire selection is forwarded to one invocation.

```bash
npm run test:web -- apps/web/tests/work.spec.ts
npm run test:web -- apps/web/tests/work.spec.ts --grep "Task creation"
# All web acceptance suites:
npm run test:web
```

Prefer focused suites during development. Separate component, hosted, recovery and
demo configurations are not included. See [web configuration](../playwright.config.ts).

### `create_web_test_command_list.sh`

[Source](create_web_test_command_list.sh). Writes a sorted command per web spec,
then component, recovery and demo test commands. Commands are chained with `&&`
and line continuations; the generated list does not include hosted tests.

```bash
bash scripts/create_web_test_command_list.sh /absolute/path/to/new-command-list.txt
bash scripts/create_web_test_command_list.sh --help
```

The output parent must exist and the file must not exist. This only writes the
list; it does not run tests. Run copied commands from `application/`. Hosted
acceptance is separately available through `npm run test:hosted`.

### `web_smoke_server.py`

[Source](web_smoke_server.py). Serves the checkout backend and the current wheel's
exact frontend assets over loopback HTTP. Asset bytes must match `apps/web/dist`.
Includes test-only lease-clock and historical-owner fixtures.

```bash
node scripts/python.mjs scripts/web_smoke_server.py --port 18744 --state ready
node scripts/python.mjs scripts/web_smoke_server.py --port 18745 --state unavailable
# Keep fixture state in an existing disposable directory:
node scripts/python.mjs scripts/web_smoke_server.py \
  --port 18744 --state ready --directory /absolute/path/to/disposable-fixture
```

Without `--directory`, a temporary fixture is cleaned on exit. With it, an existing
`config.json` is reused and fixture state remains. Never select operator data.
Normally started by [web](../playwright.config.ts) or [recovery](../playwright.recovery.config.ts)
Playwright configuration.

### `hosted_browser_server.py`

[Source](hosted_browser_server.py). Disposable loopback HTTPS harness with packaged
assets, test TLS, synthetic RSA proofs, real app sessions/CSRF/enrollment and domain
handlers. Configuration loading, remote keys, clocks and physical storage facts
are test-controlled; this does not qualify real Cloudflare or Linux quotas.

```bash
npm run test:hosted
# Manual harness, normally started by Playwright:
node scripts/python.mjs scripts/hosted_browser_server.py --port 18748
node scripts/python.mjs scripts/hosted_browser_server.py --port 18749 --read-only
```

`--read-only` removes write capabilities. Each process cleans its temporary fixture
on exit. The test origin is `https://demo.epm.test`; [hosted configuration](../playwright.hosted.config.ts)
provides browser routing/TLS setup. The harness and `/__test__/` routes are test-only.

### `web_acceptance_restore.py`

[Source](web_acceptance_restore.py). Backs up an existing browser fixture with the
production encrypted archive service, restores into a new `restored` destination,
and rewrites the fixture locator to select it.

```bash
node scripts/python.mjs scripts/web_acceptance_restore.py \
  /absolute/path/to/disposable-fixture
```

Requires an initialized fixture with `config.json`. Stop its server first. It writes
an archive and restored data and changes the locator. Use a fresh disposable
fixture to avoid existing-destination collisions; its fixed passphrase is test-only.
See [restart/restore tests](../apps/web/tests/restart-restore.spec.ts),
[Workspace](../../docs/modules/workspace.md) and [Audit](../../docs/modules/audit.md).

## Shared Python launcher

### `python.mjs`

[Source](python.mjs). Forwards arguments and exit status to the selected project
Python, setting the working directory to `application/` and `PYTHONPATH` to
`apps/server`. Use it for checkout tooling that imports `app`.

```bash
node scripts/python.mjs scripts/export_openapi.py
```

Use the release interpreter directly for installed-wheel staging/verification.
