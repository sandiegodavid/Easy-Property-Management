# Easy Property Management

Easy Property Management is a local-first, AI-assisted property-management application planned for independent landlords and managers with roughly 1–50 rentable spaces. It will support self-owned and client-managed residential and office properties, with a future path to SaaS collaboration.

## Current status

`LOCAL-001` is implemented. `LOCAL-002` is in progress: its encrypted local backup, export, validation, and restore foundation is available while the remaining acceptance work is tracked in the feature backlog.

## Repository layout

```text
docs/           Product brief, decisions, backlog, roadmap, and architecture
application/    Reserved source-code root and local configuration template
```

The planned stack is React/Vite/TypeScript for the interface, with Python/FastAPI, SQLAlchemy, Alembic, SQLite, and a future PostgreSQL SaaS path. See [the architecture plan](docs/ARCHITECTURE.md) for modules, folder structure, AI boundaries, workspace design, and stack rationale.

## Planning documents

- [Product brief](docs/PRODUCT_BRIEF.md)
- [Feature backlog](docs/FEATURE_BACKLOG.md)
- [Product roadmap](docs/ROADMAP.md)
- [Product decisions](docs/DECISIONS.md)
- [Architecture and technology plan](docs/ARCHITECTURE.md)
- [LOCAL-002 backup, export, and restore design](docs/LOCAL-002_DESIGN.md)
- [AUDIT-001 local audit ledger design](docs/AUDIT-001_DESIGN.md)

## Local workspace configuration

Application code is Git-maintained, while live user data is stored outside this repository. The local configuration file points to that external workspace:

```text
application/config.local.json       # Git-ignored; live, machine-specific configuration
application/config.example.json     # Git-tracked template with a fake path
```

Set `localWorkspacePath` in the live file to the chosen external data folder. The live configuration file, SQLite database, attachments, backups, exports, and connection credentials must never be committed. The configuration template is safe to commit because it contains no live path or user data.

## Implementation starting point

When implementation begins, work starts in [application](application) using the existing skeleton:

- `apps/web` — React interface
- `apps/server` — FastAPI application
- `packages` — API contracts, reusable UI, and test support
- `database` — SQLite and future PostgreSQL migrations
- `scripts` — operator setup, backup, restore, and health checks

Follow the feature backlog sequence and preserve the local workspace, approval, audit, and migration requirements documented in `docs/`.

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

Choose a separate external destination before routine backups. The command saves only that location in the Git-ignored configuration; it never stores a backup passphrase there.

```bash
python -m app configure-backup-destination /absolute/path/to/encrypted-backups
python -m app backup
python -m app export /absolute/path/to/portable-export
python -m app validate-archive /absolute/path/to/archive.epm-backup
python -m app restore /absolute/path/to/archive.epm-backup /absolute/path/to/new-workspace
```

Each backup and export prompts for a passphrase of at least 12 characters, uses authenticated encryption, and is validated before it is published. Restore requires a new or empty external destination and never changes the configured live workspace. Automatic daily backups are optional: `python -m app enable-automatic-backups` stores the passphrase in the operating-system credential store only after the operator explicitly opts in.
