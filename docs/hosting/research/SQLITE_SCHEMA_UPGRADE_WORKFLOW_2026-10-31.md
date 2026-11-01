# Per-Operator SQLite Schema Upgrade Workflow

Prepared: October 31, 2026
Revised November 25, 2026. Design decisions accepted for future release qualification. H10 owns hosted rollout. Implementation and production qualification are pending.

[Release design](../design/mvp/releases.md) · [Delivery plan](../design/mvp/delivery-plan.md) · [Recovery](../design/mvp/recovery.md) · [Store ownership](../../database/schema-resources.md)

## 1. When an upgrade path becomes necessary

During greenfield development EPM keeps one latest schema per store. Once Pilot 0 holds real customer records, subsequent releases must preserve those stores and every accepted write. The October C6 incident illustrates why the first protected release matters. Two builds shipped different audit constraints under the same Alembic revision. A version comparison could not identify which schema a workspace actually contained.

## 2. Existing implementation boundary

The business initializer applies Alembic head to a fresh database. Its validator checks exact revision, structure and domain invariants. Local archive restore validates the extracted workspace against the installed schema before publishing it. These paths establish fresh initialization and compatible restore. The upgrade operation described below requires separate qualification. Hosted business, access, operator recovery, Admin, Admin recovery and host inventory each have their own owner and revision.

## 3. The Bluesky pattern, in brief

Three layers, each answering a different kind of schema change:

- Storage schema (the per-user SQLite file): versioned, numbered migrations. The store records its schema version, and the PDS ships a migrator whose contract is: if the store is already at the latest version, do nothing; otherwise run the pending migrations and bring it to latest. New accounts are created at the latest version. Accounts on mixed versions during a rollout are a normal state, and the surrounding code is written to tolerate the window (ship code that reads both shapes, migrate, then remove the old shape).
- Application schema (what a post or a follow is): kept out of the database entirely. Records are content-addressed CBOR blocks in a Merkle Search Tree; the SQL tables are storage plumbing (blocks by CID, record URI to CID, commits, backlinks). Record types are defined by Lexicons and evolve additively (new optional fields, new collections; readers ignore fields they do not understand), so most product evolution needs no database migration at all. A breaking change gets a new collection name.
- Derived data (AppView indexes): disposable. The repositories are the source of truth, so an indexer whose schema changes can drop its database and rebuild by replaying the firehose. Bluesky proved the storage layer itself is replaceable when it moved the PDS from PostgreSQL to per-user SQLite: a repo exports as a CAR file and re-imports anywhere.

For EPM, the useful precedent is preserving released migration history while independently stored accounts move between supported versions. Each EPM store retains its relational constraints and its owning service controls changes.

## 4. Establish the supported release history

Before the first protected rollout, inventory the stores admitted to persist customer records. H10 must publish the first protected artifact identity, per-store revision, expected structural fingerprint and digests of migration resources and dependencies that affect their behavior. Keep the manifest with an independently retained qualified release. CI compares subsequent packages to it and rejects edits or removal of frozen resources. Append new migrations for actual required changes. Disposable development builds create no compatibility commitment.

At open, identify the expected store and validate its revision and actual structure. An exact match still requires the owning validator. A known supported ancestor can enter its qualified upgrade path. A release manifest can identify a proven newer schema and direct the operator to a compatible release. For a missing stamp, unknown or divergent lineage, wrong store, or unexplained structural mismatch, preserve the store and report the specific condition. Where admitted variants share a stamp, require a recognized source fingerprint and a separately qualified path for each. Never infer age from revision-string ordering or repair ambiguity by stamping.

For every admitted artifact and store, publish which versions it can read, write, migrate from and restore, including API compatibility and the values each writer can produce. Preserve a tested path from every admitted starting version through skipped releases. For destructive changes, ship expansion first, migrate and verify existing data, then contract only when every affected reader and writer is compatible or fenced. Test old binaries with new data before authorizing image-only rollback. Adjacent-version support in the new binary proves only one direction.

## 5. Run a hosted upgrade

1. **Assign and schedule.** Admin approves a pinned target. H10 starts with a canary, limits batch size, and halts expansion on failure. Honor the operator’s announced window and permitted deferral. Ordinary startup checks readiness. A waking workspace may resume its authorized release operation before serving traffic.
2. **Drain and protect.** The operation takes the workspace maintenance gate, prevents new writes, preserves acknowledged drafts, drains admitted work across devices and reconciles uncertain outcomes. Bind a verified off-host recovery point to the final drained business revision, retained-file generation, source incarnation, relevant store revisions and source artifact. Reuse a point only after proving an exact match. Pin its content, key reference and compatible validator through acceptance and the documented recovery window, independently of nightly rotation. Verify capacity for backup, staging and table rebuilds before DDL.
3. **Apply through each store owner.** The release manifest specifies store order and allowed intermediate combinations. An owning runner applies each revision on its own connection in one explicit write transaction. Apply DDL, validate target structure and relevant data, and advance the stamp in that transaction. Keep intermediate combinations fenced. The existing fresh-store initializer keeps its separate contract.
4. **Recover interrupted work.** Keep durable release progress outside the data being replaced. Record operation identity and request digest, source and target, maintenance fence, recovery point, step and observed effect. On retry, reconcile receipts with validated store state. After a crash during a transaction, expect the last committed logical state. After a commit with a lost acknowledgment, verify the effect before advancing. If evidence disagrees, keep the gate closed and surface the required intervention. Each store commits independently.
5. **Verify and reopen.** Start the pinned image behind the gate and check source binding, all required store combinations, data and smoke operations. Only the owning job releases its gate after confirming current access policy. Reconnect clients, preserve drafts and reconcile uncertain submissions through their original identities. Show Updating, completion or a supportable failure state.
6. **Recover a failed release.** Prefer a retained, validated original binding when safe. H10 may automate pre-write recovery only through the owning recovery service under authority bound to this release operation, exact point and uninterrupted fence. If authority or absence of subsequent writes cannot be proven, retain the fence and use authenticated recovery. Once writes reopen, preserve them and use a forward fix or separately reviewed, operator-authorized recovery. Stage restored business data separately and keep live sessions and entitlements under their own authorities.
7. **Measure rollout.** A bounded, read-only census compares verified state to each assignment and reports current, deferred, in progress, failed or unknown. A deferred compatible workspace can coexist with a completed canary. Before contraction, account for every affected assignment, including sleeping workspaces. Unknown state cannot establish that an incompatible reader is gone.

