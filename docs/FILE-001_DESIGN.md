# FILE-001 — Local File Store Design

## Purpose

FILE-001 stores business attachments—leases, receipts, issue photos, quotes, and message attachments—inside the external workspace while keeping database references portable across backup, restore, and future SaaS migration.

## Model and safety

- File bytes live at `files/managed/<sha256>`; the database stores only that workspace-relative path, hash, media type, original display name, size, and creation time.
- Content-addressed storage deduplicates identical bytes. New business links never overwrite an existing file.
- `file_records` owns immutable file metadata; provider-specific content-location records own storage state and durable location identity; `file_links` connects a file to a future domain record with a purpose label. Owning business tables never duplicate file metadata or storage fields. Physical deletion and retention are intentionally deferred.
- Uploads are size-limited, stream-hashed, staged under a private temporary name, verified, and atomically published. Filenames are display metadata only and cannot select a filesystem path.
- Each metadata/link write records an audit event in the same SQLite transaction. File snapshots contain portable metadata only—never file bytes.

## API

- `POST /api/files` accepts one local multipart upload plus optional entity type, entity ID, and purpose.
- `GET /api/files/{id}` returns portable metadata and links.
- `GET /api/files/{id}/content` returns the stored bytes with the recorded media type and a safe download name.

The module does not interpret lease, payment, issue, or communication rules; later modules provide their record IDs and labels. Its API is deliberately technical plumbing for upload, metadata retrieval, and safe byte retrieval. Operator-facing workflows show linked files in their owning lease, inspection, expense, or issue context rather than as a generic file-cabinet screen.

The remaining Alembic migration and adapter-boundary design is recorded in [FILE-001_MIGRATION_AND_ADAPTER_DESIGN.md](FILE-001_MIGRATION_AND_ADAPTER_DESIGN.md).

## Acceptance

1. An uploaded file is staged, hashed, atomically stored, and represented with a portable workspace-relative reference.
2. Duplicate bytes share one stored content path without losing separate metadata records or links.
3. Traversal filenames, oversize input, and missing content fail safely without publishing partial bytes or rows.
4. File metadata and links survive LOCAL-002 backup/restore and appear in append-only audit history.
