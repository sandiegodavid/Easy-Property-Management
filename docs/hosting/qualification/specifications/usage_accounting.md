# Logical usage and admission proof — H04, with H02

Case authority: [usage_accounting.json](usage_accounting.json); apply the
[common invocation/safety rules](README.md). H02 supplies the qualified physical
boundary; H04 supplies logical source accounting and crash-safe reservations.

## Setup and exact workload

Use two private synthetic workspaces with Free v1 **50,000,000 usable bytes**, separate
physical workspace/control/scratch reserves and separate administrative backup capacity.
Pin every fixture DB/file/resource/profile and source clock. The immutable input fixes
file byte sizes/digests, insert/delete/VACUUM choices, WAL/checkpoint transitions and
expected accounting formula; compute expected logical usage independently from the
source adapter. No physical `du`/statvfs value is substituted for logical allowance.

Use an empty source, one 1,024-byte blob linked twice, a distinct 2,048-byte blob,
retained active/archived evidence and exact-version remote fixtures, then deterministic
DB growth to allowance minus one/at allowance/plus one. Pin full DB snapshots/digests
and source-owned accounting units; the driver cannot silently change fixture size.

```bash
.venv/bin/python -m app.platform.hosted_proofs execute --spec ../docs/hosting/qualification/specifications/usage_accounting.json --inputs /private/proof/inputs.json --output /private/proof/report.json --phase run
```

H01 exits 3. H04 implements deterministic component, Docker and exact GCP driver runs.

| Case | Required workload / observation |
| --- | --- |
| `exact_free_usage` | Independently calculate committed logical usage for fixed fixtures and compare source result at each boundary. Units are decimal bytes, unknown is not zero. |
| `duplicate_retained_versions` | Repeated content, multiple links, archived links and distinct retained versions follow the declared formula; prove no accidental double/under-count from locators or missing content. |
| `sqlite_freelist_wal` | Delete rows without VACUUM, grow WAL, checkpoint/reopen and perform reviewed VACUUM fixture; compare declared logical usage with independently observed physical reserves. |
| `atomic_reservation_source_commit` | Reserve, commit source data/audit/receipt and reconcile; fault before/after each commit boundary. Only committed data counts and original reservations never silently disappear. |
| `interrupted_restart_reconciliation` | Stop after reservation, source commit and lost reconciliation in turn; reopen owning stores, inspect original receipts and resolve without duplicate publication/released unknown commitment. |
| `concurrent_admission` | Two synchronized growth requests each fit alone but not together. At most qualified capacity admits; run at least ten repetitions with distinct original keys and retain all outcomes. |
| `quota_commit_cleanup_failure` | Inject byte/inode/commit/fsync/publication-cleanup failures; retain original error and privacy-safe attention, prior business integrity and explicit unknown/unavailable state. |
| `unknown_never_unbounded` | Provider/collector/store failure, stale facts and malformed reservation deny unbounded growth; never publish zero usage/healthy state or change storage state for an outage. |
| `over_allowance_read_cleanup` | At/over allowance, permitted reads/export/logout/cleanup remain usable; new growth denied, existing data/receipts retained. Cleanup must not erase unresolved evidence. |
| `backup_separate_capacity` | At full usable allowance, verified archive copies/drill staging use separately admitted administrative capacity and do not inflate logical source usage. Separate host-capacity failure remains explicit. |

## Retention / cleanup

Record expected/actual byte tables, source/reservation/operation IDs, commit/fault
ordering, independent physical facts and retained file hashes. Use only disposable
stores; no release/schema migration or real user data. Preserve failed/unknown source
and reservation state for inspection; ownership-reviewed cleanup releases commitments
only after evidence proves it safe. Component results cannot qualify physical limits.
