# Internal workspace and separate control recovery proof — H05

Case authority: [recovery.json](recovery.json). Apply the [common safety/report rules](README.md)
and the H01 recovery security boundary. No offline customer restore/decrypt executor
is introduced. H05 must finish its detailed key/engine/phase-switch/identity design
before implementing this proof; H02/H03 supply runtime and current identity evidence.

## Setup and invocation

Use two private synthetic operators, separate access/recovery/business stores, main
Admin plus separate Admin-recovery store, dedicated encrypted off-host objects and
protected current bootstrap/key references. Pin encryption/key policy (no key bytes),
object/manifest scopes, scheduler clock, seven-night retention, schema/API versions,
file inventory and incremental-chain policy. Private administrative staging is outside
operator allowance and independently capacity-admitted.

Workload A: empty workspace then recorded DB change, file-only change, duplicate blob,
archived links/reasons/history and a known original command receipt. Workload B: unrelated
workspace with distinct identity/data/key scope. Capture seven daily points and an eighth
changed point, plus unchanged and commit-before-crash variants. Pin every expected
logical ID/link/audit/verified-byte comparison in the private workload manifest.

```bash
.venv/bin/python -m app.platform.hosted_proofs execute --spec ../docs/hosting/qualification/specifications/recovery.json --inputs /private/proof/inputs.json --output /private/proof/report.json --phase run
```

H01 exits 3 before touching inputs. Component, actual Docker/GCP and deployed-browser
runs are separate reports; no local mock proves off-host custody, runtime repair or MFA.

| Case | Required workload / negative control / observation |
| --- | --- |
| `consistent_scheduled_capture` | Concurrently mutate DB/files while scheduler captures; validate one consistent source point with exact DB/file membership and committed receipt/audit. Starting a job is not protection success. |
| `unchanged_file_only_checkpoints` | Compare unchanged, file-only and DB-change captures; distinguish proven unchanged from stale/unknown source, with correct checkpoint/point coverage. |
| `source_commit_crash` | Stop after source commit and before checkpoint/catalog acknowledgement; restart and reconcile exact commit coverage without inventing a new proof or losing the committed command. |
| `encrypt_key_custody_readback` | Unattended encrypted capture, scoped upload and full verified readback; prove recovery inputs/key references available outside the host. Reject unavailable/wrong key and unverified upload. |
| `seven_points_incremental_retention` | Produce eighth daily point and run retention; keep seven valid nightly points and all referenced chain objects. Failed new readback must never prune an older good point. Record exact object/ref counts. |
| `corrupt_missing_object_key` | Remove/corrupt a manifest/object and deny key access in dedicated copies. Restore rejects before switch, preserves prior state and reports safe reason without plaintext/provider responses. |
| `admin_outage_independence` | Stop/unavailable central Admin while operator capture/catalog/authorized restore runs. No main Admin transaction or approval required for workspace recovery. |
| `corrupt_business_recovery_mode` | Corrupt disposable business DB; minimal operator recovery starts without business bootstrap and authenticates current authority before listing/previewing own eligible points. |
| `clean_runtime_repair` | Fence/replace only compatible stopped runtime; retain IDs/account/data/access/recovery/key references, revoke old sessions and require fresh operator-selected restore. No empty initialization or seed. |
| `operator_step_up_exact_confirmation` | Actual operator preview, qualified recent strong step-up and exact point/workspace/action confirmation; stale/weak/stolen ordinary cookie and Admin session alone fail before restore admission. |
| `cross_workspace_replay_path_key_denial` | Try B's point/key/manifest/ID, replay confirmation and substitute destination/object reference. Deny without data disclosure; only source-selected own-workspace targets allowed. |
| `crash_safe_locator_switch` | Inject interruption at drain, connection closure, staging validation, prior-tree preservation, switch/fsync and post-switch receipts. Restart reconciles one original restore and never exposes mixed trees or two writers. |
| `forensic_prior_tree` | Preserve corrupt pre-state as forensic evidence, not a verified recoverable point. Compare restored IDs, links/archive reasons/audits/verified bytes and retain exact prior tree until explicit policy cleanup. |
| `separate_admin_recovery_loss` | Independently corrupt main Admin then Admin-recovery copies. Use current protected bootstrap/MFA independent of restored principal/session rows; retain local recovery operations/audit and no cross-store FKs. |
| `whole_host_control_loss` | Reconstruct clean disposable host from verified off-host registry/inventory/config/key inputs, fence old source and restore under exclusive authority. No permanently running outside service or stale jobs/sessions revived. |
| `no_offline_workspace_bypass` | Inventory package/CLI/routes and attempt unauthenticated/offline workspace restore/decrypt/export bypasses. All unavailable; restricted platform control recovery is not customer workspace authority. |
| `point_age_duration_traffic` | Measure actual verified point age, capture/readback/restore duration, retained bytes and transferred bytes for each workload. Record missing capacity/provider limits and achieved results, not a contractual SLA. |

## Evidence / cleanup

Retain sanitized operation/manifest/checkpoint/switch phase IDs, hash comparisons,
actual object membership, current-auth denial results, key-policy/configuration hashes,
measurements and crash recovery observations. No decrypted customer data, secret keys,
raw tokens or usable grants enter git. Archive/restore staging failures preserve the
original failure plus cleanup identity; unknown effects remain visible. Keep prior
valid points, chain objects, forensic trees and failed switch evidence until explicit
ownership-verified cleanup. Never automatically delete orphaned/unknown content.
