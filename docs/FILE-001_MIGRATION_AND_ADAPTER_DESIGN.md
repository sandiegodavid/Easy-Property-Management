# FILE-001 — File Storage and Schema Design

`file_records` and `file_links` are part of the single current Alembic baseline. Their SQLAlchemy models own the schema definition, while the file module owns current-schema validation and the filesystem blob-store and metadata-repository adapters.

This is a greenfield product: a workspace must have the current Alembic revision and complete file schema. Future migrations will be added as ordinary Alembic revisions only after real customer data exists.

The file service stores content by SHA-256 under `files/managed`, persists portable relative paths, validates content before reuse, and keeps file metadata, links, and audit events transactional. Backup and restore verify every recorded managed file and reject unexpected or missing files.
