# Local Linux qualification VM

This retained local VM is for Hosted Admin Slice 8A kernel, ext4 project-quota
and sandbox tests. It is separate from the Google demo host and contains no live
operator data or deployment credentials. Keep the VM after testing; stop it when
idle rather than deleting it.

## Configuration

| Setting | Value |
| --- | --- |
| Name | `epm-quota-test` |
| Manager | Homebrew Lima 2.2.1 |
| Virtualization | Apple Virtualization.framework (`vz`) |
| Guest | Ubuntu Server 24.04 LTS, ARM64 |
| CPUs / memory | 2 CPUs / 4 GiB RAM while running |
| Virtual disk | 20 GiB maximum; host disk allocation grows with use |
| Host configuration and disks | `~/.lima/epm-quota-test/` |
| Isolation | Plain mode; no host-folder mounts, container runtime or automatic application-port forwarding |
| Automatic startup | Not enabled |

Lima downloaded the dated Ubuntu ARM64 image from
`https://cloud-images.ubuntu.com/releases/noble/release-20260926/ubuntu-24.04-server-cloudimg-arm64.img`
with expected SHA-256
`1d6bffe64b848468ac97f821d369a4846d983de1800ccf6b5ec8853e85cefc55`.
The dated image is an installation input, not a permanent download guarantee.
Future rebuilds must record their actual image digest and guest package versions
before using their results as qualification evidence.

## Start, use and stop

Run these commands in a **macOS Terminal**:

```bash
limactl list
limactl start epm-quota-test
limactl shell --workdir=/tmp epm-quota-test
```

The last command opens a Linux shell. `sudo` operates **inside this VM**.
Use `exit` to return to macOS. A one-off command is:

```bash
limactl shell --workdir=/tmp epm-quota-test uname -a
limactl shell --workdir=/tmp epm-quota-test sudo systemctl --version
```

The explicit working directory avoids attempting to enter the Mac checkout,
which is deliberately not mounted in the guest.

After testing, shut down from macOS:

```bash
limactl stop epm-quota-test
```

Stopping preserves installed packages, test files, evidence and the virtual disk.
Start the same name next time. Do not run `limactl delete`, remove its directory,
or recreate the VM as routine cleanup. Rebooting the guest with `sudo reboot` is
appropriate only during an explicitly isolated persistence test.

## Copy test code and retrieve results

Copy only the test inputs needed for a run. Host folders and credentials are not
shared automatically. From macOS, for example:

```bash
limactl copy /tmp/epm-quota-tests.tar epm-quota-test:/tmp/epm-quota-tests.tar
limactl shell --workdir=/tmp epm-quota-test tar -xf /tmp/epm-quota-tests.tar
limactl copy epm-quota-test:/tmp/epm-quota-results.json /tmp/epm-quota-results.json
```

Create the archive/result named above before running those examples. Do not copy
`.venv`, `node_modules`, `.git`, workspace data, SSH keys, cloud credentials or
secret configuration into the test archive. Install Linux dependencies in the
guest; the macOS virtual environment cannot run there.

## Installation and test prerequisites

The initial macOS installation used:

```bash
brew install lima
limactl create --name=epm-quota-test --vm-type=vz \
  --cpus=2 --memory=4 --disk=20 --plain --mount-none \
  --containerd=none --yes template:ubuntu-24.04
limactl start epm-quota-test
```

