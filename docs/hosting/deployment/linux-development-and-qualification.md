# Development and native qualification

[Tool source](../../../application/deploy/hosted-mvp/lab) · [Foundation guides](../foundation/README.md)

Use synthetic data only. These tools cannot enroll an operator, enable ingress or
promote a release. Mac Docker Desktop/emulated AMD64, native ARM64 Lima and native
AMD64/GCP are separate evidence scopes. The [H02.8 handoff](../qualification/reports/HOSTED_MVP_H02_8_HANDOFF.md)
records actual results and remaining gates. Keep failed laboratories and raw logs.

## Mac Docker development

Use the [candidate build instructions](packaging-and-installation.md) to prepare fresh Admin and
Operator contexts using the pinned Linux dependency lock, then build them with
`--platform linux/amd64 --network=none --load`. Do not reuse old image qualification
for changed sources. Keep contexts, wheel inventories, lock, image IDs and build logs
in a fresh private folder outside Git. Dependencies are resolved once; builds are offline.

From `application/`, set the artifact folder and Docker CLI path:

```sh
export PATH="/Applications/Docker.app/Contents/Resources/bin:$PATH"
export EPM_LAB="$HOME/Desktop/Property-Management-Data/hosted-mvp-qualification/H02.8"
export EPM_ADMIN_IMAGE="$(cat "$EPM_LAB/admin-image-id")"
export EPM_OPERATOR_IMAGE="$(cat "$EPM_LAB/operator-image-id")"
.venv/bin/python deploy/hosted-mvp/lab/desktop.py \
  --admin "$EPM_ADMIN_IMAGE" --operator "$EPM_OPERATOR_IMAGE" \
  --output "$EPM_LAB/desktop-new.json"
```

The checker rejects tags, verifies actual image/component identity and runs the
installed probe without a checkout, network or writable root. Its only host mount
is the read-only probe source. Disposable `/tmp` holds synthetic stores. Each fresh
report records engine/architecture and partial failures; an existing report is never
overwritten. Missing H03/H05 stores must remain unavailable without destination creation.

To inspect the unavailable pages, use the explicit loopback development origins:

```sh
docker compose -p epm-h02-dev -f deploy/hosted-mvp/lab/compose.yaml config --quiet
docker compose -p epm-h02-dev -f deploy/hosted-mvp/lab/compose.yaml up -d
# Admin: http://127.0.0.1:18801/
# Operator: http://127.0.0.1:18802/
docker compose -p epm-h02-dev -f deploy/hosted-mvp/lab/compose.yaml down
```

Both pages are intentionally unavailable, not fake login/Admin applications. Compose
mounts no workspace, credentials, Docker socket or host folder. Its development bridge,
loopback-only ports and no-restart policy are for development. The development bridge does not enforce production outbound restrictions. They do not prove
ext4 quotas, the native AppArmor/seccomp policy, reboot safety or source admission.
Actual business browser workflows stay with H03–H05; no development bypass is added
to production composition. The real synthetic admission adapters exist only inside
the opt-in native fixtures, not in an installed service.

## Preserve the baseline and create a separate native clone

The original `epm-quota-test` and `epm-h02-runtime` must be stopped before cloning.
Never run this procedure against the live demo or change either original VM. Choose
a fresh name; retain the new VM and its laboratories after use.

```sh
limactl list
limactl clone epm-h02-runtime epm-h02-8 --mount-none --tty=false
limactl start epm-h02-8 --tty=false
```

H02.8 used that retained clone, with no host mounts. Do not repeat `clone` for an
existing name. Before changes, record the source VM's stopped state and configuration
hash privately. Do not copy host credentials or business data. The clone contains the
previous lab's Linux-only tools at `/var/lib/epm-h02-runtime-tools/bin/python`; it is
not a production installation. Fresh machines need the prerequisite packages from
the [sandbox runbook](../operations/runtime-supervision.md), Docker, AppArmor, nftables and the pinned
Python workload image. Record actual versions, not just package names.

## Source custody and prerequisites

From `application/`, create a fresh archive; the command prints its per-file manifest:

```sh
.venv/bin/python deploy/hosted-mvp/lab/snapshot.py --application . \
  --output "$EPM_LAB/source-new.tar" > "$EPM_LAB/source-new.json"
limactl copy "$EPM_LAB/source-new.tar" epm-h02-8:/tmp/h02-source-new.tar
limactl shell --workdir=/tmp epm-h02-8 sudo mkdir /opt/epm-h02-source-new
limactl shell --workdir=/tmp epm-h02-8 sudo tar -xf /tmp/h02-source-new.tar \
  -C /opt/epm-h02-source-new
```

