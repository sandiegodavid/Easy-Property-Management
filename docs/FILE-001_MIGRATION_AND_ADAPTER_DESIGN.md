# FILE-001 — File Storage and Schema Design

`file_records` and `file_links` are part of the single current Alembic baseline. Their SQLAlchemy models own the schema definition, while the file module owns current-schema validation and the filesystem blob-store and metadata-repository adapters.

This is a greenfield product: a workspace must have the current Alembic revision and complete file schema. Future migrations will be added as ordinary Alembic revisions only after real customer data exists.

The file service identifies content by SHA-256, validates local content before reuse, and keeps file metadata, links, and audit events transactional. Its initial adapter stores bytes under `files/managed`, but file identity and domain links do not depend on a physical storage provider. Lease documents and inspection evidence use ordinary typed file links; feature modules do not create another file store.

## Storage-neutral identity and links

`file_records` owns portable logical metadata: stable ID, original name, media type, byte size, SHA-256, and creation metadata. `file_links` associates that logical file with a domain record through `entity_type`, `entity_id`, and `purpose`. Neither a lease nor a condition observation stores a local path, S3 key, bucket, or temporary URL.

Physical placement is owned by a FILE-001 content-location boundary. A current location records:

- `file_id` and `storage_provider` (`local` or `s3`);
- a controlled state such as `pending`, `available`, `missing`, or `quarantined`;
- `local_relative_path` only for local content;
- `s3_bucket`, `s3_object_key`, and optional `s3_version_id` only for S3 content;
- optional provider metadata such as ETag, plus application-owned `verified_at`;
- the file record's independent SHA-256 and byte size as the portable integrity authority.

Exact constraints require precisely the locator fields for the selected provider. S3 ETags are not treated as content hashes. No presigned-URL API is part of the local MVP, and file retrieval currently streams a verified temporary local copy through the configured adapter. The adapter uses the host's standard AWS SDK credential-provider chain; credentials and presigned URLs are never persisted in workspace records or archives. A future connected-access surface may add short-lived presigned URLs behind its own authorization boundary.

The content-store port is responsible for staging, publication, retrieval, verification, and deletion policy. Moving or replicating bytes between local and S3 storage changes the content location without changing `file_records`, `file_links`, observation IDs, or audit history.

S3 publication requires bucket versioning. Each upload publishes to an operation-owned, no-overwrite object key, records the returned version ID, and verifies that exact version by SHA-256 before metadata commits. A failed metadata transaction may delete only the exact object version created by that operation. S3 objects are not shared for deduplication because safe rollback must hold across different machines and processes; SHA-256 remains the portable content identity.

The local workspace adapter remains the MVP default. The S3 adapter and content-location schema are an optional connected-storage extension; inspection-domain code must use the storage-neutral contract from its first implementation so enabling that adapter does not require changing condition-report relationships.

## Portability and backup

Local backup and export verify every recorded local file and reject unexpected or missing managed content. When an S3 adapter is enabled, a portable backup must retrieve and hash-verify the referenced object and embed its bytes in the encrypted archive. A successful restore therefore does not depend on the original bucket, cloud account, or presigned URL still existing. Missing or unverifiable remote evidence makes the backup incomplete and must be reported rather than silently producing a complete-looking archive.
