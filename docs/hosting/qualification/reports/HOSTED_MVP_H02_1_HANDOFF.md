# H02.1 contract and input baseline

H02.1 candidate-baseline preparation is delivered on `hosted_mvp`, starting at
`2180160365725f72a067fca898d549e59781df74`. The
[input baseline](HOSTED_MVP_H02_1_INPUT_BASELINE.json) pins 23 current source,
dictionary and specification files. This is preparation evidence, not a passed host
qualification report, release row or permission to dispatch effects.

## Delivered contracts and decision mapping

| Accepted decision | H02.1 delivery and later gate |
| --- | --- |
| D1 | Explicit main-Admin closure of 13 tables checked against all three owning dictionaries. H02.2 supplies DDL with local FKs intact. Initialization populates only `control_meta`. |
| D2 | Candidate-only build-input contract rejects qualified acceptance and open customer ingress. Missing owning resources remain unavailable; candidates never populate qualified releases. |
| D3 | Non-root UID/GID range contract rejects inverted, duplicate-reservation and exhausted ranges. Selected ranges require actual host/system/container collision checks before persisted allocation in H02.3. No automatic recycling. |
| D4 | Typed held/eligible/blocked ingress request resolves registered binding/generation rather than accepting an origin/path. Eligible requires both source-identity and resource-readiness references; adapters must authenticate and verify them. |
| D5 | Versioned deterministic child UUID/key includes original parent reference, scope, kind, binding, generation and slot. Consequential fences remain in canonical request hashes, so changed fences cannot silently allocate another effect. Golden-vector tests fix serialization/namespace behavior. H02.3 must atomically reserve and replay receipts. |
| D6 | Literal single restricted-supervisor restart owner, Docker restart `no`, and mount/quota/inventory/external-deny checks. Actual start/reboot enforcement remains H02.5. |
| D7 | Protected candidate selects Ubuntu 24.04 amd64, non-Spot 2-vCPU/8-GiB target with 20-GiB boot and 50-GiB balanced data disks, cgroup v2/ext4. Exact image/tool candidates are recorded below. |
| D8 | Build inputs fix direct UID mapping; user-namespace remapping rejects. New architecture/kernel/seccomp combinations require fresh native and Docker proofs. |
| D9 | Capacity remains explicitly unmeasured; no invented physical ceilings or restore reserves. H04's 50,000,000-byte logical allowance is separate. Backups do not count toward operator quota. |
| D10 | Stage/switch vocabulary retained for H05, no implementation or effect dispatch added. |
| D11 | Existing local and old hosted launch unchanged. Stable control-tree lock and fresh composition remain H02.5/H02.7. |
| D12 | Contracts and proof plans only; no H03 identity proof, H04 policy/rebind behavior or H10 scheduling claim. |
| D13 | Protected setup selection retained outside Git. Revised runtime proof plan adds gateway, metadata/egress and scoped-secret checks, none executed here. |

The 13-table closure is `control_meta`, `storage_policies`, `qualified_releases`,
`component_deployments`, `operators`, `invitations`, `admin_principals`,
`admin_sessions`, `login_handoffs`, `operations`, `operation_events`, `admin_audit`
and `workspace_recovery_status`. Recovery tables belong to the separate recovery
store. In particular, operations/assignments/operators/principals and qualified
release/component pairs must retain their local FK relationships. The nullable
assignment operation reference permits the dictionary's insert-then-link sequence;
it does not justify disabling FK checks. No table definitions were added here.

The new contracts are preparation seams, not replacements for the live legacy
composition or an implemented HostPort. H02.3 must bind the original parent from its
authenticated owning lookup before deriving children, check current inventory fences
even for unseen keys, return historical receipts without replaying stale effects,
and keep external work outside writer transactions. No durable enforcement is
claimed by pure hash/UUID tests.

## Protected inputs and exact candidate pins

The user chose to retain the existing GCP project/domain and replace the old demo VM
and its disks. The exact documented target selection is in private input reference
`h02-1-candidate-inputs-v1`, whose content hash is recorded in the baseline. Reset
belongs to H02.9 and has **not** run. The protected setup will identify/reconfirm
actual devices and credentials before any destructive operation. H02 does not inherit
the old host's access grants, expiry rules, machine size or qualification results.

