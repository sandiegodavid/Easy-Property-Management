# Easy Property Management

Easy Property Management is a local-first, AI-assisted property-management application for independent landlords and managers with roughly 1–50 rentable spaces. The MVP serves only the United States: property addresses and spaces are US-based, property-local dates use US IANA time zones, and monetary workflows use USD. Its implemented backend covers portfolio, people, leases, inspections, maintenance, money, communications, tasks, retained evidence and optional AI governance. Core browser workflows and live Home aggregation are delivered; follow-up integrations remain planned; [the documentation index](docs/README.md) distinguishes current behavior from remaining work.

## Operator manual

Start with the [operator manual](manual/README.md) for installation/setup, daily use, every current workflow, backup/restore and troubleshooting. It is organized by operator task; developer/build details remain in this README and `docs/`.

## Repository layout

```text
manual/         Operator installation, task guides, operation index and troubleshooting
docs/           Developer index, current module/platform guides, active work, research and archive
application/    FastAPI application, Alembic baseline, tests, and local configuration template
```

The implemented stack is React/Vite/TypeScript for the interface, with Python/FastAPI, SQLAlchemy, Alembic, SQLite, and a future PostgreSQL SaaS path. A new workspace is initialized from one current Alembic baseline; this greenfield build accepts only the latest workspace and archive formats. See [the architecture plan](docs/ARCHITECTURE.md) for modules, folder structure, AI boundaries, workspace design, and stack rationale.

## Developer reading path

Start with [docs/README.md](docs/README.md), then [architecture](docs/ARCHITECTURE.md) and the relevant module guide. Use [active designs](docs/active/README.md) and [the feature backlog](docs/FEATURE_BACKLOG.md) for remaining delivery. [The inventory](docs/DOCUMENT_INVENTORY.md) maps archived design sources to their current references.

## Local workspace configuration

Application code is Git-maintained, while live user data is stored outside this repository. The local configuration file points to that external workspace:

```text
application/config.local.json       # Git-ignored; live, machine-specific configuration
application/config.example.json     # Git-tracked template with a fake path
```

Set `localWorkspacePath` in the live file to the chosen external data folder. The live configuration file, SQLite database, attachments, backups, exports, and connection credentials must never be committed. The configuration template is safe to commit because it contains no live path or user data.

## Synthetic demo workspace

[application/demo](application/demo/README.md) contains a reproducible synthetic
portfolio, generator, verifier and browser launcher. It includes ten properties,
twenty providers and linked lease, deposit, finance and maintenance scenarios.
The generated database lives outside the repository; its demo configuration is
separate from the operator's live configuration.

## Application layout and delivery

`application/apps/server` contains the FastAPI modules, current schema validation and tests. `application/apps/web` contains React workflows; `packages/ui` supplies shared components and `packages/contracts` supplies generated API contracts. A new workspace uses one current greenfield baseline.

The current browser shell, workspace gate, recovery, contextual reads, Portfolio/identity/Provider, Lease/Inspection, Money, Maintenance/coordination, search/coverage, manual Intake, capability-gated AI controls and live Home workflows are delivered. Their recorded acceptance is in [browser validation](docs/ui/validation.md). The [visual demo](demo/operator-experience.html) includes design/future states and is not a capability inventory.

## Local HTTP transport

From `application/`, `python -m app serve` binds only to `127.0.0.1:8000`
(`--port` selects another port). Production browser requests must use the same
origin; null/foreign origins and non-loopback Host headers are rejected before
route handling. Development may explicitly opt into an exact loopback frontend
origin with `--development-origin http://localhost:5173` (repeatable). Do not use
this flag in production. Forwarded headers are not trusted.

CLI/setup HTTP mutations without an Origin header must include
`X-EPM-Local-Client: 1` and no browser Fetch Metadata/Referer headers. The marker
is public intent, not authentication, and never overrides an invalid Origin.
Ordinary CLI reads need no marker. Browser clients use relative API paths and
must not add it; cross-origin browser preflight cannot request this header.
Direct application CLI commands are unchanged. This device-local policy is not
stored in workspace backups and does not enable browser controls.

## Packaged web delivery

