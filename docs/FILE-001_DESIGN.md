# FILE-001 — Storage-Neutral File Store

## Purpose

FILE-001 stores retained business evidence such as lease documents, receipts, issue photos, quotes, message attachments, and condition evidence. It gives each upload a stable logical identity, keeps its physical location behind a storage adapter, and links it to owning domain records through validated purposes.

The default MVP provider stores bytes in the external local workspace. The same logical file and link contracts support the optional S3 provider and future SaaS migration without putting filesystem paths, bucket details, or temporary URLs in business tables.

This document defines the only supported greenfield format. A workspace must match the current schema and retained-data rules exactly. There are no legacy file tables, compatibility aliases, or upgrade/adoption paths.

## Scope and boundaries

FILE-001 owns:

- immutable logical file metadata and content hashes;
- one current provider-specific content location per logical file;
- staging, publication, provider verification, retrieval, and storage state;
- portable links from a file to a domain record;
- the owning-domain validation boundary for link entity types, IDs, purposes, and archival;
- file/link audit events and safe content download; and
- file integrity checks for workspace validation, backup, export, and restore.

FILE-001 does not interpret lease, finance, inspection, maintenance, communication, or Intake business rules. It does not infer a business link from a filename, path, media type, or content. It provides no generic file-cabinet workflow, public filesystem access, presigned-URL API, physical-delete lifecycle, or temporary-media retention policy.

Owning features decide which evidence is required, when their aggregate may accept it, which purpose names are valid, how many links are allowed, and whether an incorrect link may be archived. They use FILE-001 through application ports and never copy file metadata or provider location into their own tables.

## Current schema

All IDs are UUID text. Timestamps are timezone-aware UTC text. The SQLAlchemy models, current Alembic baseline, exact-schema validator, archive validator, and this design must describe the same three tables and indexes.

### `file_records`

One immutable logical record is created for each accepted upload. Two uploads with identical bytes may have different logical records and business links while sharing local content-addressed bytes.

| Column | Rule |
| --- | --- |
| `id` | Primary key. |
| `original_name` | Required normalized safe display name only; never a path selector. |
| `media_type` | Required normalized declared media type, or `application/octet-stream` when absent or invalid. It does not grant safe inline rendering. |
| `size_bytes` | Required integer greater than or equal to zero. |
| `content_sha256` | Required application-owned SHA-256 content identity. |
| `created_at` | Required UTC timestamp. |

Index `file_records_content(content_sha256)` supports content reuse and integrity lookup. The hash is intentionally not unique because logical upload identity and business association remain separate from byte deduplication.

### `file_content_locations`

Each logical file has exactly one current content-location row, keyed and foreign-keyed by `file_id`.

| Column | Rule |
| --- | --- |
| `file_id` | Primary key and foreign key to `file_records.id`. |
| `storage_provider` | `local` or `s3`. |
| `storage_state` | `available`, `missing`, or `quarantined`. Normal accepted uploads commit as `available`. |
| `local_relative_path` | Required only for `local`; workspace-relative and controlled by FILE-001. |
| `s3_bucket`, `s3_object_key` | Required only for `s3`. |
| `s3_version_id` | Required durable S3 version identity for `s3`; null for `local`. |
| `provider_etag` | Optional provider metadata. It is never treated as the content hash. |
| `verified_at` | Required application verification timestamp. |

The locator check requires local rows to contain only `local_relative_path` and S3 rows to contain a bucket, object key, and non-null version ID while leaving the local path null. Index `file_content_locations_provider(storage_provider, local_relative_path, s3_bucket, s3_object_key)` supports provider validation and lookup. Retrieval, verification, backup, and cleanup always address the exact S3 version and never fall back to the provider's latest version.

`verified_at` records the latest successful application verification, not the last attempted read. A normal accepted upload starts in `available`. An explicit verification operation may move it to `missing` when the exact local file or remote object version does not exist, or to `quarantined` when bytes exist but fail boundary, regular-file, size, or SHA-256 validation. A later successful explicit verification may restore `available` and advance `verified_at`.

`pending` is not part of the current greenfield schema because neither current adapter publishes after metadata commit or persists a restart-safe recovery identity. A future post-metadata adapter must introduce its durable recovery fields and state transition as an explicit schema and design change.

