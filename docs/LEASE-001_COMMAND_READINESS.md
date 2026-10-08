# LEASE-001 command readiness — UI-001 Slice 13

Delivered October 8, 2026. The user approved a shared Lease revision and immutable
receipts for all existing Lease commands. OPS form registration and consequential
browser controls remain separate work in Slices 19–20.

## Owning contract

`leases.lease_revision` covers the Lease, initial terms, participants, renewal
options, termination cases and proposals. Creation requires revision zero and
commits revision one. Each effective command advances the aggregate once; unchanged
draft, term, participant and renewal edits retain the revision and `updatedAt`, but
still record an immutable no-change receipt. All public application commands require
concurrency metadata and a nonblank idempotency key of at most 200 characters.

HTTP requests use `expectedLeaseRevision` and `idempotencyKey`. For non-timeline
application methods, `expected_revision` is the Lease revision. Execute, end,
terminate, void and termination completion also require Portfolio's independent
Space revision: HTTP `expectedRevision`, application `expected_revision`. Their
Lease revision is application `expected_lease_revision`. A Lease child change does
not advance the Space status revision. Each timeline action still advances Space
status exactly once through the existing atomic source-timeline command.

Lease representations and termination-case reads expose `leaseRevision`. All
mutation responses require `operationId`; timeline results also require `revision`
for Space status. Lease revision conflicts carry the current Lease representation;
Space revision conflicts retain the full PORT-003 status snapshot. HTTP exposes a
typed 409 envelope with either snapshot.

| Command family | Public operations | Original result |
| --- | --- | --- |
| Draft | create, patch, replace initial term | Lease snapshot |
| Participants | add, update, remove | Lease snapshot, including the committed participant set |
| Renewal options | add, edit, decide | Lease snapshot, including the committed option history |
| Termination negotiation | request, propose/counter, accept, under-review/withdraw/decline | Termination-case snapshot, proposal history and parent Lease revision |
| Timeline | execute, end, terminate, void, complete termination case | Lease snapshot plus Lease/Space revisions and original source operation identity |

Canonical identities include action, target kind/ID, expected Lease revision and
the complete semantic payload, including supplied patch fields and the expected
Space revision where applicable. Omitted and explicit-null fields remain distinct.
Generated IDs, time and the idempotency key are excluded from the fingerprint.
Keys are globally unique within Leasing. Replay checks the receipt before current
Lease/child lifecycle or revision validation and returns the original response.
Changed reuse conflicts; it cannot adopt a newer current representation.

## Persistence and recovery

The current greenfield baseline adds `lease_command_operations`: UUID operation and
Lease IDs, unique idempotency key, action, expected/result Lease revisions, effective
flag, canonical request/response JSON and SHA-256 fingerprints, correlation ID and
UTC commit timestamp. An effective-revision unique index permits no-change receipts
without advancing the aggregate. Exact INSERT/UPDATE/DELETE guards prohibit receipt
replacement or mutation. No compatibility migration is provided.

One Lease-owned immediate transaction performs source and child writes, advances the
Lease revision, builds the transaction-visible response (including inspection
attention), appends the receipt and correlated `lease/command_applied` and
`lease_command_operation/recorded` events, and attaches a timeline consumer result
when needed. Existing domain and Portfolio audit events retain that correlation.
Failure at mutation, receipt, audit or database commit rolls everything back.
General activity omits receipt keys and fingerprints; the receipt audit stores
payload digests rather than private Lease narratives or full response bodies.

Read-only recovery routes:

- `GET /api/leases/operations/{operationId}` (`getLeaseCommandOperation`).
- `GET /api/leases/{leaseId}/operations/by-key?idempotencyKey=...`
  (`getLeaseCommandOperationByKey`).

Each route selects one indexed receipt and returns its recorded response and
metadata. It neither hydrates the current Lease nor writes audit/domain records.
Wrong Lease scope and absent operations return 404. Lookup requires workspace
readiness, but not the writer lock. It does not redispatch a lifecycle command.

Workspace-open, backup and restore validation check the exact receipt schema,
indexes, checks and trigger bodies; canonical payloads and hashes; legal Lease
revision/no-change chains; typed original results; current Lease and child facts;
correlated aggregate and receipt audit evidence; and agreement with Portfolio's
opaque source receipt, read through its owning port on the validation connection.

## Focused validation matrix

| Area | Proof |
| --- | --- |
| Happy paths | SQLite-backed create/patch, terms/participants, renewal decisions, termination negotiation/completion and typed HTTP results |
| Invalid combinations | Required application signatures, non-integer/boolean/negative revisions, malformed request metadata, wrong receipt scope and missing operations |
| Retry/idempotency | Original full response after subsequent edits/lifecycle changes; changed same-key payload conflict; concurrent same-key creation commits one receipt |
| No changes | Unchanged patch retains business state, timestamp and Lease revision while recording a no-change receipt |
| Concurrency | Child changes invalidate stale Lease commands without changing Space revision; timeline actions carry both independent revisions |
| Rollback | Receipt-audit failure and database-commit failure after source writes roll back Lease, Space timeline and receipts together |
| Persistence/schema | Exact receipt shape/uniqueness/partial index/trigger checks; UPDATE/DELETE/REPLACE rejection; tampered audit, source result, participant and revision history fail validation |
| Backup/restore | Encrypted LOCAL-002 round trip compares every receipt column and recorded response; old execute replays after later negotiation and restoration |
| Query budget | Recovery uses exactly one indexed SELECT and no writes or current-state hydration |
| Integration | Existing Finance, Maintenance, Inspection, Owner-accounting and OPS coverage fixtures invoke named commands with explicit fixture concurrency setup; no service monkeypatching |

Attachment commands remain FILE-001/INSP-001 gates. This slice does not introduce
rent amendments, automatically exercise renewal options, register new OPS forms,
or enable browser controls.
