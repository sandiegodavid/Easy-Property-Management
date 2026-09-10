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
- [LOCAL-002 backup, export, and restore design](docs/LOCAL-002_DESIGN.md)
- [AUDIT-001 local audit ledger design](docs/AUDIT-001_DESIGN.md)
- [PORT-001 portfolio ownership-context design](docs/PORT-001_DESIGN.md)
- [LEASE-001 lease records and occupancy design](docs/LEASE-001_DESIGN.md)
- [INSP-001 move-in and move-out condition-report design](docs/INSP-001_DESIGN.md)
- [FIN-001 rent expectations and recorded-receipts design](docs/FIN-001_DESIGN.md)

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

The React interface and shared web packages are planned follow-on work. No UI development begins until `DASH-001`; before then, work is limited to backend capabilities, APIs, CLI/setup tooling, tests, and documentation. Follow the feature backlog sequence and preserve the local workspace, approval, audit, and migration requirements documented in `docs/`.

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
