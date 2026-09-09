# FILE-001 — Storage-Neutral File Store Design

## Purpose

FILE-001 stores business attachments—leases, receipts, issue photos, quotes, message attachments, and condition evidence—through a storage-neutral record while keeping references portable across backup, restore, and future SaaS migration.

## Model and safety

- `file_records` stores immutable logical metadata, content hash, media type, display name, size, and creation time. Provider-specific content-location records store `available` state and durable local-path or S3 bucket/object/version identity. The default provider stores bytes at `files/managed/<sha256>`; optional S3 records retain their own bucket and object identifiers rather than relying on the current configuration or a presigned URL.
- Content-addressed storage deduplicates identical bytes. New business links never overwrite an existing file.
- `file_records` owns immutable file metadata; provider-specific content-location records own storage state and durable location identity; `file_links` connects a file to a domain record with a domain-approved purpose. Owning business tables never duplicate file metadata or storage fields. A link requires a registered owning-domain validator; arbitrary entity types, IDs, and purposes are rejected. Physical deletion and retention are intentionally deferred.
- Uploads are size-limited, stream-hashed, staged under a private temporary name, verified, and atomically published. Filenames are display metadata only and cannot select a filesystem path.
- Each metadata/link write records an audit event in the same SQLite transaction. File snapshots contain portable metadata only—never file bytes.

## API

- `POST /api/files` accepts one multipart upload plus optional entity type, entity ID, and purpose, using the configured default provider.
- `GET /api/files/{id}` returns portable metadata and links.
- `GET /api/files/{id}/content` returns the stored bytes with the recorded media type and a safe download name.

The module does not interpret lease, payment, issue, or communication rules; later modules provide their record IDs and labels. Its API is deliberately technical plumbing for upload, metadata retrieval, and safe byte retrieval. Operator-facing workflows show linked files in their owning lease, inspection, expense, or issue context rather than as a generic file-cabinet screen.

The remaining Alembic migration and adapter-boundary design is recorded in [FILE-001_MIGRATION_AND_ADAPTER_DESIGN.md](FILE-001_MIGRATION_AND_ADAPTER_DESIGN.md).

## Acceptance

1. An uploaded file is staged, hashed, atomically stored, and represented by a portable logical record with a provider-specific durable location.
2. Duplicate bytes share one stored content path without losing separate metadata records or links.
3. Traversal filenames, oversize input, and missing content fail safely without publishing partial bytes or rows.
4. File metadata and links survive LOCAL-002 backup/restore and appear in append-only audit history. Portable backup/export materializes and hash-verifies referenced remote content, embedding it in the encrypted package so restoration does not depend on the original S3 account.
