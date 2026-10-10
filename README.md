# Easy Property Management

Easy Property Management is a local-first, AI-assisted property-management application for independent landlords and managers with roughly 1–50 rentable spaces. The MVP serves only the United States: property addresses and spaces are US-based, property-local dates use US IANA time zones, and monetary workflows use USD. Its implemented foundation supports a private local workspace, encrypted backup/restore, append-only audit history, managed files, and tasks/reminders; property-management workflows build on this foundation.

## Repository layout

```text
docs/           Product brief, decisions, backlog, roadmap, and architecture
application/    FastAPI application, Alembic baseline, tests, and local configuration template
```

The planned stack is React/Vite/TypeScript for the interface, with Python/FastAPI, SQLAlchemy, Alembic, SQLite, and a future PostgreSQL SaaS path. A new workspace is initialized from one current Alembic baseline; this greenfield build accepts only the latest workspace and archive formats. See [the architecture plan](docs/ARCHITECTURE.md) for modules, folder structure, AI boundaries, workspace design, and stack rationale.

## Planning documents

- [Product brief](docs/PRODUCT_BRIEF.md)
- [Feature backlog](docs/FEATURE_BACKLOG.md)
- [Product roadmap](docs/ROADMAP.md)
- [Product decisions](docs/DECISIONS.md)
- [Architecture and technology plan](docs/ARCHITECTURE.md)
- [Confirmed operator experience and acceptance scenarios](docs/UI-001_DESIGN.md)
- [Implementation quality checks](docs/CODE_QUALITY.md)

## Local workspace configuration

Application code is Git-maintained, while live user data is stored outside this repository. The local configuration file points to that external workspace:

```text
application/config.local.json       # Git-ignored; live, machine-specific configuration
application/config.example.json     # Git-tracked template with a fake path
```

Set `localWorkspacePath` in the live file to the chosen external data folder. The live configuration file, SQLite database, attachments, backups, exports, and connection credentials must never be committed. The configuration template is safe to commit because it contains no live path or user data.

## Implemented foundation

[application](application) contains the implemented local backend and schema baseline:

- `apps/server` — FastAPI application, feature modules, API routes, and tests
- `database` — current SQLite Alembic baseline and future migration location
- `config.example.json` — safe, Git-tracked local-workspace configuration template

The React interface and shared web packages are planned follow-on work. `UI-001`, immediately before `DASH-001`, delivers the deferred operator workflows; before then, work is limited to backend capabilities, APIs, CLI/setup tooling, tests, and documentation. Follow the feature backlog sequence and preserve the local workspace, approval, audit, and migration requirements documented in `docs/`.

The confirmed UI design includes configurable Owners and Providers destinations, Light/Dark appearance, full-summary-bar inline expansion, manual legal matters, HOA violation notices, and reviewed Excel/read-only Google Sheets intake for properties, owners, and providers. The backlog names their supporting prerequisites; design approval does not indicate those new capabilities are implemented. Broader HOA administration and historical/update imports remain post-MVP.

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
Python package. Until the React/Vite build exists, eligible HTML routes return
503 `web_build_unavailable`; the API, bootstrap and documentation remain usable.
SPA fallback is restricted to registered UI-001 routes, canonical record IDs,
explicit child sections, GET/HEAD and a positive `text/html` Accept header.
Unknown API routes, missing assets and UI-002 routes never return the entry page.

For future packaging, stage the Vite `index.html` and flat public `assets/` output
under `application/apps/server/app/web_build` before building the wheel. Package
data includes only declared JS/CSS/image/font extensions; do not stage workspace
files, credentials, environment files or source maps. The build must use relative
same-origin API paths, external scripts/styles and the restrictive production CSP
(no inline/eval scripts or styles). Entry pages are not stored; fingerprinted
hex-name assets are immutable and other assets revalidate. Actual Vite and
packaged-browser verification remain follow-up UI acceptance work; fixture wheel
tests do not claim a delivered frontend.

## Frontend development checks

The frontend lint/format/type-check tooling is configured under `application/`. React interface implementation remains deferred until UI-001. On a current Node.js LTS release, run:

```bash
cd application
npm ci
npm run check
```

The combined check runs ESLint, Prettier, and strict TypeScript validation. Before TypeScript sources exist, type checking explicitly reports a skip; that does not validate a frontend feature. See [implementation quality checks](docs/CODE_QUALITY.md) for source scopes and generated-contract handling.

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
