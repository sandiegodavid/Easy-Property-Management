# Application architecture

## System at a glance

Easy Property Management is a local single-operator modular monolith for US portfolios. It uses React/Vite/TypeScript, FastAPI/Python, SQLAlchemy, a current Alembic SQLite baseline and an external workspace file store. Modules deploy together and keep separate business ownership.

```text
Browser on the local machine
    │ same-origin REST / generated OpenAPI contracts
    ▼
FastAPI · loopback transport policy · packaged web assets
    │
    ├─ source-owned domain services and application ports
    ├─ Operator compositions, preferences and form recovery
    └─ shared runtime, audit, errors and storage mechanics
    │
    ├─ external workspace SQLite database
    ├─ managed evidence files (local; optional version-pinned S3)
    └─ OS credential store / host credentials, outside portable data
```

The backend and core UI-001 browser workflows are implemented, including Money, Maintenance, Tasks/communications, search and information review, manual Intake and capability-gated AI Settings/review. [Current UI guides](ui/operator-experience.md) describe behavior; [validation evidence](ui/validation.md) records completed packaged-browser and restart/restore acceptance. DASH-001 Home aggregation is delivered. Legal/HOA, spreadsheet intake and issue-proposal review remain UI-002; connected-assistant setup/health move to UI-003. A bounded EPM-invoked drafting action may be delivered independently of assistant connection. The [product brief](PRODUCT_BRIEF.md) describes intended scope and the [backlog](FEATURE_BACKLOG.md) tracks delivery; production AI availability remains separately registered and gated.

## Ownership map

| Implemented package | Authority | Current reference |
| --- | --- | --- |
| `workspace` | External workspace identity/readiness and encrypted portable recovery | [Workspace](modules/workspace.md) |
| `audit` | Append-only record history and snapshot read marker | [Audit](modules/audit.md) |
| `files` | Logical file identity, exact storage/integrity and owning links | [Files](modules/files.md) |
| `parties` | Reusable person/organization identity and contact methods | [Parties](modules/parties.md) |
| `portfolio` | Properties, Spaces, ownership, occupancy and availability | [Portfolio](modules/portfolio.md) |
| `tenants` | Tenant role/profile and contact preference | [Tenants](modules/tenants.md) |
| `leases` | Terms, participants, contract lifecycle, renewal and termination | [Leases](modules/leases.md) |
| `inspections` | Condition reports, evidence, acknowledgment and comparison | [Inspections](modules/inspections.md) |
| `vendors` | Provider profiles, categories, references and reputation links | [Providers](modules/providers.md) |
| `finance` | Expected/recorded rent, actual expenses/refunds, checks, deposits and summaries | [Finance](modules/finance.md) |
| `owner_accounting` | Owner rent claims and verified Finance receipt provenance | [Owner accounting](modules/owner-accounting.md) |
| `owner_management` | Client-owner operational concern lifecycle | [Owner management](modules/owner-management.md) |
| `tasks` | Actions, deadlines, reminders and independent waiting/follow-up | [Tasks](modules/tasks.md) |
| `communications` | Manual recorded interaction history and explicit context | [Communications](modules/communications.md) |
| `intake` | Canonical retained source evidence, identity and revision lineage | [Intake](modules/intake.md) |
| `ai_governance` | Provider-neutral configuration, governed generation/review infrastructure | [AI governance](modules/ai-governance.md) |
| `operator` | Bounded source compositions, information review, preferences and incomplete forms | [Operator](modules/operator.md) |

Navigation names differ from package boundaries. An Owners view can compose Portfolio, concerns, communication and whole-property money; it does not own those records. Documents and interactions are contextual. Home aggregation, legal/HOA cases, spreadsheet intake and connected-assistant transport are separate planned delivery, rather than existing modules hidden behind the navigation.

## Module structure and composition

Server modules live in `application/apps/server/app/modules/<module>/`:

- `domain/`: values, invariants and snapshot policies.
- `application/`: use cases, transaction-aware ports and consumer-neutral read facts.
- `infrastructure/`: owning SQLAlchemy models, repositories, units of work and adapters.
- `api/`: strict typed contracts, router validation and stable error mappings.
- `tests/`: focused executable domain/HTTP/persistence specifications.

[bootstrap/api.py](../application/apps/server/app/bootstrap/api.py) wires services and routers. The other bootstrap files compose context validation, File link policies, source adapters, recovery forms and immutable-result readers. Cross-module policy goes through small application protocols; a consumer must not import another domain's ORM model/repository. Source adapters own source queries; consumers own their workflow and presentation.

## Records and coordinated operations

A Property is a top-level reporting aggregate; Space is an independent child with occupancy/availability history and Lease references. Party is shared identity with multi-valued contact methods, while Tenant/Provider profiles and client-owner relationships add roles. File metadata and provider location are centralized; source records store validated associations rather than copied paths/hash metadata.

Source authority must remain visible across coordination:

- Lease contractual transitions use Portfolio's complete source-timeline operation, with independent Lease/Space revisions and one caller transaction.
- Finance explicitly synchronizes Lease terms and records money. Lease execution does not silently create expectations. Quotes, scheduled checks and owner claims are not received income/spending.
- Owner report verification adopts/creates one Finance receipt atomically. Inspection evidence supports reviewed deposit deductions without deciding them.
- Source workflows can create linked Tasks and Files atomically through application ports; Task/appointment/journal completion does not resolve a physical issue automatically.
- Operator recovery prepares an attempt and reads the original owning result; it never dispatches or authorizes the business command itself.

## Shared platform contracts

[Persistence](platform/persistence.md) defines immediate writes, deferred snapshots, current-schema validation, original-result replay and portable validation. [API contracts](platform/api-contracts.md) defines the shared problem envelope and generated-contract boundary. [Local security](platform/security-and-audit.md) defines Host/Origin controls, secrets and disclosure.

Store monetary values as integer USD cents and exact formatted decimal strings. Use stored Property zones for business dates, aware UTC instants for event time and explicit captured `asOf` for read classifications. Keep aggregate revisions, append markers and runtime epochs distinct.

One server owns the writer lock. SQLite suits the local single-operator workload; network shares/cloud-synchronized live database access are unsupported operating assumptions. Backups use validated consistent snapshots rather than copying live journal files independently. No distributed queue or background job framework is assumed; the configured backup scheduler is an explicit local service.

## Optional AI and future integrations

The production AI action/adapter/redaction/source registries are currently empty. Governance infrastructure, configuration and synthetic tests do not establish production model or assistant capability. Built-in models use registered provider-neutral ports and explicit cloud/device disclosure. Assistant transports require separate grants/adapters and reviewed proposals; no vendor is mandatory.

Research and planned feature designs separate an EPM-invoked draft action, a shared assistant boundary, alternative local MCP/file transports, and later qualified source discovery. File exchange is a conditional adapter with a managed workspace subfolder and portable-backup extension, not a deployed capability. Read-only Sheets and Universal Reader remain separate proposals. None alters current authority or gates manual workflows. See [active work](active/README.md) and [research](research/README.md).

## Frontend and deployment

[Frontend architecture](ui/frontend-architecture.md) maps bootstrap, route/capability registry, server/form/recovery state and packaged delivery. The server serves trusted compiled assets and restricted HTML fallback on loopback. Development explicitly allows an exact loopback Vite origin. External workspace data never enters the public bundle or Git.

A future hosted product requires tenant isolation, authentication, remote permissions, hosted storage and reauthorization. Those are planned capabilities, not current local access controls. Preserve portable stable identities and module ports without building speculative compatibility layers.
