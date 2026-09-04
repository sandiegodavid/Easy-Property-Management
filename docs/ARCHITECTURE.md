# MVP Architecture and Technology Plan

## Status and scope

This is the agreed implementation direction for the local, single-operator MVP. It records architecture decisions and options only; it does not authorize or include application code. Detailed product outcomes and dependencies remain in [FEATURE_BACKLOG.md](FEATURE_BACKLOG.md), and the product scope remains in [PRODUCT_BRIEF.md](PRODUCT_BRIEF.md).

## Architecture in one view

Use a **modular monolith**: one locally run application with a React/TypeScript user interface, a Python API, a SQLite workspace database, and a workspace file store. Modules are independently organized and tested but deploy together. This is the right fit for one operator and roughly 1–50 rentable spaces: it keeps installation, data ownership, backup, and support understandable while leaving clean seams for a future hosted product.

```text
Local browser or optional desktop shell
                │
                ▼
React + TypeScript user interface
                │  REST / OpenAPI on the local machine
                ▼
FastAPI application (Python)
  domain modules · jobs/outbox · connector and AI adapters
                │
       ┌────────┴────────┐
       ▼                 ▼
SQLite workspace      Workspace files
financial records     leases, receipts, photos, imports, exports
```

Do not begin with microservices, a cloud database, Redis, RabbitMQ, or a separate search service. They add operating complexity without solving an MVP problem. The application may initially run in the user's browser against a local server; packaging it as a desktop application is a later distribution decision and must not change its workspace model.

## User-facing modules

The navigation should use familiar, task-oriented language. Each module has one primary job, while related history and drill-down remain linked rather than duplicated.

| Navigation module | Main responsibility | MVP capabilities |
| --- | --- | --- |
| Home & Inbox | Answer “what needs attention now?” | Action dashboard, overdue rent, expiring leases, owner actions, showings, urgent repairs, source-message and AI-review queues. |
| Portfolio | Represent the physical portfolio and its ownership context | Properties, spaces, self-owned versus managed relationships, occupancy, contacts, and property history. |
| Leasing | Move a vacancy from listing to approved lease | Listings, leads, showings, offers/counteroffers, applications, applicant evidence, human approval decisions, leases, and rent adjustments. |
| Money | Make expected, received, spent, and due money understandable | Rent expectations and receipts, payment methods, prepaid checks, expenses, owner-reported rent, owner balances, and recorded owner disbursements. |
| Maintenance | Move a reported issue to a documented outcome | Owner/tenant/manager/staff-reported issues, triage, quotes, assignments, work journals, costs, and provider recommendations. |
| Service providers | Retain local provider knowledge | Categories, coverage, past work, references, preferred/avoid status, and manually recorded external-review links. |
| Communications | Preserve follow-up context | Tenant and owner communication history, reminders, task completion, and source attribution. |
| Documents | Produce and review controlled documents | Approved templates; AI-assisted drafting, summary, and comparison with human review. |
| AI assistance | Improve a workflow without becoming a separate destination | Embedded, reviewable drafts for issue intake and diagnosis, provider selection, document work, and listing copy; never autonomous action. |
| Reports | Explain performance and allow verification | Occupancy, rent roll, delinquency, income/expense, owner, leasing, and repair reports with source-record drill-down. |
| Settings | Manage the local product safely | Workspace and backup location, connections, provider categories, jurisdiction rules, document templates, AI controls, and data export/restore. |

Some modules will initially appear as sections inside another screen rather than as top-level navigation. For example, Service providers may live within Maintenance, Documents within Leasing and Settings, and Communications within the record it concerns. The information architecture should favor the fewest understandable destinations for a nontechnical operator.

## Backend domain modules

The server separates domain responsibilities from user-interface screens. This supports consistent rules and lets a later SaaS product retain the important business logic.

| Server module | Responsibility |
| --- | --- |
| `workspace` | Open, validate, migrate, back up, restore, relocate, and export a local workspace. |
| `parties` | Owners, tenants, prospects, vendors, companies, contacts, and their roles. |
| `portfolio` | Property, space, ownership/management relationships, availability, and occupancy. |
| `leasing` | Listings, leads, showings, offers, applications, approvals, leases, deposits, renewals, and rent changes. |
| `finance` | Rent expectations, receipts, payment methods, prepaid checks, expenses, categories, and financial allocations. |
| `owner-accounting` | Owner-reported receipts, balances, disbursement approvals, and disbursement history. |
| `maintenance` | Issue intake, reporter attribution, appointments, quotes, assignments, status, costs, and work journals. |
| `providers` | Provider profiles, categories, service areas, references, reputation notes, and historical outcomes. |
| `communications` | Interaction timeline, reminders, tasks, and completion/follow-up state. |
| `intake` | Gmail, Outlook.com/Hotmail, SMS, and voice-note source normalization, deduplication, review queues, and source links. |
| `documents` | Templates, versions, generated drafts, attachments, and document review metadata. |
| `jurisdictions` | Effective-dated notice rules, sources, verification dates, and alert calculations. |
| `reporting` | Read models, filters, aggregate reports, and source-record drill-down. |
| `ai-governance` | Source separation, prompt/input controls, retained AI output, confidence, approval decisions, and action limits. |
| `connectors` | External provider authorization, OS credential-store access, adapter lifecycle, and connection health. |

