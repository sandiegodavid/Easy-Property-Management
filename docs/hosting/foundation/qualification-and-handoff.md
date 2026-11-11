# Qualification, evidence and remaining delivery

[Foundation guides](README.md) · [Acceptance register](../qualification/HOSTED_MVP_ACCEPTANCE.md) · [Evidence index](../qualification/reports/README.md#infrastructure-evidence-by-topic) · [Proof specifications](../qualification/specifications/README.md)

## What is delivered

The infrastructure subset has component, installed-candidate, native Linux/Docker,
exact GCP setup/reboot and measured warm-capacity evidence. Recorded consolidated
validation on November 13, 2026 passed **985 focused Python tests**, **four local
hosted-status Chromium cases**, and Ruff check/format check on **113 infrastructure
Python files**. No full application suite ran. The final qualification VM/data disk
were stopped and retained; business ingress, invitations and release promotion stayed off.

The [consolidated source/command manifest](../qualification/reports/HOSTED_MVP_H02_11_VALIDATION.json)
pins commit `88140223ca46fac469438daa1ef68d30b5e8d55c` at execution start, immutable
selected sources, exact commands, target/tool/configuration facts and raw-evidence hashes.
These are recorded checks, not tests rerun by this documentation consolidation.

Scope matters: local contract tests do not prove native root isolation; Desktop
AMD64 under ARM64 emulation is not native AMD64; ARM64 labs do not qualify GCP;
a healthy process or closed page is not an authenticated usable operator workflow.
Historical reports retain their own source/artifact identity, not a renewed pass.

## Coverage by topic

| Area | Delivered evidence and practical limit |
| --- | --- |
| Packaging and launch | Separate pinned candidates, Linux dependency closure, outside-checkout installed probes, available schema validation and safe unavailable UI. Final owning resources/assets remain unavailable. |
| Inventory and commands | Real structural baselines/FKs/triggers, immutable parent/child identity, short reservation/result transactions, original-result recovery and protected peer-checked transport. Final authenticated owning admission remains open. |
| Runtime and storage | Two private principals, kernel project enforcement, read-only roots/control lock, actual sandbox/compat/second-writer/replace/log/resource tests, stop-only crash recovery and connected firewall-loss containment. |
| Network and cloud | Exact-host/dual-stack/metadata/egress/stream denials, scoped IAM/Tunnel, real closed projection and actual retained-data-disk/guest reboot. Positive identity routing is not delivered. |
| Capacity | Two/five/six actual application/SQLite/backup workloads and faults. Pure physical planner and retained-limit accounting; no durable serialized admission, production SLO or whole-workspace recovery claim. |
| UI and local compatibility | Light/dark, narrow/wide, keyboard/deep-link/no-replay safe-status checks; default local launch/transport regressions. Not Admin/login/business browser acceptance. |

| Validation area | Evidence / remaining boundary |
| --- | --- |
| Happy paths | Current-source component/native/connected/ABI checks; earlier exactly pinned installed/reboot/capacity results. |
| Invalid combinations | Malformed scope/identity/paths/resources, stale revisions/fences, wrong images/schemas/peers and unknown capacity reject; native quota-off, escape and cross-UID controls retained. |
| Idempotency/retry | Matching immutable child receipts return/inspect original results; changed semantics conflict. Concurrent durable admission and parent application orchestration remain with the admission owner. |
| Transactions/rollback | Failed reservation commits dispatch no external effects; result/receipt observations commit together. Native saturation/reopen preserves acknowledged SQLite data; no cross-store rollback claim. |
| Persistence/schema | Available Admin/inventory fresh init and read-only reinit pass. Actual reboot/lock/project identity proof retains original pins. Missing later resources remain unavailable. |
| Backup/restore | Consistent synthetic SQLite scratch backup and physical headroom measured. Encrypted off-host/business/control restore, key custody and operator-authorized switch remain unavailable. |
| Query/bounds/performance | Bounded contract/kernel/cgroup/receipt observations and measured CPU/RSS/IO/PSI/latency; no recursive edit-time scan, general business query-budget or scaling claim. |

## Complete reports versus scoped acceptance

The [v1 native subset report](../qualification/reports/HOSTED_MVP_H02_11_RUNTIME_SUBSET.json)
includes every runtime-specification case. Its overall result is **unavailable**:
scoped executed passes coexist with unrun or later-owned whole-workflow requirements,
including real concurrent admission. The [final image/all-store report](../qualification/reports/HOSTED_MVP_H02_11_IMAGE_ALL_STORES.json)
is **unavailable** until hosted-access, recovery/admin-recovery and final application
assets exist. It invents neither execution times nor missing artifact/schema digests.

Both validate in the strict [v1 report format](../qualification/specifications/REPORT_FORMAT.md).
CLI exit 2 means valid non-passing evidence. Validators check format/coverage, not
remote evidence authenticity, provider signatures, independent security review or
release authority. The generic executor remains unavailable; explicit native/build
runbooks are the actual scoped procedures.

The accepted infrastructure boundary deliberately separates those results from
qualified release rows. Final owners rebuild the actual artifacts, run installed
without checkout and all six store-family proofs, then qualify changed artifacts
before Pilot 0 invitations. Do not fill a missing schema, authority port or UI with
a permissive fixture to make the aggregate report appear passed.

## Source changes and reproduction

Exact commands, input/procedure hashes, environment and limitations remain in each
record. Use the [build](../deployment/packaging-and-installation.md),
[native lab](../deployment/linux-development-and-qualification.md),
[gateway](../operations/network-and-host-services.md) and
[GCP](../deployment/gcp-host-setup.md) runbooks with new immutable
outputs/labs. Preserve original failures; never patch a tested snapshot or silently
renew its qualification after changing code, architecture, UID mapping, seccomp,
kernel, Docker or filesystem configuration.

Final current-source consolidation repeated sandbox/connected/ABI checks and validated
the exact measured capacity artifact with the portable native validator. It did not
repeat the VM reboot, cloud/provider setup or capacity workload, or rebuild/reinstall
earlier candidates. Between the measured workload and final consolidation, only the
validator's Linux-errno portability correction changed selected source. Runtime policy,
budget and workload were unchanged. Earlier reboot/network drivers remain unchanged;
those results retain their original scope/pins.

Safe raw references map into the private evidence root
`/Users/dcai/Desktop/Property-Management-Data/hosted-mvp-qualification/` with recorded
run subdirectories and hashes. Credentials and real customer data stay outside reports.
Preserve the dated narratives/JSON as records, not current operating instructions.

## Failure evidence

| Observation | Correction or remaining limit |
| --- | --- |
| Docker Desktop CLI-link postflight, noexec agent-install tmpfs and build constraint path containing spaces | App-local CLI, separate executable install staging and constraint-local invocation passed without relaxing Operator writable-tree policy. [Packaging record](../qualification/reports/HOSTED_MVP_H02_4_HANDOFF.md#observed-failures-and-recovery) |
| Guardian stop exceeded deadline | Kernel AppArmor signal evidence identified exact `runc` TERM/KILL peer; narrowly allowed receive signals, retaining deadline and original labs. [Runtime diagnosis](../qualification/reports/HOSTED_MVP_H02_5_HANDOFF.md#hardened-test-diagnosis-and-fix) |
| Native application chmod failed | Added only missing native chmod alias; owned operation succeeds while protected changes remain denied. Current native/compat requalification passed. [Capacity record](../qualification/reports/HOSTED_MVP_H02_10_HANDOFF.md#corrected-failures-and-limits) |
| Missing quota extras/bridge filtering; development internal bridge did not publish loopback ports | Matching clone-only prerequisites and development bridge correction; production checks still fail closed. [Lab failures](../qualification/reports/HOSTED_MVP_H02_8_HANDOFF.md#failed-attempts-retained) |
| Numeric setpriv metadata stall, provider empty credential field and concurrent service refresh | Direct numeric subprocess credentials, narrowly normalized/validated staging and ordered service refresh. No timeout/firewall/identity relaxation. [Host failures](../qualification/reports/HOSTED_MVP_H02_9_HANDOFF.md#failures-retained-and-resolved) |
| Repeated backup EIO | Explicit connection close fixed the workload at unchanged scratch size. [Measured workload record](../qualification/reports/HOSTED_MVP_H02_10_HANDOFF.md#corrected-failures-and-limits) |
| Extra-runtime host-memory refusal | Cause remains unexplained; retained as variability. A later successful run does not authorize bypassing fresh shared-reserve checks. Same measured record above. |
| Ten local socket-bind failures in consolidated tests | Restricted execution sandbox denied binds; all ten passed with socket access, without code/expectation changes. [Consolidated record](../qualification/reports/HOSTED_MVP_H02_11_HANDOFF.md#validation-matrix) |

These observations are not erased by successful reruns. Detailed histories, failed
lab identities and source/binary pins remain in the linked records and private evidence.

## Remaining delivery

| Owner | Foundation supplied | Required usable workflow |
| --- | --- | --- |
| Managed identity (H03) | Main-Admin structural closure, typed scope/epoch contracts, exact registered hosts and externally closed launch. | MFA, exact invited ownership, central login/one-use handoff, host-only sessions, revocation, hosted-access resources and assets. Identity/source proof gates positive route/start authority. |
| Admission and Free usage (H04) | Inventory allocation, immutable child receipts, ingress fences, protected transport, measured candidate and pure capacity planner. | Durable serialized holds/CAS with concurrent/lost-response recovery, logical allowance/metering, Admin-lite provisioning and Operator status UI. Count unknown/pending/retained commitments; no cohort cap or fixture bypass. |
| Recovery (H05) | Private workspace/control/scratch, stable writer lock, stop/deny boundary and reserved physical recovery headroom. | Separate recovery stores, encrypted off-host points/keys/control recovery, fencing and operator-authorized separate-staging restore. No empty reinitialization or Admin approval substitution. |
| Final artifact owners / Pilot 0 (H06) | Scoped infrastructure proofs, runbooks, retained failures and explicit coverage. | Complete final assets/all six stores, rebuild/qualify exact installed artifacts, then satisfy identity, real admission, recovery, UI/support and operational gates before invitations. |

Later paid billing, general provisioning automation, idle-wake and per-operator
scheduling retain their feature owners. No infrastructure report implements them.
