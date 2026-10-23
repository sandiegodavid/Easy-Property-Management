# Google Cloud trial: two-workspace demo deployment

Recorded October 23, 2026. Audience: the administrator provisioning and maintaining the demo.

**Historical initial installation:** this guide records `demo-001` and the old
private portfolios. On October 24, the deployment moved to the qualified hosted
release and fresh current-format portfolios; old units are masked. For the latest
recorded state, evidence, current locators and remaining public-access gates, start
with the [human review guide](../../operations/CLOUDFLARE_OPERATIONS.md#human-review-guide--october-24-2026).
Do not rerun the initial creation/restoration commands over the current deployment.

This records the Google Cloud setup completed during the guided session, including the corrected archive names, restore configuration, and temporary-directory permissions. Commands identify whether they run on the Mac, in Cloud Shell, or inside the VM. Use the existing installation; do not rerun creation or restore commands over populated directories.

## Scope and completion status

One Ubuntu VM runs two independent synthetic portfolios, each under its own Unix account and application process. This follows the [hosted demo proposal](../../design/HOSTED_DEMO_DESIGN.md) and [wheel deployment guide](../../../../manual/deployment.md). It does not implement shared-portfolio collaboration or public hosted authentication.

The administrator reported completing VM provisioning, installation, both restores, systemd startup, endpoint checks, and the private browser tunnel. The installed-resource verification and restore errors were also supplied directly in the session. This is a session record, not an independent remote audit. Browser workflow checks, persistence across restart/reboot, measured capacity, and recurring off-host backups still require recorded acceptance.

**Public operator access remains gated on the hosted application work.** The current CLI binds to loopback, and the local transport contract is not hosted authentication. Do not publish these servers by rewriting Host/Origin, relaxing transport checks, or exposing application ports. The administrator's Google/SSH credentials grant authority over both workspaces; this is not an operator login system. See the [hosted access requirements](../../design/HOSTED_DEMO_DESIGN.md).

## 1. Deployment record

These identifiers are not credentials. For a new deployment, substitute its actual project ID, VM, zone, release, paths, and workspace IDs throughout.

| Item | Recorded value |
| --- | --- |
| Project display name | `epm-demo` |
| Project ID | `project-47b72bb7-ba90-42c9-910` |
| VM name | `epm-demo` |
| Region / zone | Oregon `us-west1` / `us-west1-b` |
| Proposed machine selection | E2 `e2-medium`: 2 vCPUs, 4 GB RAM; confirm in Console |
| Selected OS / disk | Ubuntu 24.04 LTS x86/64; 30 GB boot disk |
| Network / external IPv4 | `default` / ephemeral |
| SSH target tag | `epm-admin` |
| Release | `demo-001`, package `0.1.0` |
| Source commit | `f5c1518b7d97a309660e642964c45244516c0a54`; clean checkout at build |
| Mac build Python | CPython `3.14.8` |
| VM Python | CPython `3.14.9`, as shown in the VM traceback; record the installed version explicitly |
| Runtime | `/opt/epm/releases/demo-001/venv` |
| Shared Python installation | `/opt/epm/python` |
| A identity / configuration | `epm-a` / `/var/lib/epm-a/config.json` |
| B identity / configuration | `epm-b` / `/var/lib/epm-b/config.json` |
| A workspace ID | `0efb09a0-5af2-4e6f-904f-154a50ab9445` |
| B workspace ID | `3390ed71-0bd9-40f7-8e7f-702df257e880` |
| VM application listeners | A `127.0.0.1:8001`; B `127.0.0.1:8002` |
| Mac browser addresses | A `http://127.0.0.1:18001/home`; B `http://127.0.0.1:18002/home` |

The initial Oracle account path was abandoned after account/region/capacity difficulties. This deployment uses the Google trial instead; it has no dependency on an Oracle account. An absent Oracle shape was not independently established to mean permanent regional unavailability.

## 2. Trial billing and project

October 24 operator update: Billing shows trial expiry **January 22, 2027**, and
**$30 monthly budget alerts are configured**. These are operator-reported, not an
independent Console audit. Review funding by January 15, 2027 (at least seven days
before expiry). No scheduled reminder was created; actual remaining credit and
future billing status still require administrator checks.

In the [Google Cloud Console](https://console.cloud.google.com/):

1. Select the Gmail account used to register for the Google Cloud trial.
2. Create or select the dedicated `epm-demo` project. Use **No organization** if applicable and associate the trial billing account.
3. Record the **project ID**, not just the display name. The two differ in this deployment.
4. Under **Billing**, confirm the actual trial credit, expiry date, and billing status.
5. Under **Budgets & alerts → Create budget**, select the demo project, a USD 30 monthly budget, and 50%, 90%, and 100% alerts. Exclude promotional credits from the calculation to monitor costs before those credits offset them.

This E2 medium configuration, disk, and external IPv4 consume trial credit. It is not the ongoing free-tier VM configuration. Budget alerts do not cap spending or stop resources. Review costs and trial expiry regularly. Google documents USD 300 for up to 90 days for eligible trial customers, but the account's displayed terms and remaining balance govern this deployment. Paid-account upgrade is a separate choice.

Sources: [trial conditions](https://cloud.google.com/signup-faqs), [budgets](https://docs.cloud.google.com/billing/docs/how-to/budgets), [free-tier limits](https://docs.cloud.google.com/free/docs/free-cloud-features), [network pricing](https://cloud.google.com/vpc/network-pricing). Recheck changing provider terms before reuse.

## 3. Create the VM

Open **Compute Engine → VM instances**. Enable the Compute Engine API for the selected project if prompted, then **Create instance**.

| Setting | Selection |
| --- | --- |
| Name | `epm-demo` |
| Region / zone | `us-west1` / `us-west1-b` |
| Machine series / type | E2 / `e2-medium` |
| Provisioning model | Standard |
| OS | Ubuntu 24.04 LTS, x86/64 (AMD64), not Ubuntu Pro or ARM64 |
| Boot disk | 30 GB Standard persistent disk; confirm actual type in Console |
| Network / subnetwork | `default` / regional `default` subnet |
| External IPv4 | Ephemeral |
| Network tag | `epm-admin` |
| Allow HTTP / HTTPS traffic | Both unchecked |

Use **OS and storage → Boot disk → Change → Public images → Ubuntu** before creating the VM. The Console initially selected Debian 13 in this session; the empty VM was recreated with Ubuntu. An ARM64 image such as `ubuntu-2404-noble-arm64-v20261021` is incompatible with E2. AMD64 images work on the selected x86 platform.

For an existing VM, click its name, **Edit → Network interfaces → nic0** to inspect the network and select **External IPv4 address → Ephemeral**, then **Done → Save**. An ephemeral address can change after stop/start. Assigning it does not open application ports. Avoid adding GPUs, Cloud SQL, load balancers, or additional disks for this demo.

Sources: [VM creation](https://docs.cloud.google.com/compute/docs/instances/create-start-instance), [external addresses](https://docs.cloud.google.com/compute/docs/ip-addresses/configure-static-external-ip-address).

## 4. Restrict SSH to IAP

First add the **network tag** `epm-admin` under **VM instances → epm-demo → Edit → Network tags**, then save. This is not a label or Resource Manager tag.

Open **VPC network → Firewall → Create firewall rule** in the correct project:

| Field | Value |
| --- | --- |
| Name | `epm-allow-iap-ssh` |
| Logs | Off |
| Network | `default` |
| Priority | `1000` |
| Direction / action | Ingress / Allow |
| Targets | Specified target tags |
| Target tags | `epm-admin` |
| Source filter | IPv4 ranges |
| Source IPv4 ranges | `35.235.240.0/20` |
| Protocols and ports | Specified protocols and ports: TCP `22` only |

Press Enter after typing tag/range values if the Console uses chips. Leave an optional second source filter unset. Save this rule first, then inspect `default-allow-ssh`. If it allows TCP 22 from `0.0.0.0/0`, edit it and set **Enforcement → Disabled** in this dedicated project. Check for any other rule allowing public SSH. Keep ports 80, 443, 8001, and 8002 closed.

IAP tunneling also requires Google IAM authorization; the firewall rule alone does not grant login. If a different administrator receives an authorization error, review the required IAP and Compute permissions instead of opening SSH publicly. [Google IAP instructions](https://docs.cloud.google.com/iap/docs/using-tcp-forwarding)

## 5. Connect from Cloud Shell and prepare Ubuntu

**Cloud Shell** is the terminal opened with **Activate Cloud Shell** (`>_`) in the Console. Its prompt contains `@cloudshell`. Connect from there:

```bash
gcloud compute ssh epm-demo \
  --project=project-47b72bb7-ba90-42c9-910 \
  --zone=us-west1-b \
  --tunnel-through-iap
```

Authorize and accept SSH-key generation if prompted. `--project=epm-demo` was incorrect in this deployment: it used the display name and produced an API-not-enabled prompt for the wrong project. Cancel that prompt and use the actual ID. `gcloud compute instances list` lists VMs in Cloud Shell's currently selected project when investigating a mismatch.

Once connected, the **VM terminal** prompt contains `@epm-demo`. Run:

```bash
uname -m
cat /etc/os-release
free -h
df -h /
sudo apt-get update
sudo apt-get install -y ca-certificates curl python3 python3-venv python3-pip
timedatectl status
```

Expect `x86_64`, Ubuntu 24.04, roughly 4 GB RAM, a roughly 30 GB root disk, and a synchronized clock. Keep application property time zones separate from host time configuration. This capacity is a starting allocation, not measured EPM throughput.

## 6. Install Python 3.14 and the isolated runtime

Run in the **VM terminal**. The source release requires Python 3.14 syntax despite the package metadata's older minimum. Do not replace Ubuntu's system Python.

```bash
curl --proto '=https' --tlsv1.2 -LsSf \
  https://astral.sh/uv/install.sh \
  -o /tmp/epm-uv-install.sh
less /tmp/epm-uv-install.sh
```

After inspecting the installer, press `q`, then:

```bash
sh /tmp/epm-uv-install.sh
"$HOME/.local/bin/uv" --version

sudo install -d -m 0755 /opt/epm /opt/epm/releases
sudo install -d -o "$(id -un)" -g "$(id -gn)" -m 0755 \
  /opt/epm/python /opt/epm/releases/demo-001

UV_PYTHON_INSTALL_DIR=/opt/epm/python \
  "$HOME/.local/bin/uv" python install 3.14

UV_PYTHON_INSTALL_DIR=/opt/epm/python \
  "$HOME/.local/bin/uv" venv --python 3.14 --seed \
  /opt/epm/releases/demo-001/venv

/opt/epm/releases/demo-001/venv/bin/python --version
/opt/epm/releases/demo-001/venv/bin/python -m pip --version
```

Record the installed patch version; `3.14` selects a current patch and is not a reproducibility pin. For a future rebuild, use the approved recorded patch in both uv commands. Runtime installation under `/opt/epm` lets service accounts run it without access to the administrator's home directory. [uv installation](https://docs.astral.sh/uv/getting-started/installation/), [managed Python](https://docs.astral.sh/uv/guides/install-python/)

## 7. Build and transfer the release bundle

### Bundle prepared in this session

On the **Mac**, the complete bundle is:

```text
/Users/dcai/Desktop/My Apps/Easy-Property-Management/application/dist/epm-demo-001-f5c1518.tar.gz
```

Archive SHA-256:

```text
fe81234a3da9654702f2ee16986f41bd6c8e3edd6104b902ac692c59693c82fd
```

It contains:

```text
demo-001/
├── RELEASE.txt
├── SHA256SUMS
├── easy_property_management-0.1.0-py3-none-any.whl
├── configure_workspace.py
├── stage_schema_resources.py
├── verify_installation.py
└── schema-resources/
    ├── alembic.ini
    └── database/sqlite-migrations/
        ├── env.py
        └── versions/0001_initial_schema.py
```

The wheel SHA-256 is `c94246b541c7837b7a7d69f35d2b36fa9ac985162db30bb1d67779e90eb47b2b`. These checksums describe the recorded artifacts only. A rebuilt wheel/archive needs new checksums and a new release identifier.

### Rebuilding for a future release

On the **Mac**, from the repository root:

```bash
./application/scripts/build_wheel.sh
```

Use `--install-deps` only when npm dependencies need installation. This checks frontend lint, formatting, types, and generated contracts, builds React, packages Python/public assets, and checks the wheel. Those checks passed for this release. The wheel build initially required access to the existing uv cache; after that access was allowed, packaging succeeded. No application source changes were made to build the deployment bundle.

For a new release, supply matching helpers, `alembic.ini`, and the complete current schema source directory from the same source revision; see the [release contents contract](../../../../manual/deployment.md#release-contents-required-before-deployment). Record the source revision, interpreter, and checksums in `RELEASE.txt` and `SHA256SUMS`. Build frontend assets on the Mac; resolve runtime dependencies on Linux. A copied macOS virtual environment is not a Linux deployment.

### Transfer through Cloud Shell

If currently connected to the VM, run `exit` to return to **Cloud Shell**. Use its toolbar **⋮ → Upload**, choosing the archive from the Mac. In the Mac file chooser, **Command–Shift–G** opens a path directly. Upload into Cloud Shell's home directory, then run:

```bash
gcloud compute scp ~/epm-demo-001-f5c1518.tar.gz \
  epm-demo:epm-demo-001-f5c1518.tar.gz \
  --project=project-47b72bb7-ba90-42c9-910 \
  --zone=us-west1-b \
  --tunnel-through-iap
```

Reconnect using section 5. In the **VM**:

```bash
sha256sum ~/epm-demo-001-f5c1518.tar.gz
mkdir -p ~/epm-upload
tar -xzf ~/epm-demo-001-f5c1518.tar.gz -C ~/epm-upload
cd ~/epm-upload/demo-001
sha256sum --check SHA256SUMS
```

Compare the archive hash with the recorded value above; every manifest entry must report `OK`. Linux tar warned about `LIBARCHIVE.xattr.com.apple.provenance` in the Mac-created archive. These were ignored macOS extended attributes, and all payload checksums passed; they were not an extraction failure.

## 8. Install and verify the release

In the **VM**:

```bash
cd ~/epm-upload/demo-001
/opt/epm/releases/demo-001/venv/bin/python -m pip install \
  ./easy_property_management-0.1.0-py3-none-any.whl
/opt/epm/releases/demo-001/venv/bin/python -m pip check
/opt/epm/releases/demo-001/venv/bin/python \
  ./stage_schema_resources.py ./schema-resources
/opt/epm/releases/demo-001/venv/bin/python ./verify_installation.py
```

Stop on failures. The recorded verification reported package `0.1.0`, schema `0001_initial_schema`, and installed-resource checks passed. This does not itself validate restored records or browser workflows. Keep the exact release and installed dependency versions for recovery; `pip list --format=freeze` displays the VM's resolved versions.

## 9. Create service identities and private directories

Run in the **VM**, once. If an account or directory already exists, inspect it and skip completed steps; do not reset ownership of unrelated paths.

```bash
sudo useradd --system --user-group \
  --home-dir /var/lib/epm-a --shell /usr/sbin/nologin epm-a
sudo useradd --system --user-group \
  --home-dir /var/lib/epm-b --shell /usr/sbin/nologin epm-b

sudo install -d -o epm-a -g epm-a -m 0700 \
  /var/lib/epm-a /var/backups/epm-a /var/lib/epm-a/tmp
sudo install -d -o epm-b -g epm-b -m 0700 \
  /var/lib/epm-b /var/backups/epm-b /var/lib/epm-b/tmp
sudo install -d -o root -g root -m 0755 /etc/epm

sudo install -o root -g root -m 0644 \
  ~/epm-upload/demo-001/configure_workspace.py \
  /opt/epm/releases/demo-001/configure_workspace.py
sudo chown -R root:root /opt/epm/releases/demo-001 /opt/epm/python

sudo -u epm-a /opt/epm/releases/demo-001/venv/bin/python --version
sudo -u epm-b /opt/epm/releases/demo-001/venv/bin/python --version
```

Each service can read the runtime but can write only its own data and private staging directories. Neither service account gets an interactive login or sudo access.

## 10. Prepare two synthetic exports on the Mac

These workspaces were independently seeded and verified in the session. Each contains 14 properties, 15 spaces, 9 leases, 12 tenants, 40 expenses, and related evidence/history. Their IDs are listed in section 1. Do not seed again over edited data or generate B by duplicating A's archive.

For a fresh deployment, the **Mac** commands are:

```bash
cd "/Users/dcai/Desktop/My Apps/Easy-Property-Management/application"

.venv/bin/python demo/seed.py \
  --workspace "/Users/dcai/Desktop/Property-Management-Data/gcp-demo-a" \
  --local-config "/Users/dcai/Desktop/Property-Management-Data/gcp-demo-a.config.json"
.venv/bin/python demo/verify.py \
  --config "/Users/dcai/Desktop/Property-Management-Data/gcp-demo-a.config.json"

.venv/bin/python demo/seed.py \
  --workspace "/Users/dcai/Desktop/Property-Management-Data/gcp-demo-b" \
  --local-config "/Users/dcai/Desktop/Property-Management-Data/gcp-demo-b.config.json"
.venv/bin/python demo/verify.py \
  --config "/Users/dcai/Desktop/Property-Management-Data/gcp-demo-b.config.json"
```

The generator also creates sibling `gcp-demo-a-demo-runtime` and `gcp-demo-b-demo-runtime` directories containing journals/catalogs. They are not deployment archives. See the [demo guide](../../../../application/demo/README.md) for date-sensitive scenario verification.

Once verified, create encrypted exports in the **Mac terminal**:

```bash
.venv/bin/python -m app \
  --config "/Users/dcai/Desktop/Property-Management-Data/gcp-demo-a.config.json" \
  export "/Users/dcai/Desktop/Property-Management-Data/gcp-demo-a.epm-backup"

.venv/bin/python -m app \
  --config "/Users/dcai/Desktop/Property-Management-Data/gcp-demo-b.config.json" \
  export "/Users/dcai/Desktop/Property-Management-Data/gcp-demo-b.epm-backup"
```

Enter passphrases interactively and retain them separately. Do not put them in commands, this document, or chat. The prompt says `Backup passphrase` for both operations. The application uses **`.epm-backup` for both package types**; `export` selects the internal export type. An earlier `.epm-export` filename was automatically changed to `.epm-backup` by the application. Use the path printed by the command. Existing archives are not overwritten.

When copying multiline commands, each `\` must immediately precede a newline. Do not flatten `\` plus spaces into one command line.

## 11. Transfer the encrypted exports

Upload both `.epm-backup` files from the Mac to **Cloud Shell** using the toolbar upload action, then run in **Cloud Shell**:

```bash
gcloud compute scp \
  ~/gcp-demo-a.epm-backup ~/gcp-demo-b.epm-backup \
  epm-demo: \
  --project=project-47b72bb7-ba90-42c9-910 \
  --zone=us-west1-b \
  --tunnel-through-iap
```

Reconnect to the **VM**, then place the archives in private service-owned directories:

```bash
sudo install -o epm-a -g epm-a -m 0600 \
  ~/gcp-demo-a.epm-backup /var/backups/epm-a/seed.epm-backup
sudo install -o epm-b -g epm-b -m 0600 \
  ~/gcp-demo-b.epm-backup /var/backups/epm-b/seed.epm-backup
```

Transfer complete encrypted archives, not running SQLite databases, Mac config files, credential stores, or the source checkout.

## 12. Configure and restore A

Run in the **VM**, one command at a time. Skip configuration creation if that file already exists and is correct. The helper deliberately refuses to overwrite it. Do not initialize the destination workspace before restoring. Restore only into a new or empty folder, with the application's service stopped.

Create the normal runtime configuration:

```bash
sudo -u epm-a /opt/epm/releases/demo-001/venv/bin/python \
  /opt/epm/releases/demo-001/configure_workspace.py \
  --config /var/lib/epm-a/config.json \
  --workspace /var/lib/epm-a/workspace
```

Create a separate restore-only configuration pointing to an unused sibling path:

```bash
sudo -u epm-a /opt/epm/releases/demo-001/venv/bin/python \
  /opt/epm/releases/demo-001/configure_workspace.py \
  --config /var/lib/epm-a/restore-bootstrap.json \
  --workspace /var/lib/epm-a/unused-restore-source
```

The current restore policy rejects a destination equal to the configured live workspace even if that path has never been initialized. Using normal `config.json` for this restore produced `Backup destination must be outside the live workspace`. The restore-only locator satisfies that policy without changing the runtime locator or creating an extra initialized workspace.

Validate and restore, entering **A's passphrase** at each prompt:

```bash
sudo -u epm-a env TMPDIR=/var/lib/epm-a/tmp \
  /opt/epm/releases/demo-001/venv/bin/python -m app \
  --config /var/lib/epm-a/restore-bootstrap.json \
  validate-archive /var/backups/epm-a/seed.epm-backup

sudo -u epm-a env TMPDIR=/var/lib/epm-a/tmp \
  /opt/epm/releases/demo-001/venv/bin/python -m app \
  --config /var/lib/epm-a/restore-bootstrap.json \
  restore /var/backups/epm-a/seed.epm-backup /var/lib/epm-a/workspace

sudo -u epm-a env TMPDIR=/var/lib/epm-a/tmp \
  /opt/epm/releases/demo-001/venv/bin/python -m app \
  --config /var/lib/epm-a/config.json workspace-status
```

Expect archive validation, successful restoration, and `Workspace ready` with A's original ID from section 1.

## 13. Configure and restore B

In the **VM**, create B's configurations once, skipping any already created correctly:

```bash
sudo -u epm-b /opt/epm/releases/demo-001/venv/bin/python \
  /opt/epm/releases/demo-001/configure_workspace.py \
  --config /var/lib/epm-b/config.json \
  --workspace /var/lib/epm-b/workspace

sudo -u epm-b /opt/epm/releases/demo-001/venv/bin/python \
  /opt/epm/releases/demo-001/configure_workspace.py \
  --config /var/lib/epm-b/restore-bootstrap.json \
  --workspace /var/lib/epm-b/unused-restore-source
```

Validate and restore, entering **B's passphrase** at each prompt:

```bash
sudo -u epm-b env TMPDIR=/var/lib/epm-b/tmp \
  /opt/epm/releases/demo-001/venv/bin/python -m app \
  --config /var/lib/epm-b/restore-bootstrap.json \
  validate-archive /var/backups/epm-b/seed.epm-backup

sudo -u epm-b env TMPDIR=/var/lib/epm-b/tmp \
  /opt/epm/releases/demo-001/venv/bin/python -m app \
  --config /var/lib/epm-b/restore-bootstrap.json \
  restore /var/backups/epm-b/seed.epm-backup /var/lib/epm-b/workspace

sudo -u epm-b env TMPDIR=/var/lib/epm-b/tmp \
  /opt/epm/releases/demo-001/venv/bin/python -m app \
  --config /var/lib/epm-b/config.json workspace-status
```

Expect B's distinct original ID from section 1. In this session, B initially failed before extraction with `Permission denied: /tmp/easy-property-management-locks/restore-....lock`. The restore lock uses the process's temporary directory, and the shared directory was not writable by B. The successful workaround was a private `/var/lib/epm-b/tmp` and explicit `sudo -u epm-b env TMPDIR=...`. Use the same pattern for both accounts in CLI operations. Do not make A's locks or workspace world-writable, run the restore as root, or remove another process's locks.

## 14. Configure systemd automatic startup

In the **VM**, open:

```bash
sudo nano /etc/systemd/system/epm@.service
```

Paste:

```ini
[Unit]
Description=EPM demo workspace %i
After=network-online.target
Wants=network-online.target
StartLimitIntervalSec=60
StartLimitBurst=3

[Service]
Type=simple
User=epm-%i
Group=epm-%i
WorkingDirectory=/var/lib/epm-%i
Environment=PYTHONUNBUFFERED=1
Environment=PYTHONDONTWRITEBYTECODE=1
Environment=TMPDIR=/var/lib/epm-%i/tmp
EnvironmentFile=/etc/epm/%i.env
ExecStart=/opt/epm/releases/demo-001/venv/bin/python -m app --config /var/lib/epm-%i/config.json serve --port ${EPM_PORT}
Restart=on-failure
RestartSec=5
TimeoutStopSec=60
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true
ProtectSystem=strict
ReadWritePaths=/var/lib/epm-%i /var/backups/epm-%i
MemoryHigh=1G
MemoryMax=1500M
CPUQuota=90%

[Install]
WantedBy=multi-user.target
```

Save in nano with **Ctrl+O**, **Enter**, **Ctrl+X**. Create `/etc/epm/a.env` using `sudo nano /etc/epm/a.env`, containing:

```text
EPM_PORT=8001
```

Create `/etc/epm/b.env` using `sudo nano /etc/epm/b.env`, containing:

```text
EPM_PORT=8002
```

These files contain no secrets; keep them root-owned and readable by systemd. Both private temporary directories from section 9 must exist. The service limits reserve headroom on the 4 GB VM, but are starting limits requiring measurement, not proof of workload capacity.

Validate and start:

```bash
sudo systemd-analyze verify /etc/systemd/system/epm@.service
sudo systemctl daemon-reload
sudo systemctl enable --now epm@a epm@b
sudo systemctl status epm@a epm@b --no-pager

curl --fail --silent --show-error \
  http://127.0.0.1:8001/openapi.json -o /dev/null \
  -w 'Workspace A: HTTP %{http_code}\n'
curl --fail --silent --show-error \
  http://127.0.0.1:8002/openapi.json -o /dev/null \
  -w 'Workspace B: HTTP %{http_code}\n'
sudo ss -ltnp
```

Expect both services `active (running)`, both endpoint checks HTTP 200, and application listeners on loopback only. An OpenAPI response checks reachability; it is not full domain/workspace readiness evidence. For startup failures:

```bash
sudo journalctl -u epm@a -u epm@b -n 80 --no-pager
```

There must be only one owning server process per workspace. Stop the relevant service before CLI validation, backup, or restore operations; do not start a second server against the same directory.

## 15. Open the private demo from the Mac

Use the **Mac terminal**, not Cloud Shell or the VM. Install the CLI if missing:

```bash
brew install --cask gcloud-cli
```

Open a new terminal if needed, then:

```bash
gcloud --version
gcloud auth login
```

Choose the Gmail account authorized for the project. No service-account key file is required for this administrator workflow. [Google Homebrew instructions](https://docs.cloud.google.com/sdk/docs/downloads-homebrew)

Start the SSH forwarding session:

```bash
gcloud compute ssh epm-demo \
  --project=project-47b72bb7-ba90-42c9-910 \
  --zone=us-west1-b \
  --tunnel-through-iap \
  -- -N \
  -o ExitOnForwardFailure=yes \
  -o ServerAliveInterval=30 \
  -L 127.0.0.1:18001:127.0.0.1:8001 \
  -L 127.0.0.1:18002:127.0.0.1:8002
```

Accept SSH-key generation if prompted. An idle terminal after connection is expected; leave it open. In the **Mac browser**, open:

- Workspace A: <http://127.0.0.1:18001/home>
- Workspace B: <http://127.0.0.1:18002/home>

The forwarding ports bind only to the Mac's loopback interface. If a local port is occupied, change its `18001`/`18002` value and the matching browser URL, preserving the VM's `8001`/`8002`. **Ctrl+C** closes the forwarding session without stopping the VM services. Re-run the tunnel command to reconnect. Cloud Shell forwarding does not create these listeners on the Mac.

## 16. Acceptance and remaining work

Record results before describing the demo as fully accepted:

| Area | Check / current evidence |
| --- | --- |
| Installation | Resource verification supplied in session; both systemd/HTTP checks reported complete |
| Restore and identity | Separate synthetic datasets verified on Mac; both VM restores reported complete; compare exact IDs in section 1 |
| Browser happy paths | Private tunnel reported complete; check Home, Properties, Leasing, Money, Maintenance, Settings, and evidence downloads in both workspaces |
| Persistence and separation | Change a harmless preference in A; refresh and restart A; confirm persistence and no change in B |
| Reboot | Reboot during an agreed interruption, reconnect, and repeat service/HTTP/browser checks; not yet recorded |
| Concurrency and retry | Check stale-revision conflicts and original-result recovery from separate browser sessions; not validated by HTTP 200 checks |
| Failure / rollback | Failed restores above stopped before extraction; broader full-disk, process failure, and recovery drills remain pending |
| Backup / restore | Initial encrypted Mac exports are off-host seed recovery points; recurring backups of subsequent VM changes and a fresh recovery drill remain pending |
| Capacity / query budgets | Measure concurrent browser use, report/backup load, memory, latency, disk growth, and query behavior; no capacity certification from VM size alone |
| Public access | Blocked pending the hosted authentication/session/authorization contract; SSH forwarding is administrator-only |
| Cost / lifecycle | Review trial expiry, resource usage, intended demo end date, and retention/cleanup ownership |

Inspect operating state in the **VM** with:

```bash
sudo systemctl status epm@a epm@b --no-pager
free -h
df -h /
sudo du -sh /var/lib/epm-a/workspace /var/lib/epm-b/workspace
```

For an intentional restart of A:

```bash
sudo systemctl restart epm@a
sudo systemctl status epm@a --no-pager
```

If startup retries reach the service limit, inspect and correct the logged cause before `sudo systemctl reset-failed epm@a` and `sudo systemctl start epm@a`. Do not repeatedly restart without addressing the failure.

### Backups after the seed restore

Not configured by the completed setup. The seed archives do not capture later edits. Before relying on the demo, choose an off-host destination and retention policy, create encrypted application backups while the relevant server is stopped, validate them, transfer complete archives off the VM, and rehearse restore into a new private path with matching runtime resources. Stop only the affected workspace and restore service after the operation. A different directory on the VM's boot disk is staging, not protection from VM loss.

For a manual A backup, with a new filename each time, run in the **VM**:

```bash
sudo systemctl stop epm@a
sudo -u epm-a env TMPDIR=/var/lib/epm-a/tmp \
  /opt/epm/releases/demo-001/venv/bin/python -m app \
  --config /var/lib/epm-a/config.json \
  backup --output /var/backups/epm-a/manual-001.epm-backup
sudo -u epm-a env TMPDIR=/var/lib/epm-a/tmp \
  /opt/epm/releases/demo-001/venv/bin/python -m app \
  --config /var/lib/epm-a/config.json \
  validate-archive /var/backups/epm-a/manual-001.epm-backup
sudo systemctl start epm@a
sudo systemctl status epm@a --no-pager
```

Run individually. If backup/validation fails, investigate and explicitly return the service to a known state. Export the validated archive through a private administrator staging directory; do not grant world access to service directories. Repeat independently for B. Retain decryption passphrases separately. The automatic-backup feature uses an OS credential store; this headless server's credential-store integration has not been configured or verified.

### Future public access and shutdown

The remaining application implementation and Cloudflare deployment steps are tracked in the [public-access plan](../../qualification/HOSTED_DEMO_PUBLIC_ACCESS_PLAN.md). Its design recommendations were accepted October 23, 2026; implementation and qualification remain pending. It does not permit publishing this private release.

Public hosting requires the [hosted demo design](../../design/HOSTED_DEMO_DESIGN.md), including authenticated identity bound to the correct workspace, validated origins/sessions, CSRF protection, and authorization for APIs, files, audit, and recovery. Cloudflare Tunnel/Access alone do not supply the missing application contract. No public DNS or Cloudflare routing was configured in this session.

At demo end, stop access and services, retain/export data according to the chosen policy, and review Google resources and billing. Stopping a VM does not remove retained disks or all other chargeable resources. Preserve needed recovery archives before any deletion; account deletion and infrastructure destruction are not part of this runbook's completed actions.
