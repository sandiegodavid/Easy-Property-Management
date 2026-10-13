# Retained source evidence and provenance

## Responsibility and source granularity

Intake retains one bounded email/message/note/transcript snapshot and provenance before interpretation. A conversation reference groups messages but is not a growing source record. An accepted source is untrusted evidence; it does not establish a Maintenance issue or recorded communication.

## Canonical evidence and limits

The versioned envelope contains source kind, optional subject, plain text, bounded participants, occurrence/zone context, qualified identifiers and allowed provenance/confidence fields. HTML/arbitrary headers/provider JSON are not executed or accepted as extra fields. Optional raw artifacts are File attachments.

Normalize Unicode NFC and line endings while preserving meaningful body whitespace. Bounds include subject 500 characters, body 131,072 UTF-8 bytes, 50 participants, 500-character identifiers, 20 attachments, 50 MiB per File and 100 MiB aggregate. Duplicate attachment hashes in one source manifest are rejected. Reasons are bounded; source pages default 50/max 200.

## Admission, integrity and revisions

Manual text/multipart admission validates the full envelope and attachment manifest before committing. One caller-owned transaction stores a ready source, initial immutable evidence revision, exact revision/File associations, operation and correlated audit. File batches remain held through commit and release or roll back operation-owned content.

Corrections append complete evidence revisions with reasons; attention/integrity transitions advance source state without rewriting original evidence. Wrong identity or attachment membership requires nonbranching supersession, not correction of immutable associations. Later integrity failure is separate from dismissal; verified restoration does not redefine bytes or evidence identity.

Technical state and operator attention are independent. Attention starts unprocessed, may enter registered review, and becomes resolved only through the approved owning consequence. Confirmed reasoned dismissal/reopening retain evidence. Review consumers use transaction-aware attention ports; they never write Intake tables directly.

## Identity and replay

Operation replay uses UUID key plus canonical request fingerprint. Verified exact source replay uses origin system, trusted account-scope hash, source kind and external source ID; connection identity is not account identity. Equal content is only a probable-duplicate hint. An unverified account claim cannot establish hard cross-connection deduplication.

Trusted replay resolves matching retained historical lineage evidence and rejects changed evidence; a corrected current snapshot cannot erase the original admission identity. Retained validation enforces lineage consistency. Manual HTTP callers cannot supply authenticated assistant/grant provenance; a future transport must bind it through the internal trusted admission boundary.

## Sensitive disclosure

`IntakeService.get()` commits its fail-closed sensitive-read audit before returning evidence. `evidence_detail()` similarly audits an exact revision and enforces history/attachment bounds before disclosure. The caller-owned connection reader exposes bounded non-sensitive current/historical facts only; it cannot return raw evidence inside a transaction that the caller could roll back. Lists/search disclose only approved metadata; reading a correction receipt containing evidence also requires an audit commit.

## API and integration

`/api/intake/sources` supplies manual admission/import, detail/list, correct/supersede/dismiss/reopen and operation lookup. `/{source_id}/revisions/{revision_id}` supplies typed, bounded, audited exact evidence with immutable revision facts and current source lifecycle metadata; foreign revision membership fails closed. Admission and recovery do not fetch mail or authenticate assistants. Communications can explicitly link a source without copying content or creating a ledger entry; its current-source projection identifies superseded sources while preserving the stored historical link. Governed extraction, issue proposal review and assistant transports are separate active work; manual evidence retention remains usable with AI off.

## Browser workflow boundary

Conversations → Retained source evidence provides bounded manual admission/import/correction/supersession/dismissal/reopening with the six registered operator command forms. Full content is disclosed through fail-closed audited Intake reads. Revision selection explicitly opens retained historical evidence alongside the current representation; failed authorization never reveals the selected body. Saved import metadata retains ordered roles/digests; bytes require reselection. Failed/superseded evidence remains historical and guarded, and unavailable attachments cannot be opened. Issue-proposal review remains UI-002. See the [workflow guide](../ui/workflows.md) and [browser validation](../ui/validation.md) for implementation and evidence entry points.

## Implementation map

- [Domain values and invariants](../../application/apps/server/app/modules/intake/domain).
- [Use cases and application ports](../../application/apps/server/app/modules/intake/application).
- [HTTP contracts](../../application/apps/server/app/modules/intake/api).
- [Persistence and source adapters](../../application/apps/server/app/modules/intake/infrastructure).

Persistence identities below are read from the current models. Column definitions, checks and indexes live in the linked models and the [current baseline](../../application/database/sqlite-migrations/versions/0001_initial_schema.py); update them together.

| Tables | Model definitions |
| --- | --- |
| `intake_sources`, `intake_evidence_revisions`, `intake_revision_file_links`, `intake_source_operations`, `intake_source_duplicate_candidates` | [sqlalchemy_models.py](../../application/apps/server/app/modules/intake/infrastructure/sqlalchemy_models.py) |

## Validation

Acceptance completed October 13, 2026: **72 focused Intake/Communications backend tests** and **7 packaged Intake browser tests** passed. The [completed acceptance matrix](../archive/designs/INGEST-001_DESIGN_COMPLETED_2026-10-13.md) records scope and quality-check limitations. Encrypted restore compares retained source/revision/operation/File rows, correlated audits and exact attachment bytes; page queries have a constant three-SELECT upper bound for one versus 25 records.

- [test_command_readiness.py](../../application/apps/server/app/modules/intake/tests/test_command_readiness.py).
- [test_intake.py](../../application/apps/server/app/modules/intake/tests/test_intake.py).

Use the [shared validation matrix](../platform/persistence.md#validation-matrix) when changing this boundary. Core browser acceptance is recorded in [browser validation](../ui/validation.md); later capability acceptance remains in [active work](../active/README.md).