### `file_links`

A link associates one logical file with one owning domain record.

| Column | Rule |
| --- | --- |
| `id` | Primary key. |
| `file_id` | Required foreign key to `file_records.id`. |
| `entity_type`, `entity_id` | Required owning-domain target. |
| `purpose` | Required owning-domain purpose. |
| `created_at` | Required UTC timestamp. |
| `archived_at`, `archive_reason` | Both null for an active link; both present for an archived link. Reason is trimmed and 1–1,000 characters. |

Index `file_links_entity(entity_type, entity_id)` supports contextual reads. Partial unique index `file_links_one_active_association(file_id, entity_type, entity_id, purpose) WHERE archived_at IS NULL` prevents a duplicate active association while allowing a corrected active link after an earlier link is archived.

File records, content locations, and historical links are retained. Link archival changes association visibility; it never deletes logical metadata or bytes.

One logical file may have several independently validated domain links. Reuse occurs only through an owning-workflow application command that receives an existing file ID and the new target and purpose. The command requires `available` content, validates the target through its owning-domain policy, writes the link and audit event atomically, and never changes the original file metadata. An owning UI may offer “Use this evidence in…” from an evidence item already visible in that workflow; FILE-001 provides no global file browser, discovery search, or unrestricted generic link-creation endpoint.

## Storage providers

### Safe display metadata

Before persistence, FILE-001 normalizes `original_name` to Unicode NFC. It rejects blank names, `.` and `..`, forward or backward path separators, NUL and other control characters, and names longer than 255 UTF-8 bytes. An otherwise ordinary name may contain consecutive dots; the name is display metadata and never participates in path construction.

FILE-001 normalizes a syntactically valid declared media type and otherwise records `application/octet-stream`. Content detection may later supply advisory metadata, but neither a declared nor detected type authorizes inline rendering. The content endpoint always uses attachment disposition with the safe recorded filename and sends `X-Content-Type-Options: nosniff`.

### Local workspace provider

The default provider stores managed content under `files/managed/<sha256>` in the configured external workspace. It:

1. copies the input to a private random `.uploading` file while counting bytes and computing SHA-256;
2. rejects input above the 50 MiB upload limit;
3. acquires a content-hash operation lock;
4. verifies an existing content-addressed target before reuse, or atomically publishes the private file with restrictive permissions; and
5. returns a content lease containing the verified size, hash, relative path, and rollback ownership.

Traversal filenames and symlinked, missing, non-regular, size-mismatched, or hash-mismatched managed content fail closed. Publication and retrieval verify that the files root and `managed` directory are real directories, require the exact `managed/<sha256>` locator, open the candidate without following its final symlink where the host supports that control, verify the opened descriptor is a regular file, and hash that opened content. Filenames remain display metadata and cannot influence the storage target.

Local content-addressed storage may reuse one physical target for several logical file records. Rollback removes a target only when that operation created it; it never removes previously verified shared content.

### S3 provider

The optional S3 provider uses an operation-owned, no-overwrite object key under `<configured-prefix>/<workspace-id>/`. The key and provider metadata include a unique publication identity so explicit workspace verification can distinguish this workspace's referenced and orphaned versions without scanning or claiming another workspace's objects. Bucket versioning is mandatory. It:

1. hashes and bounds the local input;
2. publishes to a unique object key;
3. requires a non-null durable version ID;
4. reads and SHA-256-verifies that exact version before metadata commits; and
5. retains the bucket, object key, version ID, and optional ETag in the content-location row.

S3 ETags are not content hashes. Remote objects are not shared for byte deduplication because rollback ownership must remain exact across processes and devices. A failed operation may delete only the exact version it created. If publication does not return a usable version ID, cleanup must first identify the exact private version or fail visibly without guessing.

Explicit workspace verification examines at most 1,000 S3 object versions per reconciliation page, returns an opaque continuation cursor when more remain, and compares exact bucket/key/version identities with retained locations. The Settings workflow and local maintenance command continue until all pages complete or the operator stops; a partial run is labeled incomplete and never reported as a clean result. Reconciliation reports unexpected versions as orphans and never deletes them automatically. A future cleanup command must present the exact versions, require explicit confirmation, and record the result. Referenced versions are still read back and hash-verified; listing alone is not integrity verification.