`platform` code supplies cross-cutting capabilities such as database access, file storage, auditing, logging, error handling, background job execution, and configuration. It must not become a substitute for domain rules.

## Recommended stack

| Layer | Recommendation | Why |
| --- | --- | --- |
| User-interface language/runtime | TypeScript on the current Node.js LTS release | A mature, type-safe ecosystem for the React interface, UI components, and browser tooling. |
| User interface | React with Vite | Mature component ecosystem, rapid local development, and a clean boundary from backend rules. |
| Server language/runtime | Python on a supported release | Best-fit ecosystem for the product's expanding AI, document, transcription, evaluation, analysis, and potential model-serving work. |
| API application | FastAPI | Typed validation, OpenAPI support, asynchronous integrations, and a clear, testable Python application structure. |
| API contract | REST with OpenAPI | Clear contracts for the web UI, local scripts, testing, and later SaaS migration; avoids premature GraphQL complexity. |
| Local database | SQLite in WAL mode | Embedded, portable, reliable single-operator data store with no database server to administer. |
| Database access and migrations | SQLAlchemy with Alembic | Mature Python data access and explicit, reviewable migrations for SQLite now and PostgreSQL later. |
| API/data validation | Pydantic | Shared validation approach for API requests, AI-structured output, and configuration. |
| Attachments | Filesystem inside the external workspace | Keeps lease files, receipts, photos, and exports portable with the local record set. |
| Background work | SQLite-backed jobs/outbox table run by the application | Handles ingestion, transcription, AI review preparation, reminders, and backup jobs without Redis or a message broker. |
| Secrets | Operating-system credential store | Keeps external connection credentials out of Git, the workspace database, exports, and backups. |
| Testing | Pytest unit/integration tests against a temporary SQLite workspace; browser end-to-end tests for critical operator workflows | Financial totals, records, approvals, migrations, and intake review are higher risk than screen styling. |
| Future cloud database | PostgreSQL | Suitable future destination for tenant-isolated SaaS workspaces, concurrent users, and central operations. |

## Viable alternatives

The backend recommendation is Python because AI is the product's largest planned growth surface—not because Python is required to call a model API. TypeScript can call the same services effectively. Python is preferred because document extraction, transcription pipelines, evaluation, retrieval, ranking, data analysis, and potential future model work can remain in the primary backend rather than becoming a second AI service later.

| Option | When it is a good fit | Trade-off |
| --- | --- | --- |
| React + FastAPI + SQLAlchemy | Recommended default; AI-intensive backend work stays in the primary application. | The interface and server use different languages, so the OpenAPI contract and browser client must be maintained deliberately. |
| React + NestJS/Fastify + TypeScript | Good choice for a strongly Node-oriented team with limited planned AI/data-processing complexity. | A growing Python AI service may become necessary later, creating two backend stacks and a more complex deployment model. |
| Rails + Hotwire + Active Job | Strong choice for a Rails-experienced team wanting a cohesive, convention-led product. | Less natural if the team expects a separate rich React interface. |

The stack choice should not change the core design: modular monolith, external workspace, SQLite for the MVP, filesystem attachments, OS-managed secrets, and a portable migration path.

## Repository structure

Use a feature-first monorepo. Source code, migrations, test fixtures, and operational scripts are Git-tracked. Real workspaces are outside this tree.

```text
easy-property-management/                 # Git repository; no user data
├── docs/
│   ├── ARCHITECTURE.md
│   ├── DECISIONS.md
│   ├── FEATURE_BACKLOG.md
│   ├── PRODUCT_BRIEF.md
│   └── ROADMAP.md
└── application/                           # future source-code root
    ├── apps/
    │   ├── web/
    │   │   └── src/
    │   │       ├── app/                   # routing, application shell, providers
    │   │       ├── features/              # home, portfolio, leasing, money, maintenance…
    │   │       └── shared/                # reusable UI, API client, formatting, accessibility
    │   └── server/
    │       └── app/
    │           ├── bootstrap/             # application startup and composition
    │           ├── modules/               # domain modules listed above
    │           └── platform/              # database, files, jobs, credentials, configuration
    ├── packages/
    │   ├── contracts/                     # OpenAPI contract, generated browser client, shared fixtures
    │   ├── ui/                            # shared presentational components
    │   └── test-support/                  # fixtures and workspace test helpers
    ├── database/
    │   ├── sqlite-migrations/
    │   └── postgres-migrations/           # introduced when SaaS work begins
    └── scripts/
        ├── setup/                         # product-owner workspace initialization/restore
        ├── backup/
        ├── restore/
        └── health-check/
```

