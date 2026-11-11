# H02.11 scoped infrastructure acceptance and handoff

Delivered November 13, 2026. H02.1–H02.11 are delivered within the infrastructure
subset defined by D1–D13. **This is not qualified-release promotion or Pilot 0
acceptance.** H03–H05 application, identity, admission and recovery gates remain open.
No business ingress, invitations or consequential browser controls were enabled.

The [validation manifest](HOSTED_MVP_H02_11_VALIDATION.json) records exact tested
sources, commands, artifact hashes, environment, results and private evidence references.
The [acceptance register](../HOSTED_MVP_ACCEPTANCE.md#h02-consolidated-infrastructure-acceptance)
is the current gate summary. Earlier reports keep their original scopes and failures.

## Evidence and source boundaries

| Evidence | Result and limits |
| --- | --- |
| Current component regressions | 985 focused Python tests pass: host commands/receipts, schema/resources, packaging, launch/local transport, gateway/network/egress, capacity and shared contracts/proof/UI fixtures. This is not the full server suite. |
| Current safe-status browser regressions | Four Chromium cases pass: light/dark at 320/1280 pixels, keyboard operation, unavailable deep links and no API/command replay. This is a local hosted-status fixture, not deployed login/Admin/business UI acceptance. |
| Current native Linux/Docker subset on GCP | Two synthetic owners; private project trees, byte/inode/deleted-open faults, WAL/reopen, cross-UID denial, chmod/ioctl/mount/namespace restrictions, stable writer lock/replacement, rotating logs, stop-only systemd crash recovery and connected-firewall-loss containment passed. Native ABI control exited 42; 32-bit executable rejected with exit 159. |
| Current capacity artifact validation | Current native validator accepts the exact H02.10 measurement hash and policy/source pins. The two/five/six workload measurements were not rerun or assigned a new source identity. |
| Earlier exact GCP setup/reboot/network evidence | [H02.9](HOSTED_MVP_H02_9_HANDOFF.md) retains actual reboot, physical data disk, full gateway/stream/egress and scoped IAM/Tunnel proofs. Those drivers and production reboot/network paths are unchanged; H02.11 did not repeat the VM reboot or cloud/provider setup. |
| Earlier measured candidate capacity | [H02.10](HOSTED_MVP_H02_10_HANDOFF.md) retains actual two/five/six workloads and resource faults. Six is a measured population, not a product cap or authority to admit that many operators. |
| Consolidated lint | Ruff check and format check pass for all 113 Python files changed across H02, using `application/pyproject.toml`. No product Python, frontend source or tooling changed in H02.11, so no new frontend lint/typecheck run was required. |

The implementation source is commit `88140223ca46fac469438daa1ef68d30b5e8d55c`,
clean at execution start. Immutable selected-source manifest:
`a75ee26ae89a0cdf70fd81755495cb51b0a5f612c15990d5bf17624080466f7b`.
Compared with the H02.10 measured source, only the capacity artifact validator differs:
portable Linux errno constants replace inspecting-machine constants. Current native
validation passed; runtime policy, workload and budget are unchanged. Compared with
H02.9, the additional changes are the capacity planner/measurement tooling, the
sandbox `chmod` alias and its actor controls. Those security changes were re-proved
with current-source native and connected fixtures; old policy acceptance was not
silently inherited.

Target: `epm-h02-host`, instance `6955052781247608210`, project
`project-47b72bb7-ba90-42c9-910`, zone `us-west1-b`; kernel `7.0.0-1017-gcp`,
Docker `29.9.3`. Exact kernel bytes, filesystem UUID, fixture images and protected
non-secret configuration hashes are in the manifest. Proofs used fresh private
loop-filesystem laboratories on this target, not customer workspaces. H02.9/H02.10
retain the distinct real-data-disk evidence.

Current lab roots are recorded in the manifest. The connected fixture temporarily
replaced only the qualification host's network rules; the installed closed projection
was restored and verified against inventory/Caddy afterward. No running Docker
containers remained. The VM is **TERMINATED**, with its same 50-GiB data disk attached
and auto-delete disabled. The VM/disks, previous labs/principals, provider settings,
off-host backups and local Lima baselines were preserved. No old-host reset was replayed.

## Complete proof coverage stays explicit

The [v1 native subset report](HOSTED_MVP_H02_11_RUNTIME_SUBSET.json) inventories every
runtime specification case, including unrun or later-owned requirements. Actual scoped
passes have evidence hashes; the overall result is **unavailable**, because final
H04 concurrent admission and other whole-workflow proofs are absent or not rerun.
The [v1 final image/all-store report](HOSTED_MVP_H02_11_IMAGE_ALL_STORES.json) is also
**unavailable**: H03 hosted-access, H05 recovery/admin-recovery baselines and final
assets are prerequisites. It invents no execution times or image/schema digests for
those missing artifacts. Both reports pass the strict report/coverage validator;
CLI exit **2** means a valid non-passing report, not malformed evidence.

These overall results do not contradict H02's scoped delivery. D1/D2 explicitly
separate current structural/infrastructure acceptance from final artifact promotion.
Do not insert a qualified-release record, turn a scaffold into initialized schema,
or enable an unavailable application to make the aggregate report appear passed.

Existing Admin/Operator OCI candidates and the installed host-agent bundle retain
[H02.9's exact artifact pins](HOSTED_MVP_H02_9_VALIDATION.json). They were not rebuilt,
reinstalled or relabelled as current complete hosted releases in this slice. Current
source qualification runs from the immutable private snapshot. Final owners must
rebuild the real artifacts, run installed-without-checkout and complete six-store
proofs, and requalify changed runtime/configuration before promotion.

## Validation matrix

| Area | Evidence and remaining owner |
| --- | --- |
| Happy paths | Current native private runtime/connected checks, 985 component tests and four safe-status browser cases. H03/H04 own actual logged-in onboarding/operator workflows. |
| Invalid combinations | Current component stale epoch/revision/hash/resource/schema/qualification cases; native sandbox, quota-off, cross-UID and ABI negative controls. |
| Idempotency/retry | Immutable parent/child receipts, conflicting semantics, lost replies and retained commitments pass component tests. H04 owns real serialized admission/reconciliation; no native concurrent-admission pass is claimed. |
| Transaction rollback | Current component transaction/receipt/audit failure paths; native saturated WAL/reopen preserves acknowledged data. The full native explicit commit/fsync injection matrix is not newly qualified by the subset report. |
| Persistence/schema | Available Admin and inventory fresh init/structural constraints and matching read-only reinit pass. Actual reboot persistence retains H02.9's exact source/environment identity. Later owning stores remain unavailable. |
| Backup/restore | Consistent bounded synthetic SQLite backup and future recovery headroom retain H02.10's measurement. H05 whole-workspace/control/off-host recovery and operator-authorized restore are unestablished. |
| Query/bounds/performance | Bounded contract/collector/planner tests and H02.10 CPU/RSS/IO/PSI/latency retained. No new business-list query-budget, production SLO or broad workload claim. |
| UI/accessibility | Four current safe-unavailable browser cases; actual Admin, login, usage and recovery workflows remain with H03–H05. |

The first component run had 584 passes and ten socket bind failures from the restricted
execution sandbox. All ten passed with socket access (no product code or test expectation
changed). Together they cover the 594 selected cases; 391 additional shared-contract
cases passed separately. No skips or failed product checks remain in this selection.
H02.10's unexplained transient host-memory refusal remains retained: future admissions
must still reject unknown/out-of-reserve observations, even though a later run passed.

## H03–H05 handoff

| Owner | Delivered input | Required completion before enabling its workflow |
| --- | --- | --- |
| H03 | Main-Admin structural closure, typed scope/epoch/intent contracts, exact registered-host/closed gateway and unavailable hosted launch. | Managed identity/MFA, exact invited ownership, one-use handoff/host-only sessions, source revocation and hosted-access resources/assets. Current identity must gate every positive route/start; projections do not grant authority. |
| H04 | Inventory UID/project/resource-generation allocation, immutable child effect receipts, monotonic ingress fences, protected transport, pure capacity planner and measured candidate budget. | Real source-owned provisioning/admission with serialized durable holds/CAS, concurrent/lost-response recovery, Free 50,000,000-byte logical metering, Admin-lite/operator UI and safe asynchronous status. Count pending/unknown/retained holds and recheck actual headroom; no cohort cap or test-authority bypass. |
| H05 | Private persistent workspace/control/scratch, stable writer lock, guarded stop/deny boundary, reserved physical recovery headroom; stage/switch effects remain unavailable. | Separate owning recovery/admin-recovery stores, encrypted off-host points/keys/control recovery, source fencing and operator-authorized separate-staging restore. Reserve-only and synthetic SQLite backup do not qualify recovery or authorize empty reinitialization. |
| Final artifact owners / H06 | Exact scoped reports, runbooks, specification coverage and retained failure evidence. | Complete all six store families, final assets/installed manifests and image proofs; review promotion on exact artifacts, then complete Pilot 0 identity, admission, recovery, UI and support gates before invitations. |

## Reproduction and evidence

Use the exact focused commands in the validation manifest from `application/`.
For explicit current-source native commands and protected input hashes, use its
`native_commands`, private `inputs.json`, and the [GCP](../../deployment/gcp-host-setup.md),
[sandbox](../../operations/runtime-supervision.md) and
[lab](../../deployment/linux-development-and-qualification.md) runbooks. Choose new
snapshot/output/lab paths; never patch tested source, adopt a populated quota tree,
reformat the retained disk or replay a completed reset.

Private raw evidence is retained at
`/Users/dcai/Desktop/Property-Management-Data/hosted-mvp-qualification/H02.11/`.
The validation manifest maps safe references such as `private:H02.11:runtime-result.json`
to that directory and records hashes. Keep original H02.9/H02.10 inputs/results and
failures alongside their original reports; JSON validity alone is not evidence
verification, independent security review or release authorization.