| Input | Selected candidate / pin source |
| --- | --- |
| GCP Ubuntu image | `ubuntu-os-cloud/ubuntu-2404-noble-amd64-v20261105`, numeric image ID `1892012953239034119`; public Compute image metadata, not a guest/kernel observation. |
| Python amd64 image | `3.14.10-slim-bookworm`; selected platform manifest digest in the baseline, resolved from `3.14-slim-bookworm` and SHA-256 verified against returned manifest bytes. No build consumes the moving tag. |
| Docker Engine / CLI | `5:29.9.3-1~ubuntu.24.04~noble`; official Ubuntu Noble amd64 index package checksums. |
| containerd | `2.4.2-3~ubuntu.24.04~noble`; same official package index. |
| Buildx | `0.38.1-1~ubuntu.24.04~noble`; same official package index. |
| Caddy | `v2.11.9`, Linux amd64 tarball; official GitHub release asset SHA-256. |
| cloudflared | `2026.10.7`, Linux amd64 binary; official GitHub release asset SHA-256. |

Exact URLs/checksums are in the baseline. Package/release metadata checksums have
not been independently checked against downloaded binary bytes or signatures. Python
OCI layers were not pulled. The GCP family query was resolved to the exact image
above; no VM was inspected or changed. These selections are not installed artifacts.

A [33-wheel candidate inventory](HOSTED_MVP_H02_1_DEPENDENCY_CANDIDATES.json)
records downloaded distribution bytes and hashes. The resolver ran on macOS with
Linux wheel tags; it does not establish Linux environment-marker closure. Nothing
was installed. H02.4 must resolve/install inside the selected Linux image.

The protected record is intentionally `candidate_incomplete_not_dispatchable`, not
a validated `HostBuildInputs`. Remaining exact inputs are installed kernel/binary
identity, Linux dependency lock/distribution hashes, protected account/credential
bindings, verified devices and measured reserves. The strict complete-input contract
requires explicit pins instead of silently substituting the local Mac environment.
Runtime measurements and actual qualification remain H02.8–H02.10; build/dependency
resolution is an H02.4 prerequisite. The user explicitly approved this H02.4/H02.8 handoff; H02.1 is complete as
candidate-baseline preparation. These remaining gates cannot be treated as passed.

## Focused validation matrix

| Area | Result / scope |
| --- | --- |
| Happy paths | Deterministic child identity, held/blocked inputs, complete synthetic candidate inputs and all restart checks. |
| Invalid combinations | Wrong effect/scope, missing eligible evidence, raw origin/path, invalid/exhausted UID range, missing digest, unsupported platform and competing restart owner rejected. |
| Retry/idempotency | Golden vector and distinct parent/slot/generation identities; changed fences keep the child key but change request hash. Existing original-result port tests retained. No durable retry execution. |
| Transaction rollback | Not executed; no storage or effect adapters in this slice. Revision-2 proof plan requires failed-reservation no-effect/crash reconciliation checks. |
| Persistence/schema | Main-Admin dictionary closure test; no DDL, initializer or runtime schema validation implemented. |
| Backup/restore | No backup or restore executed; stage/switch remains later-owner work. Historical evidence untouched. |
| Query/N+1 | No database/provider fan-out added to application requests. Read-only ingress input selects one registered binding. |
| Isolation | Revised runtime specification revision 2 adds eight cases; the 19 runtime cases are planned, not passed. |

From `application/`:

```bash
.venv/bin/python -m pytest apps/server/app/platform/tests/test_hosted_effect_contracts.py apps/server/app/platform/tests/test_hosted_ports.py apps/server/app/platform/tests/test_hosted_proofs.py apps/server/app/platform/tests/test_hosted_ui_contracts.py -q --tb=short
.venv/bin/ruff check apps/server/app/modules/host_agent/application/build_inputs.py apps/server/app/modules/host_agent/application/effect_contracts.py apps/server/app/platform/tests/test_hosted_effect_contracts.py
.venv/bin/ruff format --check apps/server/app/modules/host_agent/application/build_inputs.py apps/server/app/modules/host_agent/application/effect_contracts.py apps/server/app/platform/tests/test_hosted_effect_contracts.py
```

**305 passed**; Ruff check and format check passed for all three changed Python
files. No frontend changes or full test suite. No resource runner, privileged
executor, host reset, cloud deployment or customer access was enabled.