Each server module follows the same internal shape where useful:

```text
modules/maintenance/
├── domain/             # entities, value objects, domain policies
├── application/        # use cases and transaction boundaries
├── api/                # request validation and API handlers
├── infrastructure/     # repository and external-adapter implementations
├── jobs/               # scheduled or asynchronous work
└── tests/
```

Do not create a single generic `services/` or `utils/` dumping ground for business logic. A rule about rent, approvals, notices, or repair assignment belongs in its owning domain module.

## Local workspace and Git boundary

The live user workspace is configurable and must be external to the repository. It contains the SQLite database, its `-wal` and `-shm` companions while active, attachments, exports, and backups. For the MVP, the application discovers it through a small local locator at `application/config.local.json`; that file is explicitly excluded from Git.

The live locator sets `localWorkspacePath` to the chosen external data folder. It is not committed even though it sits under the application source root; only [application/config.example.json](../application/config.example.json), which deliberately uses a fake path, is tracked. A packaged future version may relocate this small locator to operating-system application settings without moving the workspace itself.

```text
chosen-workspace/
├── workspace.json
├── database/
│   ├── property-management.sqlite
│   ├── property-management.sqlite-wal     # present while WAL is active
│   └── property-management.sqlite-shm     # present while WAL is active
├── files/
├── exports/
└── backups/
```

Git tracks only application code, schema migrations, scripts, templates, documentation, and sanitized fixtures. `.gitignore` must defensively exclude databases and their WAL/SHM files, workspace folders, attachments, imports, exports, backups, logs, and environment files. Production paths are never inferred from the current Git checkout.

On startup, the application resolves the locator, validates the workspace manifest and permissions, obtains the single-writer lock, creates a consistent pre-migration backup when needed, runs transactional schema migrations, and checks workspace integrity. A missing configured workspace presents **Retry**, **Locate workspace**, or **Restore backup**—never an unnoticed empty database.

## SQLite suitability and operating limits

SQLite is sufficient for the MVP target: a single local operator managing approximately 1–50 rentable spaces, their financial records, communication history, issue history, and metadata for attached files. The size-intensive evidence and media live in workspace files, not database blobs by default. SQLite's JSON and full-text-search capabilities can support flexible metadata and local search when actually needed.

Use WAL mode for responsive reads while the application writes, but design around SQLite's single-writer model: short transactions, one local application writer, and a durable job/outbox queue. Do not attempt shared multi-machine editing, simultaneous network writers, or a cloud-sync folder as the live database. Those are future SaaS concerns.

Backups of an active workspace use SQLite's backup facility or an equivalent consistent snapshot, then package the associated attachment files. Do not copy only the main `.sqlite` file while the application is running. Restore, relocation, and SaaS-export workflows verify both records and file references before they switch to the result.

## AI and connector architecture

AI and external providers are adapters behind explicit interfaces, not direct calls scattered through features. The relevant module prepares a bounded input from a source record; `ai-governance` retains the source reference, model/output metadata, confidence, and operator decision. The output remains a draft until approved. No AI module may send a message, sign a document, initiate a payment, or assign/contact a provider without an explicit operator action.

Gmail, Outlook.com/Hotmail, SMS, transcription, and any later reputation sources use connector adapters. Tokens are held in the operating-system credential store and keyed to the workspace ID. Ingested messages retain source IDs and source links so processing can be idempotent and auditable. Connector credentials never enter an export, backup, or SaaS migration; they must be reauthorized after restore or migration.

## Future SaaS path

The MVP's domain modules, stable IDs, versioned schema, workspace-relative attachments, and portable export format are deliberate preparation for SaaS. The future hosted product can replace the local SQLite repository with PostgreSQL-backed tenant-isolated workspaces and introduce authentication, authorization, portals, collaboration, and central background workers without rewriting the core business rules.

Local-to-cloud migration must analyze and validate the workspace, run a dry run, preserve stable IDs and financial totals, import attachments and retained intake/AI history, provide retry/rollback safeguards, and then require external-account reauthorization. The local MVP must remain usable and recoverable if a migration is not completed.