The server serves a trusted compiled build from `app/web_build` in the installed
Python package. When no compiled build is installed, eligible HTML routes return
503 `web_build_unavailable`; the API, bootstrap and documentation remain usable.
SPA fallback is restricted to registered UI-001 routes, canonical record IDs,
explicit child sections, GET/HEAD and a positive `text/html` Accept header.
Unknown API routes, missing assets and UI-002 routes never return the entry page.

`npm run package:web` builds React and stages the public Vite output into an
isolated Python build tree, then creates a wheel in `application/dist`. It rejects
unexpected files and symlinks. Only `index.html` and declared flat JS/CSS/image/font
assets ship; source maps, environment files and workspace content are excluded.
Packaging requires `uv` and cached Python build dependencies (`uv build --offline`).
Entry pages are not stored; hexadecimal fingerprint assets are immutable.
External scripts/styles and relative `/api` calls work under the production CSP.

Current frontend structure and shared-component behavior are documented in [frontend architecture](docs/ui/frontend-architecture.md). Run `npm run test:components` from `application/` for the isolated component fixture; it is excluded from the production build.

## Production build and packaging instructions

`app/web_build` is the **compiled React frontend inside the Python package**. Python code is packaged alongside it in the wheel; Python is not compiled into that directory. The packaging script uses a temporary staging tree, so a successful build does not create `application/apps/server/app/web_build` in the checkout.

For deploying an already built wheel to a clean VM, use the [VM deployment guide](manual/deployment.md). It includes the currently required matching schema-resource bundle and installed-resource checks.

### One-command wheel build

After installing the project Python dependencies, run from the repository root:

```bash
./application/scripts/build_wheel.sh --install-deps
```

Subsequent builds can omit `--install-deps` when Node dependencies are already installed. The script works from any directory, runs frontend lint/format/type checks and generated-contract validation, builds React, packages the combined wheel and verifies its Python entry point, public assets and archive integrity. Output is printed as an absolute path under `application/dist/`. It does not install the wheel, stage assets into the running checkout, or open an operator workspace.

Python discovery uses `EPM_PYTHON` when set, then `application/.venv/bin/python`, then `.venv/easy-property-management/bin/python`. Run `./application/scripts/build_wheel.sh --help` for prerequisites/options. The standalone wheel limitation and checkout asset-staging instructions below still apply.

### Build the combined Python/frontend wheel

Prerequisites: Python 3.12 or newer, Node.js 22.13 or newer with npm, and `uv` on PATH. Use a project Python environment with the backend dependencies installed. From the repository root:

```bash
cd application
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
export EPM_PYTHON="$PWD/.venv/bin/python"
npm ci
npm run check
npm run package:web
```

The explicit `EPM_PYTHON` selects this environment; without it, Node scripts default to the repository's `.venv/easy-property-management/bin/python`.

`package:web` checks generated contracts, builds Vite into `application/apps/web/dist`, validates the public assets, and packages them with the backend into `application/dist/easy_property_management-0.1.0-py3-none-any.whl` (the version comes from `application/pyproject.toml`). The wheel contains `app/web_build/index.html` and `app/web_build/assets/*` along with the Python modules. `npm run build` alone produces the frontend output and does not create the combined wheel.

The packager calls `uv build --offline`, so its isolated build dependency (`setuptools>=68`) must already be cached. If the offline build reports a missing build dependency, run `uv build --wheel` once from `application/` with network access, then rerun `npm run package:web`. That first wheel only primes the build cache; distribute the final wheel produced by `package:web`, which includes the frontend.

Inspect the final artifact without starting the app:

```bash
python -m zipfile -l dist/easy_property_management-0.1.0-py3-none-any.whl
```

Look for the `app/web_build/` entries. Adjust the filename if the project version changes. A backend-only build or editable Python install does not automatically include the Vite output.

### Run the production frontend with the current checkout

The current wheel is a combined backend/assets artifact, **not yet a standalone installer**. Workspace initialization/schema validation still locates `alembic.ini` and `database/sqlite-migrations` relative to the application checkout; the packager does not include them. Installing only the wheel into an unrelated environment therefore does not establish a working production workspace runtime.

For the currently supported checkout-based runtime, retain the checkout, its Python environment and external workspace. After the successful packaging command above, copy the validated frontend build into the source package's generated asset directory. From `application/`, with the project environment active:

