# Managed evidence files

## Responsibility and identities

Files owns immutable logical metadata/hash, exact storage location/state, validated domain associations and safe byte retrieval. One logical file can have several owning-workflow links. Identical bytes may share local physical content while remaining distinct uploads. Business modules retain IDs and approved purposes, not storage paths or copied metadata.

## Storage and publication

Default local storage is `files/managed/<sha256>` under the external workspace. Upload bounds are 50 MiB; safe display names are NFC and at most 255 UTF-8 bytes, with separators/control characters rejected. Names never choose paths. Verify regular files, exact size/hash and symlink boundaries before reuse/read.

The optional S3 adapter requires versioning, operation-owned no-overwrite keys and exact version IDs. Hash-verify that version before committing metadata; ETags are not content hashes. Use host SDK credentials, never portable workspace secrets or a latest-version fallback.

Publish and verify before committing available metadata. Caller-owned attachment batches retain leases through database commit, coalesce local digest locks, release after success and roll back only operation-owned content in reverse order after failure. A process stop can leave orphan bytes; explicit verification reports them without inventing metadata or deleting automatically. Cleanup failures remain visible, with bounded safe audit attention.

## Associations, lifecycle and downloads

Every association uses the owning entity/purpose policy on the caller's transaction. Unknown targets/purposes and protected lifecycle fail closed. Public upload requires an owning context; Intake's immutable revision associations require its own workflow. Generic file discovery/linking is not provided.

Logical metadata and bytes have no physical-delete lifecycle. An incorrect association can be archived only with owning approval, confirmation/reason, expected link revision and UUID key. Active link revision is 1 and archived revision 2; archival is irreversible. Display missing/quarantined evidence explicitly, with unavailable download rather than an empty list.

Content GET verifies exact bytes without persisting state transitions. Return attachment disposition and nosniff. Explicit writer-locked verification sets missing/quarantined/restored available and records audit; outages are not misclassified as missing. Backup/export verifies all retained content and fails visibly on unavailable evidence.

## Command recovery and integrity

Upload/archive retain immutable original receipts. Fingerprints include verified content identity and normalized metadata/context, or link revision/confirmation/reason. Same-key replay precedes later target-state changes. Key/ID lookup is indexed and never republishes bytes. Lost upload responses are reconciled before another attempt.

Storage verification is a separate explicit operation with paged remote reconciliation, not an OPS recoverable business command. S3 scans are bounded to 1,000 versions per page; incomplete scans cannot report clean. Startup validates schema/retained data without an unbounded remote scan. Restoring local availability requires the exact original bytes; corrupt immutable remote content requires a new logical file and an explicit corrected association.

## API families

`/api/files`, file metadata/content/verification/command lookup and `/api/file-links/{id}` own generic plumbing. Each business screen supplies its permitted context. Current metadata, link and command tables are listed below; the older three-table-only planning description is superseded by the implemented command ledger.

## Implementation map

- [Domain values and invariants](../../application/apps/server/app/modules/files/domain).
- [Use cases and application ports](../../application/apps/server/app/modules/files/application).
- [HTTP contracts](../../application/apps/server/app/modules/files/api).
- [Persistence and source adapters](../../application/apps/server/app/modules/files/infrastructure).

Persistence identities below are read from the current models. Column definitions, checks and indexes live in the linked models and the [current baseline](../../application/database/sqlite-migrations/versions/0001_initial_schema.py); update them together.

| Tables | Model definitions |
| --- | --- |
| `file_records`, `file_links`, `file_content_locations`, `file_publication_cleanup_attentions`, `file_command_operations` | [sqlalchemy_models.py](../../application/apps/server/app/modules/files/infrastructure/sqlalchemy_models.py) |

## Validation

The following executable specifications are the starting point for focused validation. This documentation consolidation did not rerun them or establish feature completion.

- [test_command_readiness.py](../../application/apps/server/app/modules/files/tests/test_command_readiness.py).
- [test_files.py](../../application/apps/server/app/modules/files/tests/test_files.py).

Use the [shared validation matrix](../platform/persistence.md#validation-matrix) when changing this boundary. Core browser acceptance is recorded in [browser validation](../ui/validation.md); later capability acceptance remains in [active work](../active/README.md).
