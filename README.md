# Easy Property Management

Easy Property Management is a local-first, AI-assisted application for independent landlords and managers with roughly 1–50 rentable spaces. The MVP supports US properties, property-local dates in US IANA time zones, and USD monetary workflows.

Delivered workflows cover portfolio and people, leases and inspections, maintenance, money, communications, Tasks, retained evidence, and live Home aggregation. Optional AI governance is implemented; available AI actions depend on registered capabilities. See the [feature backlog](docs/FEATURE_BACKLOG.md) for delivery status and planned integrations.

## Start here

| Your goal | Read |
| --- | --- |
| Install or use the application | [Operator manual](manual/README.md) |
| Deploy an existing release to a new VM | [VM deployment guide](manual/deployment.md) |
| Develop or build from this checkout | Continue below, then use the [developer documentation](docs/README.md) |
| Explore synthetic data | [Demo workspace](application/demo/README.md) |

The application uses React, Vite and TypeScript in the browser, with Python, FastAPI, SQLAlchemy, Alembic and SQLite on the server. [Architecture](docs/ARCHITECTURE.md) describes module boundaries, the local workspace, AI governance and the future PostgreSQL SaaS path.

## Repository layout

```text
manual/                         Operator setup, task guides and troubleshooting
docs/                           Architecture, module guides, active work and archives
application/
  apps/server/                  FastAPI modules and backend tests
  apps/web/                     React workflows and browser tests
  packages/                     Shared UI, generated API contracts and test support
  database/sqlite-migrations/   Current greenfield schema baseline
  scripts/                      Development, build and deployment helpers
  demo/                         Synthetic portfolio and demo tooling
```

