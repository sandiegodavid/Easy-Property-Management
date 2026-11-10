# Per-Operator SQLite Schema Upgrade Workflow

> **Research input, not independently adopted — status clarified November 10, 2026.** Current direction: [Hosted MVP design](../design/HOSTED_MVP_DESIGN.md). The technical proposal below must be evaluated against the current one-writer, immutable-release and no-post-reopen-data-loss upgrade rules. Its historical repository findings and proposed mechanisms are not automatically accepted or implemented.

Prepared: October 31, 2026
Status: design proposal, not yet adopted
Origin: study of how Bluesky's Personal Data Server (PDS) handles schema change across per-user SQLite databases ([Pragmatic Engineer deep dive on Bluesky](https://newsletter.pragmaticengineer.com/p/bluesky), the [May 2023 federation architecture post](https://bsky.social/about/blog/5-5-2023-federation-architecture), the [AT Protocol paper, arXiv 2402.03239](https://arxiv.org/pdf/2402.03239.pdf), and the [bluesky-social/atproto source tree](https://github.com/bluesky-social/atproto)). Full references in section 9.
Related: docs/hosting/HOSTING_REVIEW_2026-10-24.md, finding C6

## 1. Why this note exists

EPM stores each operator workspace as its own SQLite database, the same shape Bluesky converged on for the PDS (one SQLite file per account). Bluesky operates millions of those files, most of them on machines and deployments it does not fully control, and still ships schema changes routinely. EPM's current upgrade story cannot do that yet: finding C6 in the October 24 hosting review showed a schema change made by editing the initial migration in place, which leaves every pre-existing workspace invalid under the new build. This note adapts the Bluesky pattern into a concrete workflow for EPM so that per-workspace schema upgrades become routine, automatic, and recoverable.

## 2. Current state (verified October 31, 2026)

- Migrations are Alembic, rooted at application/database/sqlite-migrations/ (env.py plus a versions/ directory).
- There is exactly one version file: 0001_initial_schema.py (54,323 bytes in the source tree as of October 26, 2026), containing the entire schema.
- The shipped file has already changed between releases: dist builds from October 25, 2026 carry a 53,983-byte 0001_initial_schema.py; builds from October 26 and 27 carry the 54,323-byte version. The change is the in-place edit recorded as finding C6 (adding hosted_operator to the audit_events actor CHECK constraint, plus a reference-length CHECK).
- modules/audit/infrastructure/schema_validation.py demands the newest constraint text exactly, so a workspace created before the edit fails validation under the new build with MigrationSchemaError.
- The standing greenfield policy sanctions backup-and-restore as the way an existing local workspace survives a breaking schema change. That is a manual, per-user recovery procedure being used as the upgrade path.

## 3. The Bluesky pattern, in brief

Three layers, each answering a different kind of schema change:

- Storage schema (the per-user SQLite file): versioned, numbered migrations. The store records its schema version, and the PDS ships a migrator whose contract is: if the store is already at the latest version, do nothing; otherwise run the pending migrations and bring it to latest. New accounts are created at the latest version. Accounts on mixed versions during a rollout are a normal state, and the surrounding code is written to tolerate the window (ship code that reads both shapes, migrate, then remove the old shape).
- Application schema (what a post or a follow is): kept out of the database entirely. Records are content-addressed CBOR blocks in a Merkle Search Tree; the SQL tables are storage plumbing (blocks by CID, record URI to CID, commits, backlinks). Record types are defined by Lexicons and evolve additively (new optional fields, new collections; readers ignore fields they do not understand), so most product evolution needs no database migration at all. A breaking change gets a new collection name.
- Derived data (AppView indexes): disposable. The repositories are the source of truth, so an indexer whose schema changes can drop its database and rebuild by replaying the firehose. Bluesky proved the storage layer itself is replaceable when it moved the PDS from PostgreSQL to per-user SQLite: a repo exports as a CAR file and re-imports anywhere.