The adapter uses the host SDK credential-provider chain. Credentials and presigned URLs are never persisted in the workspace, file tables, audit snapshots, exports, or backups. Retrieval streams a hash-verified temporary local copy through the FILE-001 API.

## Transaction and rollback contract

Current local and S3 adapters publish and verify operation-owned content before `available` metadata commits. In a caller-owned workflow:

1. The owning service opens one immediate SQLite transaction.
2. For each attachment, FILE-001 publishes and verifies the bytes, writes its file record, content location, validated link, and correlated file audit events on that connection, and returns a rollback lease.
3. The owning service writes its domain rows and audit events on the same connection while retaining every returned lease.
4. After database commit, it calls `commit()` on each lease to release rollback ownership and locks. This does not publish content a second time.
5. If file preparation or the database transaction fails, it calls `rollback()` on every acquired lease in reverse order. Each rollback may remove only content created by that operation.

This ordering prevents committed `available` metadata from pointing to content that the current adapter has not published and verified. A hard process stop between content publication and database commit can instead leave bytes without a file row. Local workspace/archive verification reports unexpected managed content and never invents metadata or a business association for it. An enabled remote provider must implement equivalent bounded orphan reconciliation using its operation-owned object/version identity before claiming the same guarantee.

FILE-001 manages caller-owned attachments through a transaction-scoped batch that retains all leases until database commit, releases them after commit, and rolls them back in reverse acquisition order after failure. Commit and rollback are idempotent. For local content, the batch coalesces repeated hashes onto one physical publication and digest lock while preserving separate logical file records and independently validated links. Digest locking must not turn a valid request into an unexplained timeout. INGEST-001 may still reject duplicate attachment hashes within one source manifest as its explicit owning-domain rule.

If provider cleanup fails before metadata commit, the operation returns a typed `publication_cleanup_incomplete` result that preserves both the original failure and exact cleanup identity for that response. When the database remains writable, FILE-001 writes a system-actor `file_publication_cleanup/cleanup_incomplete` audit event keyed by publication ID and shows workspace-integrity attention in Settings; its audit snapshot identifies the provider and outcome without storing a bucket, object key, local path, credential, or URL. A later completed full verification writes the corresponding verification result and clears the attention only when no orphan or content failure remains. Local and S3 orphan verification remains the authoritative way to locate leftover content. The application never guesses which remote version to delete. A post-commit lease-release failure is reported as an operational failure and never retried as a new upload because the metadata already committed.

## Domain link validation

Every link operation resolves a registered `FileLinkValidator` for its entity type. The validator uses the caller's transaction to confirm:

- the target exists and is in a lifecycle state that may accept the purpose;
- the purpose belongs to that target type;
- domain-specific link-count and evidence rules remain satisfied; and
- an archive request is permitted and preserves required evidence.

Unknown entity types, IDs, purposes, or missing validators fail closed. The generic `POST /api/files` route may create a link only through this validation boundary.

The public upload route requires target context and never creates a permanently unlinked retained file. Content may be temporarily unlinked only inside an owning workflow that creates the required association in the same caller-owned transaction. A prepared upload that cannot be associated is rolled back. This prevents undiscoverable retained records in a product with no generic file-cabinet or physical-delete workflow.

Some aggregates need the file, domain row, association, and audit history to commit together. Their owning service uses FILE-001's caller-owned transaction port rather than creating a domain record and later guessing whether the upload succeeded. If a valid attachment requires additional immutable association rows, as with INGEST-001 source revisions, direct generic linking is rejected and the owning workflow writes the complete association atomically.

Current examples include:

- FIN-002 `expense`: `receipt`, `invoice`, `proof_of_payment`, and `supporting_document`, with at most twenty active evidence links;
- lease, inspection, maintenance, deposit, and owner-report purposes registered by their owning modules; and
- INGEST-001 `intake_source`: owning-workflow-only association with immutable source-revision membership.

Purpose `receipt` on an expense means documentary evidence; it is not a FIN-001 rent-receipt record.

