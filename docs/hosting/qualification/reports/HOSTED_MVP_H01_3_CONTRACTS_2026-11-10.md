# H01.3 — Bounded shared values and operation envelopes

Delivered November 10, 2026 on `hosted_mvp`, starting from clean commit
`cc98285e2ae78d53694f929917d9b87034248321` (H01.2 delivered).
**Pure shared contracts only; no durable operation repository or effect dispatch.**

## Delivered boundary

The [hosted-contract package](../../../../application/apps/server/app/platform/hosted_contracts/README.md)
owns common values/envelope mechanics. Owning action payloads, actors, authorization,
reference resolution, per-store transactions and production composition remain
H01.4/H02–H05 work. No FastAPI, ORM, Docker, cloud-client or owning-module import
exists in the package. Existing domain/receipt/session/schema contracts remain unchanged.

| Module | Delivered contract |
| --- | --- |
| `values.py` | Strict canonical lowercase UUIDs; signed-64-bit positive revisions/epochs; nonnegative counts/UTC epoch milliseconds; lowercase SHA-256; bounded safe codes, registered references and idempotency keys; closed component names; explicit deployment/workspace scope. |
| `semantic.py` | Frozen, extra-forbidden typed intent with all declared consequential fields; deterministic compact sorted-key UTF-8 JSON and SHA-256; 16 KiB/nesting bounds; no arbitrary mapping, mutable list, float, bytes or secret-wrapper hashing. |
| `operations.py` | Scope/action/fence-bearing generic intent, checked request hash, original operation reference, declared volatile transport metadata, all six outcome states, pure matching-original comparison and explicit unknown timeout observation. |
| `reads.py` | Known/stale versus unknown/unavailable freshness, source/capture context and bounded versioned continuation; changes to scope/filters/capture/source/ordering require restart. |

The package guide specifies default/null semantics: defaults are included, so omitted
and explicitly supplied defaults hash identically; null is not empty text. Owners
must use tagged variants when absence and null mean different actions. Owners normalize
text before hashing. Array order remains meaningful. Serializer exclusions cannot
silently remove a consequential field from canonical intent. Persist `canonical_bytes`
and hash, not arbitrary transport JSON or a reconstruction from current assignment.

Deployment, scope, component, kind, expected revision and access epoch participate
in the intent hash. Release, initial-data/seed bundle, capacity profile/commitment and
ordered resource changes are exercised through **synthetic owning fixtures**, not
new production provisioning DTOs. Their typed validation runs before hashing.

Operation ID/key select the original lookup; correlation ID/sent-at are the explicitly
declared volatile transport envelope outside intent. Matching deployment/scope/kind/
key/hash returns the retained original object/identity, including pending/unknown
outcomes. Changed semantics conflict. A missing receipt is not permission to execute.
A timeout creates only an unknown observation requiring original-result inspection;
it cannot overwrite a retained terminal result or initiate a second effect.

Snapshot state validation prevents success without a typed result, committed results
on unresolved/failed states, missing failure reasons and unresolved outcomes without
an explicit next action. Repository-level terminal immutability, state transitions,
authenticated lookup, atomic key reservation and effect reconciliation are not proven.

Cursor envelopes bound pages to 50 and ordering positions to eight 1,024-character
strings. They are not signed/opaque token encoders, authentication proofs or query
implementations. Owning adapters must authenticate/authorize, verify trusted source
context, implement token bounds and execute bounded queries. Unknown usage cannot
be fabricated from a missing observation.

## Focused verification

From `application/`:

```bash
.venv/bin/python -m pytest apps/server/app/platform/tests/test_hosted_contracts.py apps/server/app/platform/tests/test_api_errors.py -q --tb=short
```

**88 passed in 0.46s.** This includes existing API problem regressions, not browser,
provider, native, database or hosted deployment tests.

```bash
.venv/bin/ruff check apps/server/app/platform/hosted_contracts/__init__.py apps/server/app/platform/hosted_contracts/values.py apps/server/app/platform/hosted_contracts/semantic.py apps/server/app/platform/hosted_contracts/operations.py apps/server/app/platform/hosted_contracts/reads.py apps/server/app/platform/tests/test_hosted_contracts.py
.venv/bin/ruff format --check apps/server/app/platform/hosted_contracts/__init__.py apps/server/app/platform/hosted_contracts/values.py apps/server/app/platform/hosted_contracts/semantic.py apps/server/app/platform/hosted_contracts/operations.py apps/server/app/platform/hosted_contracts/reads.py apps/server/app/platform/tests/test_hosted_contracts.py
```

Ruff check/format check passed for all six changed Python files using
`application/pyproject.toml`. Frontend checks are not applicable. Documentation links,
new-file whitespace and `git diff --check` passed. No full suite or live resources used.

## Contract validation matrix and limits

| Area | Proven | Remaining owner proof |
| --- | --- | --- |
| Happy path | Typed values, concrete generic JSON round-trips, six valid outcomes, freshness and cursor context. | H01.4 real owning DTO/port/manifest contracts; H02–H05 usable implementations. |
| Invalid combinations | Noncanonical IDs; bool/float/integer overflow; malformed/oversize codes/refs; missing consequential fields/fences; extra input; unsafe values; false completion/freshness; invalid seed fixture; cursor bounds/version/context mismatch. | Owning closed action vocabularies, actual authority/policy/lifecycle and resource resolution. |
| Hash/idempotency/retry | Fixed exact UTF-8/hash vectors, key order, normalized Unicode, defaults/null, array order, all fixture fields/scope/fences, matching original identity, changed-key/intent conflict and unknown timeout. | Authenticated original lookup, unique-key reservation and host/source durable deduplication across loss/restart. |
| Rollback | No effects or mutable shared state; failed validation/comparison cannot modify the supplied frozen receipt. | Real short owning transactions, commit failure and cross-store reconciliation; no mocked rollback claim. |
| Persistence/schema | Scalar conventions align with master; canonical request/result size bounds and no secret-wrapper serialization; no SQL/schema changes. | Owning allowlisted records and real constraint/retained validation. Plain strings are not scanned for secrets; owners must exclude sensitive fields. |
| Backup/restore | No stores or recovery grants are created or replaced. | H05 authenticated recovery, integrity/key/manifest/restore proofs. |
| Query budget | Package has no persistence/provider clients or queries. | Owning bounded/set-based queries and actual snapshot/cursor behavior. |
| API mapping | Existing shared `domain_problem` maps semantic conflict to 409; shared validation maps malformed to 422 and standard size violations to 413. No second HTTP policy added. | Owning routers compose the existing mapper with actual application failures. |
| UI | No UI or production endpoint introduced. | H01.6 fixtures; H03/H04/H05 accessible end-to-end workflows. |

Next: H01.4 owning application ports and compatibility manifests. H01.4–H01.7 and
all fresh hosted runtime/native/cloud/end-user gates remain open. No older active
implementation is removed because these values do not replace a wired consumer yet;
superseded code must be removed when its owning replacement is integrated.
