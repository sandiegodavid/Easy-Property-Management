# H04.4 source lifecycle and logical storage accounting

H04.4 adds `initialize_binding` and `apply_policy` to `SourceLifecycle`,
implements durable Free-tier logical storage accounting and reservations in
`access.sqlite`, and exposes the authenticated `GET /api/hosted/settings`
endpoint per [HOSTED_MVP_H04_DESIGN.md](HOSTED_MVP_H04_DESIGN.md) (decision
D6).

- **Source lifecycle commands** (`hosted_access/infrastructure/source_lifecycle.py`):
  - `initialize_disabled` (`access_receipts.kind = 'initialize_binding'`):
    one-time Admin-only creation of `access_meta` (disabled, unbound,
    `usable_bytes = 50,000,000`, `policy_revision = 1`) + initial `usage_state`
    + `access_receipts` + `access_audit`. Idempotently replays matching
    `(kind, idempotency_key, request_hash)`, raises `SemanticConflict` on hash
    mismatch, and fails closed if `access_meta` already exists or `email_key`
    does not match `binding.issuer`.
  - `apply_policy`: Admin-only fenced policy update requiring current
    `access_epoch`, `expected_revision == meta.revision`, no active maintenance
    fence, and strictly advancing `policy_revision > meta.policy_revision`.
    Commits `access_meta`, `access_receipts`, and `access_audit` atomically.
- **Logical Free storage accounting & reservations**
  (`hosted_access/infrastructure/usage_accounting.py`):
  - `measure_logical_usage()` computes `committed_db_bytes = (PRAGMA page_count
    - PRAGMA freelist_count) * PRAGMA page_size` plus deduplicated
    `retained_file_bytes` across distinct `content_sha256` blobs with
    `storage_provider = 'local'` and `storage_state = 'available'`.
  - `UsageAccountingStore` manages `read_usage()`, `refresh_usage_state()`,
    idempotent `reserve()` (rejecting writes past `50,000,000` bytes with HTTP
    `507 hosted_storage_quota_exceeded`), post-commit `settle_commit()`,
    rollback `release()`, crash-safe `mark_unknown()`, and
    `reconcile_unknown()`.
- **Operator Settings API** (`hosted_access/api/operator_settings.py`):
  `operator_settings_router()` serves `GET /api/hosted/settings` behind exact
  origin and `__Host-epm-session` verification, returning the validated
  `Settings` contract (`surface = "operator_settings"`, `delivery_owner = "H04"`,
  Free pilot logical usage/allowance/freshness, `usageBreakdown`, honest
  `unavailable` backup protection until H05, `support_contact`, and zero paid
  upgrade actions) with `Cache-Control: no-store`.

## Local validation

15 focused Python tests passed across `test_h04_source_usage_settings.py` (3
tests) and `test_sessions.py` (12 tests). `ruff check` passed on all new files
and `ruff format --check` passed on all 4 modified Python files using
`application/pyproject.toml`.

| Area | Observed evidence |
| --- | --- |
| `initialize_binding` & `apply_policy` | One-time disabled binding seeds `access_meta` + `usage_state`, replays idempotently, conflicts on changed semantics, and denies re-initialization; `apply_policy` enforces monotonic `policy_revision` and `expected_revision` and replays idempotently. |
| Logical accounting & 50 MB admission | Deduplicated `retained_file_bytes` ignores duplicate `content_sha256` rows and `missing` locations; `reserve()` enforces `used + active_reserved + reserved_bytes <= 50,000,000` (`507` on overflow); `release()` frees headroom; `mark_unknown()` retains headroom until `reconcile_unknown()` re-measures and clears it; `settle_commit()` updates `usage_state` post-commit. |
| `GET /api/hosted/settings` | Denies missing cookie (`401`), wrong host/origin (`403`), and expired session (`401 renewal_required`); returns validated `Settings` contract with `FreeUsage`, `usageBreakdown.remainingBytes`, honest `unavailable` H05 protection, `support_contact`, and `Cache-Control: no-store`. |

H04.5 will compose the two-layer storage admission (logical `usage_accounting`
+ physical `prjquota` headroom) into `ManagedBusiness` and `operator_entry.py`
and verify hosted business workflows.