The load-bearing insight: Bluesky can never edit a shipped migration in place, because millions of databases it does not control have already applied it. Append-only migrations plus a per-database version stamp are not hygiene; they are the only option at that topology. EPM has the same topology at smaller scale the moment a workspace exists on a machine the project does not operate.

## 4. The proposed EPM workflow

1. One version stamp per workspace, treated as the contract. Alembic already maintains an alembic_version table in each workspace database. Make that stamp the single source of truth the app reads at workspace open. Behind head means take the upgrade path. At head means no-op. Ahead of head (a newer workspace opened by an older app build) means refuse with a plain message that the workspace was upgraded by a newer version of EPM, never a schema error.

2. Append-only migrations, enforced mechanically. Freeze 0001_initial_schema.py permanently. Every schema change from now on is a new file (0002, 0003, and so on). Add a CI check that hashes each version file once it has shipped in a dist build and fails the build if a shipped file changes. Human discipline produced the C6 edit; the hash check is what makes the rule survive deadline pressure.

3. Automatic pre-migration snapshot. Before applying any migration, the app takes a backup through the existing encrypted-backup machinery, labeled with the version range (for example, pre-upgrade v1 to v3), and verifies it with the same validation a restore performs. Only then does migration start. This converts backup-and-restore from the upgrade path into the escape hatch, which is the role it is designed for.

4. Transactional, per-step application. Each migration runs inside a single SQLite transaction (SQLite DDL is transactional), and the version stamp advances only on success. A crash or failure mid-migration leaves the workspace byte-identical at its old version, still openable, with the snapshot as a second net. Required test that does not exist today: kill the process mid-migration, reopen the workspace, and assert the old version stamp and intact data.

5. Schema validation split by version. Validation expectations are keyed by the workspace's stamped version: a workspace is valid if it matches its own version's shape, and after migration completes it is validated against head. Wrong shape for your version stays fail-closed. Older version than the app becomes a normal, expected state instead of an error. This step is the direct structural fix for C6: the failure was not the CHECK change itself, it was validation demanding the newest shape from a database stamped with an older one.

6. Expand, migrate, contract for non-additive changes. Additive changes (new table, nullable column, new index) ship in a single release. Anything destructive or constraining goes in two steps across releases: the first release adds the new shape and the code tolerates both shapes; a later release removes the old shape in another migration. Standing rule: any app release must run correctly against the current head and the immediately previous version, so rolling back the app never strands a workspace. Bluesky tolerates mixed versions indefinitely across a fleet; EPM needs only one version of slack, because one operator runs one app version against their own workspaces.

7. Hosted mode gets a fleet pass. The PDS added an all-actor-stores-migrated check for exactly this purpose. EPM equivalent: an operator command that enumerates hosted workspaces, prints a version census, migrates idle workspaces in bulk immediately after a deploy, and lets the rest upgrade lazily on first open. Wire the census into the demo and pilot admission gate: a release is not considered deployed until the census shows zero workspaces behind head.

8. Keep product-schema evolution out of DDL where it is payload-shaped. EPM's relational core is its product and cannot go full content-addressed-blob the way the atproto repo does; referential integrity is a feature here, not overhead. But the parts of the product that already are payloads (intake retained sources, AI draft and governance payloads, evidence metadata) should carry an in-band payload_version and upgrade lazily at read time, with no DDL migration at all. Reserving migrations for the relational core keeps them rare, which is what makes steps 1 through 7 cheap to operate.

## 5. Worked example: finding C6 redone under this workflow

The hosted_operator widening of the audit_events actor CHECK constraint becomes a new migration, 0002_audit_actor_hosted_operator.py, performing the standard SQLite table rebuild inside one transaction: create the replacement table with the widened CHECK, copy all rows, drop the old table, rename, and recreate indexes. The reference-length CHECK lands in the same or a following migration by the same mechanism.

