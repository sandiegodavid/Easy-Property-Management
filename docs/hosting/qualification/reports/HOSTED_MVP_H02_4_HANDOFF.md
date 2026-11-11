# H02.4 — Separate installed candidate artifacts

Delivered November 11, 2026 on `hosted_mvp`, continuing `45819c90` (partial H02.4)
from H02.3 baseline `195a5fe6`. This is **component packaging evidence**, including
actual Linux AMD64 OCI builds and installed checks under Docker Desktop emulation.
It does not establish native Ubuntu/GCP isolation or qualify a hosted release.

Use the [build/install runbook](../../deployment/packaging-and-installation.md)
and [machine-readable evidence](HOSTED_MVP_H02_4_VALIDATION.json) for commands,
dependency closure, source/artifact hashes, environment and measured outcomes.
Artifacts are retained privately outside Git under `hosted-mvp-qualification/H02.4/`.
No live/cloud data or services were changed; the retained Lima quota-test VM is intact.

## Delivered boundaries

- Separate fixed Admin/Operator candidate entrypoints, Dockerfiles and OCI artifacts;
  a separate offline host-agent installation archive. All three use explicit component
  resource ownership and exact file/hash inventories. The Python app code is shared;
  schema ownership, compiled UI inclusion and entrypoints differ by component.
- App/resource file allowlists reject missing, changed, linked or undeclared content.
  Compiled public SPA assets ship only in Operator. Checkout/test corpora, qualification
  harnesses, arbitrary data/environment files and source maps are excluded from the
  owned runtime inventory; private-key markers are rejected. This is not a claim that
  arbitrary secrets in every possible source string are detectable.
- Actual Linux dependency resolution produced 35 hash-locked binary wheels, including
  Linux-only dependencies absent from the earlier Mac candidate closure. Offline image
  installs verify the app wheel, lock and exact dependency bytes before use. The H02.1
  Linux-closure handoff is complete; installed native kernel proof remains H02.8.
- Component staging/verification explicitly selects Admin + Admin recovery, business +
  hosted access + Operator recovery, or inventory. Unimplemented sets stay unavailable
  with no invented revision or database. Existing local script defaults remain unchanged.
- Final images copy only the installed environment from the build stage and run as
  UID/GID 65532. Installed probes ran from `/tmp` without a checkout/network, on read-only
  container roots, using temporary synthetic stores. Final build paths and compiler
  executables were absent. Third-party/base-image content is pinned separately.
- The agent archive uses sorted normalized metadata and refuses overwrite/unexpected
  bundle files. Installation from the archive into a fresh container virtual environment
  passed without network or host service setup.

## Artifact identities

| Candidate | OCI platform manifest digest / archive SHA-256 |
| --- | --- |
| Admin | `sha256:0c52f62a026aa31618a3e25d92dcccce4658c1beed372cb16d461ecd1c4edd06` |
| Operator | `sha256:637297357116a2dc3f86a4b13c68b3586bb7bb05e86fddf1b6f9c5acb67fd969` |
| Host-agent `.tar.gz` | `2bd341213b0a7291087edbf4e1dee995b8617b27ce582ae041d23f7a18ad0f01` |

OCI index entries and addressed manifest blob hashes were verified against build
metadata. Config digests, OCI archive hashes, app wheel hashes, manifest hashes and
source-file pins are in the JSON report. With this Docker/buildx exporter, image inspect
and `--iidfile` report the platform manifest digest; they must not be mistaken for the
OCI config digest. Convenience tags are not release authority.

Both Admin and Operator wheels **and complete manifests** reproduced byte-for-byte
with the explicit setuptools 84.0.0 constraint. Their inventories contain 586 and 595
files respectively. The pinned base is Python 3.14.10 slim Bookworm AMD64 at
`sha256:1faf2343e747208b2a36e5f2b5ff908ec3b2d0078a6a7bfe73b535698fe83909`.
The target later remains Ubuntu 24.04 AMD64; a Debian userspace base and Desktop kernel
are recorded here separately from future native-host qualification.

## Focused validation matrix

| Area | Executed result and limit |
| --- | --- |
| Happy paths | Actual Admin/Operator OCI builds, installed inventories, business/Admin initialization, and archived agent installation/inventory initialization passed. Operator contracts and SPA build passed; existing Vite large-chunk warning remains. |
| Invalid combinations | Wrong component/UI/schema ownership, false qualified/ready claims, missing/tampered/linked/extra runtime files, unsafe paths, duplicate manifest keys, private-key markers, unpinned/changed/extra dependency inputs and unexpected archive data reject. |
| Retry/idempotency | Staging and archive output never overwrite existing evidence. Matching Admin/inventory initialization is read-only and byte-preserving. Repeat pinned Admin/Operator wheels/manifests are identical. |
| Rollback | Injected resource publication failure reverses earlier published entries; missing resources publish nothing. No cross-store or external command transaction is introduced. |
| Persistence/schema | Fresh installed Admin/business/inventory validate. Admin recovery, hosted access and Operator recovery stay unavailable without creating destinations. Existing schema-resource/initializer negative and rollback tests pass. |
| Backup/restore | Immutable OCI and agent artifacts are retained/reinstallable; no workspace backup or restore capability is claimed. H05 owns authenticated recovery, keys and round trips. |
| Query/N+1 | Packaging performs no runtime directory/entity projection and introduces no database query fan-out. Inventory verification is bounded by manifest limits; query-budget workloads are not applicable here. |
| Local compatibility | Focused default-mode staging/verification regressions pass without dispatching hosted composition; frontend contracts build without opening a workspace. |
| Runtime scope | Normal startup exits unavailable. Health-only liveness 200; readiness, business API and root 503. Agent has no health service or automatic service installation. |

Focused command in the runbook: **229 passed, 0 failed, 0 skipped in 11.31 s**.
Changed-boundary Python checks: **16 Python files passed Ruff check and format --check**.
Frontend lint, format:check and complete typecheck passed (192 source files).
No full application or Playwright suite was requested or run.

## Observed failures and recovery

- Homebrew's Docker Desktop system-link postflight required sudo and rolled back.
  The official app-only installation succeeded; CLI tools remain inside the app.
- An agent probe initially used a noexec installation tmpfs; executing the new Python
  environment failed. A separate executable temporary install mount passed. This does
  not qualify or relax the future Operator writable-tree sandbox.
- The repeat builder exposed an unsupported singular constraint flag and an absolute
  constraint path truncated at a checkout space. The plural option and constraint-local
  working directory passed; a focused regression pins the invocation.
- Running the packaging tests from repo root could not import `scripts`; the documented
  `application/` working directory passed. These failures are not relabeled as passes.

## Remaining owner gates

H02.4 is delivered as an infrastructure-candidate slice. No H02.5 sandbox/quota mount,
H02.6 ingress/egress, H02.7 real hosted startup, H02.8 native/reboot, H02.9 GCP reset,
H02.10 capacity or H02.11 aggregate acceptance is established by it. H03–H05 must deliver
missing source/recovery schemas, Admin assets and application behavior, then rebuild
and requalify complete artifacts before H06 invitations. The minimal health-only
candidate is intentionally unavailable and is not a release-assignment row.