## API and read behavior

- `POST /api/files` accepts one multipart upload plus required `entity_type`, `entity_id`, and `purpose` through the configured default provider. The client cannot select a storage provider.
- `GET /api/files/{fileId}` returns portable logical metadata, current provider/state information, and retained links. It never returns a usable credential or unrestricted local path.
- `GET /api/files/{fileId}/content` verifies availability and integrity, then returns bytes using the recorded media type and a safe download name.
- `POST /api/file-links/{linkId}/archive` requires explicit confirmation, a bounded reason, and owning-domain approval. It archives only the association.

Owning workflows may use an internal `link_existing_file` application command; there is no public generic equivalent. Normal domain evidence lists show active links. An active `missing` or `quarantined` item remains visible in its owning context with an explicit unavailable status and disabled open action. Archived links are omitted from normal evidence lists and remain available in the owning record's contextual history. `GET /api/files/{fileId}` includes active and archived link metadata. Archive reasons are visible to the local operator in contextual record and link history but remain redacted from global activity.

Content reads are read-only. A read verifies the exact recorded bytes and returns a typed unavailable or integrity error when verification fails, but it does not silently mutate storage state through a GET request. State transitions belong to an explicit verification command that requires the workspace writer lock, rechecks the provider, writes `missing`, `quarantined`, or restored `available` state and `verified_at` as applicable, and records a system-actor change through AUDIT-001 in the same database transaction. Quarantine is a retained metadata state: it does not move, overwrite, or delete the suspect bytes. Provider outages are reported as temporary provider failures rather than being misclassified as missing content.

The operator can start full verification from Settings, and the local maintenance interface exposes the same command. Content reads verify only the requested file. Backup/export verifies all retained content without persisting state transitions. Application startup performs schema and retained-data validation but does not perform an unbounded remote object scan; S3 namespace reconciliation runs only through explicit verification and may return a continuation requirement.

Recovery never changes an accepted file's identity. Missing local content may return to `available` only after the exact recorded bytes are restored and explicit verification confirms its size and hash. Mismatched local bytes are not used to redefine the record. An absent or corrupt immutable S3 version cannot be repaired in place; the operator uploads a new logical file and corrects the association through the owning workflow. Successful recovery advances `verified_at`; failed attempts leave it at the last successful verification time.

Only `available` content can be read as evidence. `missing` and `quarantined` are explicit unavailable states and cannot be interpreted as an empty or successful attachment. Backup and export fail visibly while any retained content is unavailable; they never change storage state as a side effect.

The API distinguishes failures with stable codes: `file_not_found` uses `404`; `file_content_unavailable` and `file_integrity_failed` use `409`; `file_provider_unavailable` and incomplete cleanup use `503`; malformed link requests use `400`; and a valid request rejected by the target's current lifecycle uses `409`. Provider exceptions are translated at the FILE-001 boundary and never expose credentials, unrestricted locators, or raw SDK responses.

The operator sees files through their owning lease, inspection, expense, issue, source, or other workflow. The single-operator local MVP has workspace-wide access after the local workspace runtime is ready; it has no separate per-record login or ACL. A file UUID is still not a public capability URL and FILE-001 exposes no unrestricted filesystem path. Future SaaS access must authorize the tenant and owning-domain context before returning metadata or bytes.

Logical file metadata is immutable. A wrong display filename or media type is corrected by uploading a new logical file, archiving the incorrect association when its owning policy permits, and attaching the replacement. FILE-001 never changes the recorded name, media type, size, or content hash in place.

## Audit, integrity, and current-format validation

File and link creation and link archival write fail-closed AUDIT-001 events in the same database transaction. Audit snapshots contain portable metadata and association facts, never file bytes, credentials, presigned URLs, or unrestricted storage paths.

Workspace-open schema validation verifies:

- the exact three-table schema, columns, types, nullability, foreign keys, checks, and indexes described above;
- valid provider/state values and exactly the locator fields allowed for that provider;
- active/archive link constraints and active-association uniqueness; and
- the absence of unknown or obsolete file columns and tables.