The deterministic archive includes only runtime/fixture Python/C and explicitly
named security/container inputs. It excludes tests, compiled web assets, environment
files, arbitrary data, workspaces and caches; links reject. It never overwrites an
existing archive. The extracted root-owned directory is the source of the proof.
Keep old snapshots rather than editing a tested tree in place.

Inside this disposable clone, establish prerequisites explicitly before native runs
and again after a reboot. Production guard code must not silently do this for you:

```sh
sudo modprobe quota_v2
sudo modprobe br_netfilter
sudo sysctl -w net.bridge.bridge-nf-call-iptables=1 net.bridge.bridge-nf-call-ip6tables=1
findmnt -rn -t virtiofs,9p,fuse.sshfs
```

The final command should print nothing: no shared host directories. If `quota_v2` is
missing after a kernel update, install `linux-modules-extra-$(uname -r)` in this
clone only, then record that exact package/version and kernel hash. This occurred
on H02.8's first boot of kernel `6.8.0-149-generic`. Network checks failed closed until
`br_netfilter` was explicitly restored after reboot. Neither failure is a pass.
Do not format a real device, disable host/root-disk quotas or relax production guards.

## Focused native Docker and connected proofs

Inside the clone, use the fresh extracted application directory:

```sh
cd /opt/epm-h02-source-new
sudo env EPM_RUN_PROJECT_QUOTA_QUALIFICATION=1 PYTHONPATH="$PWD/apps/server" \
  /var/lib/epm-h02-runtime-tools/bin/python -B \
  deploy/hosted-mvp/sandbox/qualify_runtime.py --run
sudo env EPM_RUN_PROJECT_QUOTA_QUALIFICATION=1 PYTHONPATH="$PWD/apps/server" \
  /var/lib/epm-h02-runtime-tools/bin/python -B \
  deploy/hosted-mvp/gateway/qualify_connected.py --run
```

These allocate fresh loop-backed ext4 lab trees under `/var/lib`, never an existing
volume. They use real Docker/project quotas, separate UIDs, production sandbox code
and explicit synthetic fixture authority. Capture stdout/stderr and the printed
root/results. Runtime proof covers bytes/inodes/deleted-open/WAL failures, ioctl and
namespace/mount denials, cross-UID reads, lock replacement, log/resource bounds,
quota-off negative control, guardian death and missing inventory. Connected proof
adds current bridge/firewall validation and stop on firewall loss. These fault limits
are not Free entitlements or an accepted capacity profile.

## Actual guest reboot continuation

Use the same source root, tools Python and explicit opt-in above:

```sh
sudo env EPM_RUN_PROJECT_QUOTA_QUALIFICATION=1 PYTHONPATH="$PWD/apps/server" \
  /var/lib/epm-h02-runtime-tools/bin/python -B \
  deploy/hosted-mvp/lab/qualify_reboot.py before
```

Retain the printed lab root and `h02-reboot.json`. The fixture registers and starts
two synthetic no-restart Docker containers holding the stable control locks and
records all six kernel quota observations, image/profile/source pins and boot ID.
Then, from macOS:

```sh
limactl shell --workdir=/tmp epm-h02-8 sudo systemctl reboot
```

Wait for SSH to return. A container restart or Lima stop/start receipt is not the
proof: the continuation requires a changed Linux boot ID with unchanged exact kernel
bytes, sources and Docker platform. Inside the clone, run from the same source root:

```sh
sudo env EPM_RUN_PROJECT_QUOTA_QUALIFICATION=1 PYTHONPATH="$PWD/apps/server" \
  /var/lib/epm-h02-runtime-tools/bin/python -B \
  deploy/hosted-mvp/lab/qualify_reboot.py after \
  --root /var/lib/epm-quota-qualification-REPLACE_WITH_RECORDED_LAB
```

The continuation inspects the exact retained Docker identities before remounting the
lab; both must be stopped with restart disabled. It explicitly remounts only that
lab image, reloads the pinned AppArmor policy, checks quota usage/limits/lock inodes,
and repeats real sandbox/WAL, EDQUOT and cross-UID denial checks. The result is written
to `h02-reboot-result.json`; a repeated completed check only verifies pins/boot and
returns its retained result, without remounting or replaying actors. Changed inputs
require a fresh proof. Failures leave the lab and logs for diagnosis.

Finally collect reports, logs and manifest hashes privately, and stop the clone:

```sh
limactl stop epm-h02-8 --tty=false
limactl list
```

Keep all three VMs and both successful/failed laboratories. Exact native AMD64/GCP,
provider setup, final all-store images, production capacity and customer admission
remain H02.9–H02.11/H03–H06 gates. H02.8 evidence cannot close them.