For local use, ordinary opening checks compatibility without changing schema. A future local upgrade requires explicit OS/workspace-owner initiation, exclusive access, a usable archive destination and passphrase or configured secret, sufficient space and a verified staged recovery path using the source-compatible release. Qualify local encrypted archives and hosted off-host recovery separately. If prerequisites fail, explain how to reopen with the supported source release or resolve the blocker.

## 6. Worked qualification example — C6

Keep the two historical audit shapes as synthetic same-stamp fixtures. Classify both before any write. An unsupported fingerprint stops the operation. If a real admitted shape needs a CHECK change, preflight existing rows against the target constraint and report conflicts before copying. On a dedicated connection, prepare any necessary foreign-key enforcement change before BEGIN. Inside the owning transaction, create the replacement, copy and verify rows, replace the table and recreate dependent indexes, triggers and views. Specifically restore both audit triggers that reject UPDATE and DELETE. Verify their behavior, foreign keys, data and target structure before committing the stamp. Restore normal enforcement before reusing the connection. Qualify the actual packaged driver and transaction path. [SQLite table rebuild procedure](https://www.sqlite.org/lang_altertable.html#making_other_kinds_of_table_schema_changes)

## 7. Version structured payloads without changing evidence

Each payload owner defines its version discriminator, the interpretation of an absent version, and supported read and write versions. Decode older supported formats into an in-memory projection. Preserve original bytes, hashes, evidence identity and provenance. Unknown versions fail closed for operations requiring interpretation. Persist conversion of mutable data only through an explicit owning operation or qualified migration. Test replay, strict readers and older binaries against values a new writer may emit.

## 8. Release qualification matrix

Release engineering retains sanitized golden fixtures, resource manifests and validators alongside each protected source artifact. Store owners verify fixtures and expected invariants when a new version is admitted. Run the matrix against the packaged candidate.

| Scenario | Required evidence |
| --- | --- |
| Fresh install, adjacent and skipped releases | Fresh and upgraded stores meet target invariants. Validate intermediate revisions, preserved row identities and checksums, then exercise domain reads and writes. |
| Invalid source or binary pairing | Same stamp with wrong shape, unknown or divergent revision, wrong store, incompatible API or data semantics all leave the source intact and explain the blocker. |
| Crash, retry and rollback | Interrupt before and after each commit, between stores and after lost acknowledgment. Same request reconciles once, conflicting requests are rejected, and ambiguous state stays fenced. |
| Audit rebuild and payload conversion | Constraints, indexes, append-only behavior and foreign keys survive. Original evidence digests and replay results remain valid. |
| Backup, restore and release failure | Exercise unavailable keys or storage, full disk, staged restore from an older point, failed startup checks and recovery after reopening. Prove acknowledged writes survive and current access authority is preserved. |
| Concurrency and operator experience | Race upgrade with restore and wake. Test active, deferred and sleeping operators together. Verify one writer, draft continuity, visible failure state and a failed canary halting its batch. |
| Resource and fleet limits | Measure scan time, staging space, downtime and verification at representative maximum workspace sizes. Set rollout budgets from those measurements and exercise bounded, paginated census reads. |

## 9. References

- Gergely Orosz, Building Bluesky: a Distributed Social Network (The Pragmatic Engineer, April 2024; updated November 2024). The scaling section covers the move from PostgreSQL to ScyllaDB for the AppView and per-user SQLite for the PDS. https://newsletter.pragmaticengineer.com/p/bluesky
- Bluesky, Federation Architecture (May 5, 2023). The PDS, repository, and account-portability model this note borrows from. https://bsky.social/about/blog/5-5-2023-federation-architecture
- Kleppmann et al., Bluesky and the AT Protocol: Usable Decentralized Social Media (arXiv 2402.03239, February 2024). Repository as a Merkle Search Tree of records, Lexicon schemas, and why derived indexes are rebuildable. https://arxiv.org/pdf/2402.03239.pdf
- bluesky-social/atproto source tree. The PDS actor store (per-account SQLite databases, schema versioning and the migrator) lives under packages/pds/src/actor-store, with migrations under packages/pds/src/actor-store/db/migrations. https://github.com/bluesky-social/atproto
- DeepWiki index of the atproto PDS: repository operations and storage (per-user database layout, creation running migrations, record and blob storage). https://deepwiki.com/bluesky-social/atproto/4.4-repository-operations-and-storage
- AT Protocol account migration guide. The CAR-file export and import flow that makes the storage layer replaceable. https://atproto.com/guides/account-migration
- Hacker News discussion of the Bluesky PDS move to single-tenant SQLite, including the mixed-schema-version rollout discussion. https://news.ycombinator.com/item?id=38171322
