# Easy Property Management

Easy Property Management is a local-first, AI-assisted property-management application planned for independent landlords and managers with roughly 1–50 rentable spaces. It will support self-owned and client-managed residential and office properties, with a future path to SaaS collaboration.

## Current status

This repository currently contains the agreed product, architecture, and delivery plan. Application implementation has not started.

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