FILE-001 retained-data validation verifies UUIDs, UTC timestamps, normalized names and media types, SHA-256 form, exactly one current location per file, at least one retained link per file, accepted states, exact local locators, and non-null exact S3 versions. Owning-domain retained-data validators verify every link's registered target, purpose, lifecycle history, and active-link limits. Content is verified during publication, every content read, explicit verification, and backup/export/restore. Those archive operations also verify that referenced content exists, matches byte size and SHA-256, remains inside its controlled storage boundary, and does not produce a complete-looking result when content is unavailable. Only explicit verification persists a storage-state transition; other read and packaging paths fail without disguising a provider outage or integrity problem as successful evidence.

Unknown columns, obsolete shapes, missing tables, unsupported provider/state values, invalid domain links, or unverifiable retained content fail the applicable validation boundary. The application does not silently repair, infer, or import another format.

## Backup, restore, and portability

LOCAL-002 backup/export uses a consistent SQLite snapshot and includes every referenced managed file. It verifies recorded local files and rejects missing, mismatched, or unexpected local managed content rather than producing a complete-looking package.

When S3 is enabled, portable backup retrieves and verifies the exact referenced object version and embeds its bytes in the encrypted archive. Restore therefore does not depend on the original bucket, account, credentials, or URL. Missing or unverifiable remote evidence makes the backup incomplete and must be reported.

Restore recreates verified local managed content and the same stable logical IDs, metadata, provider-neutral associations, archived-link history, and audit evidence. Provider locators may change as part of a separately validated relocation, but domain records continue to reference logical file/link IDs rather than physical storage identity.

## Retention and disposable media

Managed FILE-001 content is retained business evidence. Archiving every link does not delete the file record or physical bytes, and the MVP exposes no physical-delete API.

A workflow that promises disposable media, such as VOICE-001 audio before transcription, keeps it in a workflow-owned private temporary store with restart-safe cleanup. Only an explicit operator decision promotes that media into FILE-001 with a normal verified record and owning-domain link. Once promoted, it follows retained-file rules.

A future managed-file deletion feature must define reference eligibility, active and archived link behavior, source/AI/audit dependencies, legal holds, backup retention, deduplicated-local-content safety, provider deletion confirmation, and interruption recovery before removing any bytes.

## Acceptance criteria

1. An accepted upload is bounded, stream-hashed, provider-verified, atomically represented by the current logical/location schema, and retrievable without exposing an unrestricted storage path.
2. Duplicate local bytes can share content-addressed storage without merging logical records or business links; S3 publications retain exact operation-owned versions.
3. Traversal names, oversize input, unknown link targets/purposes, symlinks, missing content, and size/hash mismatches fail safely.
4. A caller-owned domain operation commits file metadata, content location, validated association, owning record, and correlated audit evidence atomically, or rolls back its operation-owned publications.
5. An incorrect association can be archived only with explicit confirmation, reason, and owning-domain approval; the historical link and bytes remain retained.
6. Only verified `available` content is presented as evidence. Missing, quarantined, orphaned, or unverifiable content produces an explicit unavailable/incomplete result.
7. Exact current-schema and retained-data validation reject legacy or malformed workspaces rather than silently upgrading them.
8. Encrypted backup/export and restore preserve stable logical identities, associations, history, and verified bytes without depending on an original S3 account.
9. Disposable workflow media stays outside managed storage until explicit promotion; no workflow claims that archiving a FILE-001 link deletes bytes.
10. Display filenames and media types follow the bounded normalization rules, and downloads are attachment-only with MIME sniffing disabled.
11. Storage-state changes occur only through an audited writer-owned verification command; ordinary reads and archive operations report failures without silently changing retained state.
12. S3 orphan reconciliation is workspace-scoped, paginated at 1,000 versions, resumable, and never reports a partial scan as clean or deletes an orphan automatically.
13. Every committed file has at least one retained owning-domain link; the HTTP upload route requires target context and exposes no client storage-provider selector.
14. An existing available file can be reused only from an owning workflow through an audited validated association, without a global file browser or generic public link route.
15. Cleanup failures produce a typed response and privacy-safe workspace-integrity attention that remains until a complete verification finds no unresolved storage problem.
16. Incorrect immutable file metadata is corrected with a replacement upload and owning-domain association correction rather than an in-place edit.
