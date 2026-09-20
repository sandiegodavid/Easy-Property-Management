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

## Backlog item designs (in sequence order)

### MVP — Local single-user

| Seq | ID | Area | Design | Status |
|-----|-----|------|--------|--------|
| 1 | LOCAL-001 | Local data | — | ✅ Done |
| 2 | LOCAL-002 | Local data | [LOCAL-002_DESIGN.md](docs/LOCAL-002_DESIGN.md) | ✅ Done |
| 3 | AUDIT-001 | Audit | [AUDIT-001_DESIGN.md](docs/AUDIT-001_DESIGN.md) | ✅ Done |
| 4 | FILE-001 | Files | [FILE-001_DESIGN.md](docs/FILE-001_DESIGN.md) and [FILE-001_MIGRATION_AND_ADAPTER_DESIGN.md](docs/FILE-001_MIGRATION_AND_ADAPTER_DESIGN.md) | ✅ Done |
| 5 | TASK-001 | Tasks | [TASK-001_DESIGN.md](docs/TASK-001_DESIGN.md) | ✅ Done |
| 6 | PORT-001 | Portfolio | [PORT-001_DESIGN.md](docs/PORT-001_DESIGN.md) | ✅ Done |
| 7 | PORT-002 | Inventory | [PORT-002_DESIGN.md](docs/PORT-002_DESIGN.md) | ✅ Done |
| 8 | PORT-003 | Inventory | [PORT-003_DESIGN.md](docs/PORT-003_DESIGN.md) | 🟡 In progress — pending UI |
| 9 | TEN-001 | People | [TEN-001_DESIGN.md](docs/TEN-001_DESIGN.md) | ✅ Done |
| 10 | LEASE-001 | Leases | [LEASE-001_DESIGN.md](docs/LEASE-001_DESIGN.md) | 🟡 In progress — pending UI |
| 11 | INSP-001 | Inspections | [INSP-001_DESIGN.md](docs/INSP-001_DESIGN.md) | 🟡 In progress — pending UI |
| 12 | VEND-001 | Providers | [VEND-001_DESIGN.md](docs/VEND-001_DESIGN.md) | 🟡 In progress — pending UI |
| 13 | VEND-002 | Providers | [VEND-002_DESIGN.md](docs/VEND-002_DESIGN.md) | 🟡 In progress — pending UI |
| 14 | FIN-001 | Money | [FIN-001_DESIGN.md](docs/FIN-001_DESIGN.md) | 🟡 In progress — pending UI |
| 15 | FIN-002 | Money | [FIN-002_DESIGN.md](docs/FIN-002_DESIGN.md) | 🟡 In progress — pending UI |
| 16 | FIN-008 | Deposits | [FIN-008_DESIGN.md](docs/FIN-008_DESIGN.md) | 🟡 In progress — pending UI |
| 17 | FIN-006 | Payment methods | [FIN-006_DESIGN.md](docs/FIN-006_DESIGN.md) | 🟡 In progress — pending UI |
| 18 | FIN-007 | Prepaid checks | [FIN-007_DESIGN.md](docs/FIN-007_DESIGN.md) | 🟡 In progress — pending UI |
| 19 | COM-001 | Communications | [COM-001_DESIGN.md](docs/COM-001_DESIGN.md) | 🟡 In progress — pending UI |
| 20 | MAINT-001 | Repairs | [MAINT-001_DESIGN.md](docs/MAINT-001_DESIGN.md) | 🟡 In progress — pending UI |
| 21 | MAINT-004 | Repairs | — | 🟡 In progress — pending UI |
| 22 | MAINT-002 | Repairs | — |  |
| 23 | MAINT-003 | Repairs | — |  |
| 24 | OWNER-003 | Owner management | — |  |
| 25 | OWNER-004 | Owner management | — |  |
| 26 | LIST-001 | Listings | — |  |
| 27 | LEAD-001 | Leads | — |  |
| 28 | LEAD-002 | Leads | — |  |
| 29 | LEAD-003 | Leads | — |  |
| 30 | ADJ-001 | Rent strategy | — |  |
| 31 | UI-001 | Operator interface | — |  |
| 32 | DASH-001 | Dashboard | — |  |
| 33 | FIN-003 | Money | — |  |
| 34 | OWNER-002 | Owner management | — |  |
| 35 | RPT-001 | Reports | — |  |
| 36 | RPT-002 | Reports | — |  |
| 37 | DASH-002 | Dashboard | — |  |
| 38 | AI-GOV-001 | AI governance | — |  |
| 39 | INGEST-001 | Issue ingestion | — |  |
| 40 | ISSUE-AI-001 | AI issue triage | — |  |
| 41 | ISSUE-AI-002 | AI issue triage | — |  |
| 42 | INGEST-002 | Issue ingestion | — |  |
| 43 | VOICE-001 | Voice intake | — |  |
| 44 | VOICE-AI-001 | AI voice intake | — |  |
| 45 | CONN-001 | Connections | — |  |
| 46 | GMAIL-001 | Gmail ingestion | — |  |
| 47 | OUTLOOK-001 | Outlook ingestion | — |  |
| 48 | SMS-001 | SMS ingestion | — |  |
| 49 | DASH-003 | Dashboard | — |  |
| 50 | LOCAL-003 | Local setup | — |  |
| 51 | LEAD-004 | Applications | — |  |
| 52 | APP-FIN-001 | Applicant financials | — |  |
| 53 | APP-DEC-001 | Lease approval | — |  |
| 54 | VEND-CAT-001 | Provider categories | — |  |
| 55 | JUR-001 | Jurisdiction rules | — |  |
| 56 | ADJ-002 | Rent strategy | — |  |
| 57 | ISSUE-AI-003 | AI issue diagnosis | — |  |
| 58 | ISSUE-AI-004 | AI provider suggestions | — |  |
| 59 | DOC-001 | Documents | — |  |
| 60 | DOC-AI-001 | AI documents | — |  |
| 61 | DOC-AI-002 | AI documents | — |  |
| 62 | DOC-AI-003 | AI documents | — |  |
| 63 | MKT-AI-001 | AI marketing | — |  |
| 64 | AI-REC-002 | AI recommendations | — |  |