```bash
python scripts/stage_frontend.py
python -m app --config "$PWD/config.local.json" workspace-status
python -m app --config "$PWD/config.local.json" serve --port 8000
```

Open **http://127.0.0.1:8000/home**. FastAPI serves the frontend and API on the same origin; Vite and Node are not required while serving. Configure `config.local.json` first; for a new workspace, explicitly run `initialize-workspace` as described below. Stop the server before replacing generated assets and restart after rebuilding. Re-run the copy step for each frontend release; do not commit generated `web_build` files or put workspace data there.

A clean wheel-only runtime needs a separate packaging change to include and locate its schema resources. The packaged-asset browser tests described above validate the frontend packaging boundary using the repository backend; they do not validate that missing standalone-install boundary.

## Frontend development checks

The React/Vite app, generated contracts and shared UI package use one npm workspace
and lockfile under `application/`. On a current Node.js LTS release, run:

```bash
cd application
npm ci
npm run contracts:check
npm run check
npm run build
```

`npm run check` checks actual handwritten sources and type-checks the generated
contract too. `npm run contracts:generate` replaces the committed OpenAPI snapshot
and generated types; `contracts:check` fails on any difference. Export uses an
isolated configuration, forbids SQLite connections and never opens the live
workspace. Scripts use the repository Python environment by default; set
`EPM_PYTHON` to another installed project interpreter when needed.

For development, start FastAPI on port 8000 with
`python -m app serve --development-origin http://127.0.0.1:5173`, then run
`npm run dev`. Vite binds to loopback port 5173 and proxies relative `/api` requests
without changing the browser origin. Development explicitly allows that origin;
production remains same-origin.

For the focused packaged-asset browser smoke test:

```bash
npx playwright install chromium
npm run package:web
npm run test:web
```

Playwright starts production FastAPI on ports 18744/18745 using disposable ready
and unavailable workspaces and the actual wheel's extracted assets. It checks
React execution, generated-client bootstrap, deep links, CSP, cache headers and
reserved API/missing-asset behavior. This proves the web asset packaging boundary
using the repository backend; full installed-runtime distribution and the later
domain/browser acceptance gates are separate. See
[implementation quality checks](docs/CODE_QUALITY.md) for check policies.

## Local workspace foundation

From `application/`, install the Python dependencies and explicitly initialize the configured workspace:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
python -m app initialize-workspace
python -m app workspace-status
```

The workspace command validates the Git-ignored `config.local.json`, rejects paths inside the application checkout, creates `workspace.json` and the initial SQLite identity store, and creates the `database/`, `files/`, `exports/`, and `backups/` directories. It does not overwrite a nonempty folder without a valid workspace manifest.

## Encrypted backup and restore

Choose a separate external destination before routine backups. Its filesystem must support atomic hard-link publication; configuration checks this and rejects unsupported destinations, including many FAT/exFAT removable drives. This preserves the guarantee that only complete encrypted archives appear in synchronized folders. The command saves only that location in the Git-ignored configuration; it never stores a backup passphrase there.

```bash
python -m app configure-backup-destination /absolute/path/to/encrypted-backups
python -m app backup
python -m app export /absolute/path/to/portable-export
python -m app validate-archive /absolute/path/to/archive.epm-backup
python -m app restore /absolute/path/to/archive.epm-backup /absolute/path/to/new-workspace
```

Each backup and export prompts for a passphrase of at least 12 characters, uses authenticated encryption, and is validated before it is published. Restore requires a new or empty external destination and never changes the configured live workspace. Automatic daily backups are optional: `python -m app enable-automatic-backups` stores the passphrase in the operating-system credential store only after the operator explicitly opts in.

## Optional S3 file storage

Install the optional S3 adapter from the `application` directory:

```bash
pip install -e '.[dev,s3]'
```

Local storage is the default. To make new uploads use S3, set `fileStorageProvider` to `"s3"` and provide `s3Bucket`; `s3Prefix` is optional. The bucket must have versioning enabled. The local application uses the host's normal AWS SDK credential-provider chain, so no AWS credential is saved in the workspace or configuration file.

Keep `s3Bucket` configured even if you later switch `fileStorageProvider` back to `"local"`: it keeps the S3 adapter available for existing S3-backed files and portable backups. Each S3 upload is version-pinned and verified before its metadata is recorded.