Current behavior is documented in the [module and UI guides](docs/README.md#current-modules). [Active designs](docs/active/README.md) describe remaining work; the [document inventory](docs/DOCUMENT_INVENTORY.md) maps historical designs to current references. The [visual demo](demo/operator-experience.html) includes proposed states and is not a capability inventory.

## Prepare a development checkout

Prerequisites: Python 3.12 or newer, Node.js 22.13 or newer with npm, and `uv` on PATH for wheel packaging. From the repository root:

```bash
cd application
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
export EPM_PYTHON="$PWD/.venv/bin/python"
npm ci
```

Keep this Python environment active for the commands below. `EPM_PYTHON` selects the interpreter for Node tooling; otherwise it prefers `application/.venv/bin/python`, then falls back to the repository's `.venv/easy-property-management/bin/python`. Generate and check contracts with the same environment: differing FastAPI/Pydantic versions can produce different OpenAPI snapshots.

<a id="local-workspace-foundation"></a>

### Configure and initialize a workspace

Application code lives in Git; live user data belongs in an external workspace. Copy the configuration template and edit its paths:

```bash
cp -n config.example.json config.local.json
```

Set `localWorkspacePath` to the chosen external data directory and `backupDestinationPath` to a separate supported backup destination. `config.local.json` is Git-ignored and machine-specific; `config.example.json` is a tracked template containing fake paths.

For a **new workspace**, explicitly initialize it:

```bash
python -m app initialize-workspace
python -m app workspace-status
```

Initialization creates `workspace.json` and the `database/`, `files/`, `exports/` and `backups/` directories using the current Alembic baseline. It rejects paths inside the checkout and does not overwrite a nonempty folder without a valid manifest. This greenfield build accepts only the latest workspace and archive formats. For existing records, follow the [restore procedure](manual/data-and-recovery.md#restore-a-backup) instead of initializing over them.

Never commit live configuration, databases, attachments, backups, exports or credentials. The [synthetic demo](application/demo/README.md) uses separate configuration and generates its data outside the repository.

### Run with Vite during development

From `application/`, start FastAPI:

```bash
python -m app serve --development-origin http://127.0.0.1:5173
```

In another terminal, run `npm run dev` from `application/` and open **http://127.0.0.1:5173/home**. Vite binds to loopback and proxies relative `/api` requests to FastAPI on port 8000. The explicit development origin is for this setup only.

## Production build and packaging instructions

The release wheel combines Python modules with the compiled React frontend under `app/web_build`. The build uses a temporary staging tree; it does not place frontend assets into the running checkout or open an operator workspace.

**The wheel alone is not a standalone installer.** Workspace initialization and validation also require matching `alembic.ini` and `database/sqlite-migrations` resources, which the wheel currently omits. Use the checkout-based run instructions below, or follow the [VM deployment guide](manual/deployment.md) to install a wheel with its matching schema-resource bundle.

### Build the combined wheel

After preparing the Python environment above, run from the repository root:

```bash
./application/scripts/build_wheel.sh --install-deps
```

Omit `--install-deps` for subsequent builds when npm dependencies are already installed. The script works from any directory, runs frontend lint/format/type and generated-contract checks, builds React, packages the wheel, and verifies its entry point, public assets and archive integrity. It prints the artifact's absolute path under `application/dist/`.

Interpreter discovery uses `EPM_PYTHON`, then `application/.venv/bin/python`, then the repository's `.venv/easy-property-management/bin/python`. Run `./application/scripts/build_wheel.sh --help` for options.

For the equivalent manual build, run from `application/` with dependencies installed:

```bash
npm run check
npm run package:web
```

`package:web` validates generated contracts, builds Vite into `apps/web/dist`, and packages the approved assets with Python. Only `index.html` and declared JS/CSS/image/font assets ship; source maps, environment files, symlinks and workspace content are excluded. `npm run build` alone builds the frontend without creating a wheel.

Packaging uses `uv build --offline`, so `setuptools>=68` must be cached. If the build reports an uncached dependency, run `uv build --wheel` once from `application/` with network access, then rerun the combined build. Distribute the final wheel from the combined build.

To inspect it without starting the application:

```bash
python -m zipfile -l dist/easy_property_management-0.1.0-py3-none-any.whl
```

The filename follows the version in `application/pyproject.toml`. Check for `app/web_build/index.html` and `app/web_build/assets/`; an editable Python install does not automatically include them.

### Run compiled assets from the checkout

After building, stop any running server and stage the validated frontend. From `application/`, with the configured project environment active:

```bash
python scripts/stage_frontend.py
python -m app --config "$PWD/config.local.json" workspace-status
python -m app --config "$PWD/config.local.json" serve --port 8000
```

Open **http://127.0.0.1:8000/home**. FastAPI serves the UI and API together; Node and Vite are not needed while serving. Restage assets and restart after each frontend release. Generated `web_build` files remain outside Git.

Without an installed compiled build, eligible HTML routes return `503 web_build_unavailable`; API routes and documentation remain available. SPA fallback accepts only registered routes and GET/HEAD requests accepting HTML. Unknown API routes and missing assets do not return the entry page. See [frontend architecture](docs/ui/frontend-architecture.md) for delivery, caching and CSP details.

## Validation and tests

Run checks from `application/`:

```bash
npm run check
npm run contracts:check
```

`check` runs lint, formatting and complete frontend type checking, including generated contracts. `contracts:generate` updates the committed OpenAPI snapshot and TypeScript types; `contracts:check` verifies reproducibility without opening a workspace or connecting to SQLite.

Run focused tests for the changed workflow. For example:

```bash
python -m pytest apps/server/app/modules/tasks/tests/test_tasks.py
npm run test:components
npm run test:recovery
npx playwright install chromium
npm run package:web
npm run test:web -- apps/web/tests/home-layout.spec.ts
```

Packaged browser tests start local FastAPI servers on ports 18744/18745 with disposable workspaces and the wheel's extracted assets. `npm run test:web` without a selector runs all browser suites. See [code-quality requirements](docs/CODE_QUALITY.md) for Python Ruff checks and [browser validation](docs/ui/validation.md) for recorded acceptance evidence.

### Demo end-to-end tests (Playwright)

The seeded demo workspace has its own read-only Playwright suite covering the main workspaces (properties, owners, tenants, leasing, money, maintenance, providers, home) against a locally served demo server on `http://127.0.0.1:8001`. The suite never submits workflows, so seeded records stay intact for `demo/verify.py`.

Run from `application/` after seeding and serving the demo workspace:

```bash
export EPM_PYTHON="$PWD/.venv/bin/python"
.venv/bin/python demo/seed.py --workspace "$HOME/Desktop/Property-Management-Data/synthetic-demo"
.venv/bin/python demo/serve.py
npm run test:demo
```

See [demo Playwright tests](application/apps/web/tests-demo/README.md) for prerequisites, the full suite list, and conventions.

## Local HTTP transport

`python -m app serve` binds only to `127.0.0.1:8000`; `--port` selects another port. Production browser requests use the same origin. Null/foreign origins and non-loopback Host headers are rejected before route handling; forwarded headers are not trusted. Development can explicitly allow an exact loopback frontend origin with the repeatable `--development-origin` flag.

CLI HTTP mutations without an Origin header require `X-EPM-Local-Client: 1` and no browser Fetch Metadata/Referer headers. This public intent marker is not authentication and cannot override an invalid Origin. Browser clients use relative API paths without the marker; ordinary CLI reads need none. Direct application CLI commands are unaffected. See [local transport and security](docs/platform/security-and-audit.md) for the full contract.

## Backups and optional remote storage

### Encrypted backup and restore

From `application/`, with the configured environment active:

```bash
python -m app configure-backup-destination /absolute/path/to/encrypted-backups
python -m app backup
python -m app export /absolute/path/to/portable-export
python -m app validate-archive /absolute/path/to/archive.epm-backup
python -m app restore /absolute/path/to/archive.epm-backup /absolute/path/to/new-workspace
```

Backup destinations must support atomic hard-link publication; unsupported destinations, including many FAT/exFAT volumes, are rejected. Backups and exports prompt for a passphrase of at least 12 characters, use authenticated encryption, and are validated before publication. Restore requires a new or empty external destination and leaves the configured live workspace unchanged.

Optional automatic daily backups are enabled with `python -m app enable-automatic-backups`; after explicit opt-in, the passphrase is stored in the operating-system credential store. Detailed backup, restore and relocation steps belong to [data protection and recovery](manual/data-and-recovery.md).

### Optional S3 file storage

Install the optional adapter from `application/`:

```bash
python -m pip install -e '.[dev,s3]'
```

Local file storage is the default. To send new uploads to S3, set `fileStorageProvider` to `"s3"`, provide `s3Bucket`, and optionally set `s3Prefix`. Bucket versioning is required; each upload is version-pinned and verified before its metadata is recorded. Credentials come from the host's normal AWS SDK credential-provider chain, not workspace data or configuration.

Keep `s3Bucket` configured after switching new uploads back to `"local"` so retained S3 files remain accessible for retrieval and portable backups. See the [Files guide](docs/modules/files.md) for integrity and verification behavior.