### Next — Connected local features

| Seq | ID | Area | Design | Status |
|-----|-----|------|--------|--------|
| 65 | PAY-001 | Payments | — |  |
| 66 | FIN-004 | Money | — |  |
| 67 | FIN-005 | Money | — |  |
| 68 | COM-002 | Communications | — |  |
| 69 | COM-003 | Communications | — |  |
| 70 | OWNER-001 | Owner management | — |  |
| 71 | OWNER-005 | Owner management | — |  |
| 72 | LIST-002 | Listings | — |  |
| 73 | SCREEN-001 | Screening | — |  |
| 74 | SIGN-001 | E-signature | — |  |
| 75 | SHOW-AI-001 | AI scheduling | — |  |
| 76 | NEG-AI-001 | AI negotiation | — |  |
| 77 | NEG-AI-002 | AI negotiation | — |  |
| 78 | AI-REC-001 | AI recommendations | — |  |
| 79 | AI-REC-003 | AI recommendations | — |  |
| 80 | VEND-003 | Providers | — |  |
| 81 | VEND-005 | Provider discovery | — |  |
| 82 | OFFICE-001 | Commercial | — |  |

### Later — Local product extensions

| Seq | ID | Area | Design | Status |
|-----|-----|------|--------|--------|
| 83 | ACCT-001 | Accounting | — |  |
| 84 | OFFICE-002 | Commercial | — |  |
| 85 | VEND-004 | Providers | — |  |
| 86 | RPT-003 | Reports | — |  |
| 87 | RPT-004 | Reports | — |  |
| 88 | DATA-001 | Data | — |  |
| 89 | BEGIN-001 | Beginner experience | — |  |
| 90 | BEGIN-002 | Beginner experience | — |  |
| 91 | BEGIN-003 | Beginner experience | — |  |

### Future SaaS — Cloud, identity, and collaboration

| Seq | ID | Area | Design | Status |
|-----|-----|------|--------|--------|
| 92 | SAAS-001 | Cloud platform | — |  |
| 93 | SEC-001 | Authentication | — |  |
| 94 | SEC-002 | Authorization | — |  |
| 95 | SAAS-002 | Migration | — |  |
| 96 | SAAS-003 | Migration | — |  |
| 97 | SAAS-004 | Migration | — |  |
| 98 | SEC-003 | Secure intake | — |  |
| 99 | INTAKE-001 | Intake | — |  |
| 100 | PORTAL-001 | Tenant portal | — |  |
| 101 | PORTAL-002 | Owner portal | — |  |
| 102 | RPT-005 | Reports | — |  |
| 103 | PLATFORM-001 | Platform | — |  |
| 104 | API-001 | Platform | — |  |

### Later — Apartment extensions

| Seq | ID | Area | Design | Status |
|-----|-----|------|--------|--------|
| 105 | APT-001 | Apartments | — |  |
| 106 | APT-002 | Apartments | — |  |
| 107 | APT-003 | Apartments | — |  |
| 108 | APT-004 | Apartments | — |  |
| 109 | APT-005 | Apartments | — |  |
| 110 | APT-006 | Apartments | — |  |
| 111 | APT-007 | Apartments | — |  |
| 112 | APT-008 | Apartments | — |  |

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