Do not repeat `create` for an existing VM. Lima's
[installation](https://lima-vm.io/docs/installation/),
[plain-mode](https://lima-vm.io/docs/config/plain/) and
[usage](https://lima-vm.io/docs/usage/) documentation describe these controls.

Install qualification prerequisites **inside the Linux VM**:

```bash
sudo apt-get update
sudo apt-get install -y e2fsprogs quota util-linux build-essential \
  libseccomp-dev pkg-config python3-venv python3-pytest
sudo apt-get install -y linux-modules-extra-"$(uname -r)" gcc-arm-linux-gnueabihf
sudo modprobe quota_v2
```

Keep quota test images and mountpoints in a harness-owned directory in the
guest, separate from its root filesystem. A loop image is allowed for this
isolated qualification harness; production per-operator loop images are not the
Slice 8 target backend. Never enable/disable quotas or format the VM's root disk
as part of a test. Record kernel, e2fsprogs, systemd, seccomp/tool versions and
digests alongside each result.

## Qualification status

Setup verified November 1, 2026: Ubuntu 24.04.5 ARM64 booted through VZ,
kernel `6.8.0-142-generic`, systemd `255.4-1ubuntu8.17`, e2fsprogs `1.47.0`,
libseccomp `2.5.5`, Python `3.12.3` and pytest `7.4.4`. The listed prerequisite
packages installed successfully. SSH, passwordless guest sudo, copying a guest
result to macOS, and absence of virtiofs/9p/sshfs host mounts were verified.
Cloud-init reported no errors, with recoverable warnings about deprecated Lima
template field spelling/types. The guest's Python is for the low-level harness;
running the complete application requires its separately pinned Python/runtime
dependencies. The VM was shut down after setup and retained for reuse.

After setup, the [Slice 8A real-kernel harness](HOSTED_PROJECT_QUOTA_QUALIFICATION.md)
passed byte/inode enforcement, attribution, sandbox escape, enforcement loss,
remount and actual VM reboot checks on November 1, 2026. Matching optional kernel
quota modules and the ARM32 cross-compiler are installed. The report records
compatibility limits. This does not qualify the live host or authorize rollout.

See [Slice 8A](../design/HOSTED_DEMO_ADMIN_IMPLEMENTATION_PLAN.md#8a--prove-the-filesystem-and-sandbox-boundary)
for the completion gate. Record the actual VM setup verification and any
remaining work in the Slice 8A checkpoint.


## Slice 8C accounting runtime and evidence

November 3, 2026: installed a separate root-owned Linux CPython 3.14.8 runtime
and test venv in `/opt/epm-s8c-runtime`, plus source-only snapshot
`/opt/epm-s8c-code/application`. The original system Python 3.12 was preserved.
The source-ledger byte/inode drills and three-case clean-reboot continuation passed
under the existing sandbox, including unknown-intent reservation recovery. Runtime
installation commands, exact dependency/source pins, all failed attempts, final
results and retained laboratory locations are consolidated in the
[source-accounting qualification report](HOSTED_SOURCE_STORAGE_QUALIFICATION.md).
Use that report for reruns; the earlier 8A reboot phase is not an 8C reboot proof.
No live host or operator data was copied into the guest. Keep the VM and test
artifacts; stop it when idle rather than deleting it.

The later [native observer continuation](HOSTED_SOURCE_STORAGE_QUALIFICATION.md#native-collector-transport-and-quota-observation-continuation)
retains separate initial/final code snapshots and laboratories. It exercised real
root/source kernel peers and quota observations in the source sandbox, with
synthetic authority/profile inputs. Use its recorded command and opt-ins; it is
not an installed-service or production profile grant. The VM remains stopped and
retained after these tests.

## Retained Slice 8C collector and initialization fixtures

The disposable VM now also retains `/opt/epm/admin`, an isolated collector test
virtual environment and empty synthetic Admin authority/inventory under
`/var/lib/epm-admin`. The `epm-source-storage` service/socket units are installed
but stopped and not enabled for boot. Dedicated test HTTP/probe accounts and the
observer group remain. These are test fixtures, not production installation or
source grants. The collector installation guard refuses to replace them.

Current scoped results and exact snapshot/laboratory paths are in the
[source storage qualification report](HOSTED_SOURCE_STORAGE_QUALIFICATION.md#installed-collector-service-and-initial-workspace-publication).
The root-preserving initialization component uses a separate fresh quota laboratory;
keep its successful and failed trees and snapshots. Earlier interpreter environments
were not modified. Stop the VM after tests; do not delete fixtures to make a
fresh-installation guard pass.

## Full-application seed qualification runtime

Slice 8C's November 4 seed proofs use the separate environment
`/opt/epm-s8c-seed-runtime/venv/bin/python`. The earlier primitive runtime remains
unchanged. Both use the retained CPython 3.14.8 installation; the seed environment
adds the app's declared keyring/multipart/ASGI/client dependencies. Exact versions,
source snapshots, failure dispositions and repeat commands are in the
[seed qualification report](HOSTED_SOURCE_STORAGE_QUALIFICATION.md#fresh-synthetic-seeding-and-explicit-clean-reseed).
Do not reuse a recorded laboratory for another run or use the laboratory's explicit
cleanup flag on an enrolled or real operator workspace.