- 0001_initial_schema.py never changes, so the CI hash check passes.
- A workspace stamped v1 validates against the v1 shape; on open, the app snapshots it, applies 0002, advances the stamp, and validates against the v2 shape.
- A workspace created fresh under the new build is created at head directly.
- The hosted pair of demo workspaces is upgraded by the fleet pass at deploy time, and the version census proves it.
- Nobody restores anything by hand, and the observed C6 failure mode (a pre-existing workspace declared invalid by the new build) is impossible by construction rather than by care.

## 6. Release checklist

- Author the migration as a new version file; never edit a shipped one (CI hash check enforces).
- CI upgrades golden workspace fixtures, frozen at every shipped version, to head: migration success, per-version validation at each step, row counts and checksums on preserved tables, and smoke queries.
- CI includes the interrupted-migration test (kill mid-migration, reopen, old version intact).
- Release notes record the new head schema version.
- Hosted deploy runs the version census pass; the deploy is not complete until no workspace is behind head.
- If the change is non-additive, confirm the expand step shipped in an earlier release before the contract step ships.

## 7. Deliberate differences from Bluesky

- Compatibility window: one version of slack (head and head minus one) instead of indefinite mixed-version tolerance. EPM's topology (one operator, their own app install, their own workspaces) does not need more, and a bounded window keeps the code honest.
- No down-migrations. Recovery is the pre-migration snapshot restored into a new destination, using the restore machinery that already exists. SQLite down-migrations for table rebuilds are error-prone and would be exercised only in the worst moments.
- The relational core stays relational. Only payload-shaped data adopts the lexicon-style in-band versioning; the ledger, leases, and audit trail keep full SQL integrity.
- The version stamp already exists (Alembic). No new bookkeeping table is proposed; the work is in the open-time behavior, the validation split, and the enforcement checks.

## 8. Open questions

- Alembic configuration: confirm how env.py currently scopes transactions on SQLite, and whether transaction-per-migration needs to be set explicitly for step 4 to hold.
- Golden fixtures: where frozen per-version workspace databases live (repository versus release artifacts), and who refreshes them when a new version ships.
- Snapshot retention: how many pre-upgrade snapshots to keep per workspace, and whether they share the existing backup rotation.
- Fleet pass placement: whether the hosted version census belongs in the deploy scripts, an admin command in the app, or the qualification tooling.
- First adoption step: whether 0002 is the audit CHECK change itself (closing C6 through the new workflow) or a no-op rehearsal migration on the demo workspaces first.

## 9. References

- Gergely Orosz, Building Bluesky: a Distributed Social Network (The Pragmatic Engineer, April 2024; updated November 2024). The scaling section covers the move from PostgreSQL to ScyllaDB for the AppView and per-user SQLite for the PDS. https://newsletter.pragmaticengineer.com/p/bluesky
- Bluesky, Federation Architecture (May 5, 2023). The PDS, repository, and account-portability model this note borrows from. https://bsky.social/about/blog/5-5-2023-federation-architecture
- Kleppmann et al., Bluesky and the AT Protocol: Usable Decentralized Social Media (arXiv 2402.03239, February 2024). Repository as a Merkle Search Tree of records, Lexicon schemas, and why derived indexes are rebuildable. https://arxiv.org/pdf/2402.03239.pdf
- bluesky-social/atproto source tree. The PDS actor store (per-account SQLite databases, schema versioning and the migrator) lives under packages/pds/src/actor-store, with migrations under packages/pds/src/actor-store/db/migrations. https://github.com/bluesky-social/atproto
- DeepWiki index of the atproto PDS: repository operations and storage (per-user database layout, creation running migrations, record and blob storage). https://deepwiki.com/bluesky-social/atproto/4.4-repository-operations-and-storage
- AT Protocol account migration guide. The CAR-file export and import flow that makes the storage layer replaceable. https://atproto.com/guides/account-migration
- Hacker News discussion of the Bluesky PDS move to single-tenant SQLite, including the mixed-schema-version rollout discussion. https://news.ycombinator.com/item?id=38171322
