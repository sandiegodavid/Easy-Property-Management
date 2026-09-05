# FILE-001 — Migration and Adapter Refactor Design

This document designs the remaining FILE-001 implementation work. It does not change the current database or file-store behavior.

## 1. Move file schema ownership to SQLAlchemy and Alembic

### Target ownership

`BootstrapMigrationRunner` remains limited to workspace identity, audit-ledger bootstrap, and its migration ledger. FILE-001 becomes the first ORM-owned product schema:

```text
application/
├── alembic.ini
├── database/sqlite-migrations/          # Alembic script location
│   ├── env.py
│   └── versions/
│       └── 0001_file_records_and_links.py
└── apps/server/app/platform/database/
    ├── sqlalchemy.py                    # SQLite engine/session factory
    └── models.py                        # shared SQLAlchemy metadata only
```

`modules/files/infrastructure/sqlalchemy_models.py` defines `FileRecordModel` and `FileLinkModel`; the Alembic revision imports their metadata and creates `file_records`, `file_links`, and their indexes. It is written using SQLite-compatible types/constraints so the same logical schema can later target PostgreSQL.

### Compatibility and rollout

1. Ship Alembic infrastructure and revision `0001` first, with a `schema_migrations`/Alembic version table managed only by Alembic.
2. Before applying the revision, inspect the existing native platform migration ledger.
3. If native version 2 exists and its schema matches the expected `file_records`/`file_links` shape, stamp Alembic `0001` without recreating tables. Record an audit event `file_schema_adopted` in the same workspace operation.
4. If version 2 is absent, apply `0001` normally. If either table exists but does not match, stop with a controlled migration error and preserve the pre-migration SQLite-consistent safety snapshot.
5. After all supported local workspaces have an Alembic revision, remove file-schema creation from `BootstrapMigrationRunner`; native version 2 becomes an adoption marker only for older workspaces and is never created for new ones.
6. New workspaces run native bootstrap then Alembic upgrade before the workspace is published.

The migration runner must use the same single-writer/runtime ownership and SQLite-consistent pre-migration snapshot guarantees as the existing bootstrap flow. Alembic errors are translated to `WorkspaceError` and leave the workspace not-ready.

### Acceptance criteria

- A new workspace has Alembic revision `0001` and no file-table creation in the native bootstrap runner.
- A workspace made by the current FILE-001 release adopts its existing tables without data loss or table recreation.
- Metadata, links, audit IDs, managed bytes, backup/restore, and migration safety snapshots remain intact across adoption.
- SQLite and future PostgreSQL migration checks use the same model metadata and revision history.

## 2. Split FILE-001 adapters

### Ports

`modules/files/application/ports.py` defines only application-facing contracts:

```text
FileContentStore
  stage_and_hash(source) -> StagedContent
  publish_or_reuse(staged) -> PublishedContent
  discard(staged | published) -> None
  verify(relative_path, sha256, size) -> Path

FileMetadataRepository
  create_file_and_optional_link(unit_of_work, draft) -> StoredFile
  get(file_id) -> StoredFile
  has_reference(relative_path) -> bool

FileUnitOfWork
  transaction() -> context manager
```

`StagedContent` is private temporary state. `PublishedContent` carries the canonical relative path, hash, size, and whether this operation created the blob. Neither is exposed as an API response.

### Adapter responsibilities

| Component | Responsibility |
| --- | --- |
| `FilesystemContentStore` | Streaming, hashing, private staging, digest serialization/retry, atomic publication, safe compensation, and byte verification. It owns the per-digest lock. |
| `SqlAlchemyFileMetadataRepository` | ORM models, file/link queries, and metadata persistence. It does not touch filesystem paths. |
| `SqlAlchemyFileUnitOfWork` | One database transaction and audit-recorder integration. |
| `FileService` | Validate use-case inputs; coordinate content publication with metadata/audit commit; compensate only through the content-store port; return domain values. |
| API router | Enforce runtime readiness; stream multipart input into the content-store staging operation; map typed errors to HTTP responses. |

### Transaction/compensation sequence

1. API streams the upload to `FilesystemContentStore.stage_and_hash` with the size limit.
2. `FileService` validates name/link intent and asks the store to publish or reuse the digest under its per-digest lock.
3. Within `FileUnitOfWork`, repository creates metadata and optional link; audit events are appended; transaction commits.
4. On a failure before commit, `FileService` calls `discard` while the content-store still holds the digest lock. The store deletes only a blob it created and only after confirming no committed repository reference exists.
5. On success, the lock is released. Backup validation independently reconciles all managed blobs and records.

### Tests

- Unit-test `FilesystemContentStore` for streams, limits, staged cleanup, hash tampering, duplicate serialization, and compensation.
- Unit-test the SQLAlchemy repository for metadata/link persistence and query shape.
- Integration-test file + audit rollback in one unit of work.
- Migration tests cover new workspace, native-v2 adoption, corrupt legacy schema rejection, encrypted backup/restore, and attachment corruption rejection.

## Delivery order

1. Add SQLAlchemy engine/session and Alembic environment with no production schema change.
2. Add FILE-001 ORM models, revision, and adoption planner/tests.
3. Route workspace migration lifecycle through Alembic and remove native file-table creation.
4. Add content-store/repository/unit-of-work adapters behind ports.
5. Switch API composition to adapters and remove the legacy `FileService` SQLite/filesystem implementation.
6. Run complete workspace, audit, file, backup, restore, and migration regression suites; only then mark FILE-001 done.
