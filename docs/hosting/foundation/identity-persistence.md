# Identity persistence and expiry cleanup

[H03 design](../design/HOSTED_MVP_H03_DESIGN.md) · [Contract baseline](identity-contracts.md) · [Schema catalog](../../database/overview.md)

H03.2 delivers current resource-owned Admin identity and per-Operator access schemas,
retained-data validation, explicit disabled binding and dependency-aware cleanup.
Authentication, provider verification, claim/session orchestration and public sign-in
remain later H03 work. No provider, cloud host or real Operator state changed here.

## Resources and initialization

`application/database/admin-migrations/versions/admin_0001_initial.py` now owns the
17-table main-Admin baseline, including attempts, email continuations, managed identity
sessions and identity-command receipts. Existing Admin sessions/handoffs retain their
accepted managed-proof and redemption fields. Identity operations remain separate from
infrastructure operations; all local identity references use RESTRICT.

`application/database/hosted-access-migrations/versions/access_0001_initial.py` owns the
complete eight-table access baseline, including structural policy/usage dependencies.
It uses the owning transactional runner rather than runtime DDL. No migration,
compatibility translation, URL, account, policy, session or usage seed is supplied.
The two recovery resource sets remain unavailable; schema readiness grants no access.

Trusted composition calls `initialize_store(HostedStore.HOSTED_ACCESS, destination,
application_directory=installed_root)` beneath a private canonical directory. Fresh
creation reserves an exclusive 0600 file and rolls all DDL back on failure. An existing
matching store is checked read-only. Partial/foreign/old-schema/nonprivate/linked stores
reject without repair or replacement. Direct Alembic commands cannot bypass the runner.

A separate caller-owned transaction may call `bind_disabled_access` with a typed
`DisabledAccessBinding` containing the owning H04 admission/policy and exact assignment
inputs. It inserts only an unclaimed, disabled singleton. Matching retry is read-only;
changed input or an already changed binding conflicts rather than resetting authority.
The adapter checks consistency, not the admission proof's authenticity. H04 must verify
that proof before calling it. Usage remains absent/unknown; no allowance is inferred
from an empty database or from the physical filesystem limit.

## Validation and retention

Resource-derived validation compares the exact schema, revision, CHECKs, FKs, indexes
and triggers, then checks retained rows with the H03 state contracts. It decodes return
paths, validates closed typed receipt payloads and checks local identity/purpose/target/
proof relationships. Unknown result fields and secret-bearing receipt JSON reject.
Historical revoked/stale rows remain valid records, without becoming request authority.
Validation streams fixed table queries and makes no provider/source RPC.

`cleanup_identity` runs only in a caller-owned transaction with FK enforcement. It
obtains the SQLite writer lock before choosing candidates and rechecks dependencies
inside each delete. It examines at most 100 candidates across the entire pass, retains
rows on FK rejection and leaves commit/rollback to its caller.

- Keep at least 24 hours after terminal expiry/result; this is a minimum hold.
- Retain live remembered lineages and pending/unknown commands regardless of age.
  Redeeming reservations need explicit reconciliation; the cleanup worker does not
  convert them into expired successes or assume provider rollback.
- Remove eligible Admin sessions, continuations, handoffs, commands, attempts and managed
  sessions in dependency order. Repeated passes reclaim eligible leaves as holds retire.
- Source session replacement chains retire leaf-first. Source rows with logical handoff
  or continuation references remain held unless the caller supplies bounded IDs from
  authenticated owning reconciliation performed outside the transaction. Missing or
  unavailable observations mean retain, even after a long timeout.
- Do not cascade, rewrite FKs, erase original receipts/audits, delete unfinished forms
  or release unknown usage reservations. Cleanup performs no cross-store transaction.
  Expired draft-lease rows remain owning edit-lease cleanup's responsibility.

No metadata-scrubbing worker is introduced. Retaining immutable request/identity facts
is safer than altering them while a dependent outcome remains unresolved. Scheduling,
aging-hold alerts and authenticated source-observation acquisition belong to the later
owning identity services.

## Retired composition

The runtime `hosted_access/infrastructure/schema.py` creator is removed. The old
`SQLiteHostedSessionStore` name is a temporary fail-closed import guard, not a second
store adapter: construction and initialization return safe 503 before filesystem or
SQLite access. The obsolete bootstrap attaches no auth, session or edit routes.
The user approved closing this path during H03.2; there is no supported Cloudflare/demo
schema mode or migration path. The normal local Operator remains independent and its
focused workflow regressions pass.

Old provider/session-specific setup tests are replaced with denial/file-preservation
and current-schema tests. Independent transport, serialization and local workflow
checks remain. The legacy `scripts/hosted_browser_server.py` fixture still targets the
retired flow and cannot qualify H03 sign-in; H03.11/H03.12 must replace that harness with
the new authentication composition. No hosted browser acceptance is claimed here.

## Validation matrix

| Area | Focused evidence |
| --- | --- |
| Happy paths | Complete empty baselines, explicit disabled binding, exact read-only reinit and installed-resource initialization outside checkout/CWD. |
| Invalid combinations | Missing/wrong/partial/linked resources or stores; invalid identity/purpose/deadline/state fields, malformed/extra receipt fields and encoded auth return paths reject. |
| Retry/idempotency | Binding retry leaves data unchanged; changed binding rejects; immutable intent/results, terminal guards and INSERT OR REPLACE denial preserve original evidence. |
| Rollback | Baseline DDL, metadata binding and bounded cleanup roll back in caller transactions; no implicit authority or usage rows appear. |
| Persistence/schema | Exact columns/checks/indexes/local FKs, current-resource drift detection, typed retained results and reverse dependency indexes. |
| Backup/restore | Private SQLite snapshots reopen under the current baseline without recreating authority. Business archive exclusion and real recovery activation remain H03.10/H05 integration gates. |
| Query/bounds | Validation query count stays constant as rows appear; cleanup caps candidates at 100, retains unknown/live-lineage evidence and eventually reclaims dependency chains. |
| Local/obsolete path | Local app/task/recovery workflows remain usable; obsolete initializer/composition rejects before probing or mutating any destination. |

Validation completed November 14, 2026: **849 focused tests passed, one skipped**.
The skip is the existing opt-in Linux storage qualification, which requires an explicitly
provisioned disposable Linux quota volume; no native proof was simulated. The focused
run covered hosted-access tests, current schema/resource/artifact/effect/private-port
regressions and the changed release-demo tests. Ruff lint and format checks passed on
all **27 changed Python files**; 226 local Markdown links resolved and `git diff --check`
passed. No frontend files changed. This is schema and component evidence, not provider,
deployed-browser, native-host or release acceptance.
