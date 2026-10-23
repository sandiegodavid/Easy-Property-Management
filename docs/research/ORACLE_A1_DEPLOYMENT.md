# Oracle Always Free A1 ARM deployment runbook

Prepared October 15, 2026. Audience: the administrator installing a two-operator synthetic demo, not the property manager using it.

## Scope and current release gate

This runbook applies the [Hosted Demo Design](../hosting/design/HOSTED_DEMO_DESIGN.md), [consolidated Hosting Plan](../hosting/Hosting_Plan.md), and [release-wheel deployment procedure](../../manual/deployment.md) to one Oracle ARM VM. It uses two Unix service accounts, two independent workspaces, one supervised application process per workspace, and encrypted off-host recovery points. Managed Postgres, billing, relays, managed AI, and database replication are not required for this experiment.

**Provisioning and private administrator testing can proceed. Public browser access remains blocked on the hosted application changes in the Hosted Demo Design.** The current application has no hosted login, workspace membership enforcement, or hosted session/CSRF contract. Its [transport middleware](../../application/apps/server/app/platform/browser_transport.py) accepts loopback hosts and origins only, and its [CLI](../../application/apps/server/app/__main__.py) binds to `127.0.0.1`.

| Stage                                                                | Current disposition                                                              |
| -------------------------------------------------------------------- | -------------------------------------------------------------------------------- |
| Oracle VM, ARM runtime, release installation and separate workspaces | Follow sections 1–6                                                              |
| Private administrator browser acceptance                             | Follow section 7; SSH credentials grant host administration, not operator access |
| Two operators using public HTTPS addresses                           | Stop at section 8 until a tested hosted release exists                           |
| Real customer information or shared-portfolio collaboration          | Outside this synthetic-demo runbook                                              |

Do not make the current app public by changing its bind address, rewriting Host/Origin to loopback, adding a development-origin exception, or trusting an email header. Cloudflare Access alone does not implement the missing application contract. This file does not mark hosting/authentication backlog items delivered.

## 1. Record the deployment and obtain capacity

Create a deployment record containing the source commit, wheel checksum, schema-bundle checksum, Python patch version, installed dependency versions, OCI region/instance OCID, SSH administrator, workspace IDs, intended demo expiry, backup destination, and recovery-key custodian. Keep provider credentials and passphrases out of this record.

Suggested initial allocation, subject to account eligibility and measurement:

| Setting               | Select                                                                                       |
| --------------------- | -------------------------------------------------------------------------------------------- |
| Region                | Your OCI tenancy's home region; choose a suitable US home region when creating a new account |
| Shape                 | `VM.Standard.A1.Flex`, ARM64                                                                 |
| Capacity              | One VM, 2 OCPUs and 8 GB RAM; this is a starting allocation, not measured EPM capacity       |
| Image                 | An Always Free-eligible Canonical Ubuntu 24.04 ARM64 platform image                          |
| Disk                  | A 50 GB boot volume; keep all existing boot/block volumes within the tenancy allowance       |
| Application processes | `epm-a` on loopback port 8001; `epm-b` on loopback port 8002                                 |
| External dependencies | Disabled for the synthetic demo; local file storage                                          |

Oracle currently documents 1,500 A1 OCPU-hours and 9,000 GB-hours per month, equivalent to 2 OCPUs / 12 GB for Always Free tenancies, and 200 GB combined boot/block storage. These are tenancy-wide allowances, not per-instance allowances. Confirm the actual account limits, image eligibility, and estimated charge in the Console before creation; older 4 OCPU / 24 GB instructions are not this runbook's assumption. Capacity can be unavailable, and idle instances can be reclaimed. Do not generate artificial load to avoid reclamation. See [Oracle's Always Free resource rules](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm).

Use a dedicated demo compartment and budget alerts. Alerts do not cap spending. Avoid adding a NAT gateway, paid load balancer, additional volumes, or paid images to solve a problem that does not require them. Domain registration, off-host backups, and any chargeable networking remain separate costs.

If A1 capacity is unavailable, try another availability domain in the same home region or wait. Do not accept a paid shape silently. For a scheduled demo, use the paid fallback described in the source plans if necessary.

## 2. Create the VM and restrict networking

In the OCI Console:

1. Create/select the demo compartment and a VCN with Internet connectivity.
2. Create the Ubuntu ARM instance with the settings above. Add your SSH public key and retain its private key on your administrator device.
3. For this simple administrator setup, assign a public IP in a public subnet. Record the address and check its current account-specific pricing. The application itself will have no public listener.
4. Permit inbound TCP 22 only from your administrator public IP `/32`, or the smallest trusted administration CIDR. If that address changes, update the rule through the OCI Console.
5. Check **all** attached subnet security lists and network security groups. Remove any default rule that still permits SSH from `0.0.0.0/0`; a restrictive NSG does not cancel another rule granting access.
6. Do not add public ingress for 80, 443, 8001, 8002, or the future origin ports. Keep required return traffic and system networking working. Inspect the image's host firewall too; do not flush its rules.
7. Allow outbound package downloads and normal DNS/time synchronization. Only the later hosted stage needs Cloudflare Tunnel egress; consult its current destination allowlist rather than opening inbound web ports.

OCI's [instance creation guide](https://docs.oracle.com/en-us/iaas/Content/Compute/Tasks/launchinginstance.htm) describes VCN/image/SSH choices; [security-list documentation](https://docs.oracle.com/en-us/iaas/Content/Network/Concepts/securitylists.htm) describes the network rule boundary. OCI Bastion is an alternative administration path, but is not configured by the commands below.

From your administrator computer, replacing the key and address:

```bash
ssh -i /absolute/path/to/oci-admin-key ubuntu@VM_PUBLIC_IP
```

On the VM:

```bash
uname -m
cat /etc/os-release
sudo apt-get update
sudo apt-get install -y ca-certificates curl python3 python3-venv python3-pip
timedatectl status
```

Expect `aarch64`. Keep UTC system time synchronized; property time zones remain application data. Apply available security updates and reboot if required before installation. Preserve a working second SSH session when changing SSH/firewall settings. Do not give demo operators SSH accounts or keys.

## 3. Prepare the release and synthetic workspaces off-host

### Application bundle

Build from one approved, recorded source revision using [the combined-wheel build](../../README.md#production-build-and-packaging-instructions). Supply the complete bundle required by [the VM guide](../../manual/deployment.md#release-contents-required-before-deployment):

```text
<release-id>/
├── easy_property_management-0.1.0-py3-none-any.whl
├── stage_schema_resources.py
├── verify_installation.py
├── configure_workspace.py
├── schema-resources/
│   ├── alembic.ini
│   └── database/sqlite-migrations/...
├── RELEASE.txt
└── SHA256SUMS
```

The wheel version is illustrative. `RELEASE.txt` must identify the source revision and tested Python patch version; `SHA256SUMS` must cover the wheel, helpers and every schema-resource file. Verify the manifest against a separately trusted release/checksum record. Do not combine schema files from another build using the same package version.

The application wheel is pure Python, but dependencies can contain native code. A copied macOS virtual environment or macOS dependency wheelhouse is not a Linux ARM deployment. Resolve and smoke-test Linux ARM64 dependencies using the selected interpreter. For an offline install, supply an appropriately tested Linux ARM64/Python wheelhouse. Build frontend assets elsewhere; Node/npm and a source checkout are not needed on the VM.

### Two independent seeded exports

On the development computer, use the [synthetic demo generator](../../application/demo/README.md). From `application/`, prepare operator A with a **new empty destination**:

```bash
.venv/bin/python demo/seed.py \
  --workspace "$HOME/Desktop/Property-Management-Data/oracle-demo-a" \
  --local-config "$HOME/Desktop/Property-Management-Data/oracle-demo-a.config.json"
.venv/bin/python demo/verify.py \
  --config "$HOME/Desktop/Property-Management-Data/oracle-demo-a.config.json"
.venv/bin/python -m app \
  --config "$HOME/Desktop/Property-Management-Data/oracle-demo-a.config.json" \
  export "$HOME/Desktop/Property-Management-Data/oracle-demo-a.epm-export"
```

Repeat with `oracle-demo-b` throughout for operator B. Enter export passphrases at the prompt and retain them separately. Independently seed B; restoring A's archive twice would duplicate workspace/business identities. Do not transfer running SQLite files, desktop credential stores, development config locators, or the checkout as a substitute for portable exports.

Transfer the release directory to `/home/ubuntu/epm-upload/<release-id>/` using SCP/SFTP. Transfer the two encrypted exports separately to the administrator's private staging directory. No cloud credentials belong in the release bundle.

## 4. Install an ARM-compatible Python runtime and the release

Use **CPython 3.14** for the current source. Although package metadata and the generic VM guide say “3.12+,” current modules use Python 3.14's unparenthesized multiple-exception syntax. Do not assume Ubuntu 24.04's default Python can parse this release. [Python 3.14 language changes](https://docs.python.org/3.14/whatsnew/3.14.html) document the syntax.

One installation option is uv-managed CPython. This adds uv only as an installer; the service runs the installed Python directly. Download and inspect the installer before running it as `ubuntu`, using a version approved for the deployment. See [uv installation](https://docs.astral.sh/uv/getting-started/installation/).

```bash
curl --proto '=https' --tlsv1.2 -LsSf https://astral.sh/uv/install.sh -o /tmp/epm-uv-install.sh
less /tmp/epm-uv-install.sh
sh /tmp/epm-uv-install.sh
"$HOME/.local/bin/uv" --version
```

Replace `REPLACE_WITH_RELEASE_ID` once below with the actual release directory name. These shell variables are administrator convenience values, not application secrets:

```bash
EPM_RELEASE='REPLACE_WITH_RELEASE_ID'
EPM_ARTIFACTS="/home/ubuntu/epm-upload/$EPM_RELEASE"
EPM_VENV="/opt/epm/releases/$EPM_RELEASE/venv"

cd "$EPM_ARTIFACTS"
sha256sum --check SHA256SUMS

sudo install -d -o root -g root -m 0755 /opt/epm /opt/epm/releases
sudo install -d -o ubuntu -g ubuntu -m 0755 /opt/epm/python "/opt/epm/releases/$EPM_RELEASE"
UV_PYTHON_INSTALL_DIR=/opt/epm/python "$HOME/.local/bin/uv" python install 3.14
UV_PYTHON_INSTALL_DIR=/opt/epm/python "$HOME/.local/bin/uv" venv --python 3.14 --seed "$EPM_VENV"

"$EPM_VENV/bin/python" --version
"$EPM_VENV/bin/python" -m pip install "$EPM_ARTIFACTS/easy_property_management-0.1.0-py3-none-any.whl"
"$EPM_VENV/bin/python" -m pip check
"$EPM_VENV/bin/python" "$EPM_ARTIFACTS/stage_schema_resources.py" "$EPM_ARTIFACTS/schema-resources"
"$EPM_VENV/bin/python" "$EPM_ARTIFACTS/verify_installation.py"
"$EPM_VENV/bin/python" -c 'import app, compileall, pathlib; assert compileall.compile_dir(pathlib.Path(app.__file__).parent, quiet=1)'
"$EPM_VENV/bin/python" -m pip freeze > "/opt/epm/releases/$EPM_RELEASE/installed-requirements.txt"
install -m 0644 "$EPM_ARTIFACTS/configure_workspace.py" "/opt/epm/releases/$EPM_RELEASE/configure_workspace.py"
sudo chown -R root:root "/opt/epm/releases/$EPM_RELEASE" /opt/epm/python
```

If the release manifest pins a specific 3.14 patch, use it in both uv commands. Otherwise record the selected patch and reproduce it for recovery. Do not replace Ubuntu's system Python. The shared managed interpreter and retained configuration helper live under `/opt/epm` so services do not depend on access to the administrator's home directory. [uv's managed-Python guide](https://docs.astral.sh/uv/guides/install-python/) and [installation-directory setting](https://docs.astral.sh/uv/reference/environment/#uv_python_install_dir) describe the managed interpreter layout.

Stop if installation requires an unavailable ARM dependency, schema staging fails, compilation fails, or `pip check` fails. Correct the release/environment; do not bypass those checks. Use a fresh release environment for subsequent deployments, and do not modify this environment while a service uses it.

## 5. Create private service accounts and restore the demos

For a fresh host, as `ubuntu` with the variables from section 4 still set:

```bash
sudo useradd --system --user-group --home-dir /var/lib/epm-a --shell /usr/sbin/nologin epm-a
sudo useradd --system --user-group --home-dir /var/lib/epm-b --shell /usr/sbin/nologin epm-b
sudo install -d -o epm-a -g epm-a -m 0700 /var/lib/epm-a /var/backups/epm-a
sudo install -d -o epm-b -g epm-b -m 0700 /var/lib/epm-b /var/backups/epm-b
sudo install -d -o root -g root -m 0755 /etc/epm
```

If an account or populated directory already exists, inspect it instead of recreating/resetting it. Runtime code is root-owned and readable by both services; each workspace/config/archive directory is private to its service user. Neither user receives sudo or container-management access.

Install operator A's encrypted export into its private archive directory, substituting the actual staging path:

```bash
sudo install -o epm-a -g epm-a -m 0600 \
  /home/ubuntu/epm-upload/oracle-demo-a.epm-export /var/backups/epm-a/seed.epm-export
sudo -u epm-a "$EPM_VENV/bin/python" "/opt/epm/releases/$EPM_RELEASE/configure_workspace.py" \
  --config /var/lib/epm-a/config.json --workspace /var/lib/epm-a/workspace
sudo -u epm-a "$EPM_VENV/bin/python" -m app --config /var/lib/epm-a/config.json \
  validate-archive /var/backups/epm-a/seed.epm-export
sudo -u epm-a "$EPM_VENV/bin/python" -m app --config /var/lib/epm-a/config.json \
  restore /var/backups/epm-a/seed.epm-export /var/lib/epm-a/workspace
sudo -u epm-a "$EPM_VENV/bin/python" -m app --config /var/lib/epm-a/config.json workspace-status
```

Repeat for B, substituting `epm-b` and B's export. **Do not initialize before restoring.** Enter passphrases interactively; do not put them in arguments, environment files or unit definitions. Record and compare both workspace IDs: they must be distinct and match their respective seed exports. Run these CLI operations while the workspace's server is stopped.

The portable restore preserves business records and retained evidence, not desktop credentials. Use local file storage, leave AI/provider credentials absent, and keep external messaging/payment integrations disabled.

## 6. Supervise one process per workspace

Use `sudoedit /etc/systemd/system/epm@.service` to create this template. Replace `REPLACE_WITH_RELEASE_ID` in `ExecStart` with the pinned release from section 4; systemd does not inherit your shell's `EPM_VENV` variable.

```ini
[Unit]
Description=EPM private demo workspace %i
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
EnvironmentFile=/etc/epm/%i.env
ExecStart=/opt/epm/releases/REPLACE_WITH_RELEASE_ID/venv/bin/python -m app --config /var/lib/epm-%i/config.json serve --port ${EPM_PORT}
Restart=on-failure
RestartSec=5
TimeoutStopSec=60
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true
ProtectSystem=strict
ReadWritePaths=/var/lib/epm-%i /var/backups/epm-%i
MemoryHigh=1500M
MemoryMax=2G
CPUQuota=90%

[Install]
WantedBy=multi-user.target
```

Create `/etc/epm/a.env` containing `EPM_PORT=8001` and `/etc/epm/b.env` containing `EPM_PORT=8002`, owned by root and mode `0644`. These files contain no secrets. Memory/CPU limits are starting values to measure on the proposed 8 GB / 2 OCPU host; an out-of-memory kill is a failed capacity test, not a successful quota response.

```bash
sudo systemd-analyze verify /etc/systemd/system/epm@.service
sudo systemctl daemon-reload
sudo systemctl enable --now epm@a epm@b
sudo systemctl status epm@a epm@b --no-pager
sudo ss -ltnp
curl --fail http://127.0.0.1:8001/openapi.json -o /dev/null
curl --fail http://127.0.0.1:8002/openapi.json -o /dev/null
```

Confirm the application listeners are only `127.0.0.1:8001` and `127.0.0.1:8002`. Use `journalctl -u epm@a -n 100 --no-pager` for startup failures. A listening port alone does not establish workspace readiness. Do not run another CLI server or multiple Uvicorn workers against either workspace. Before CLI validation/backup/restore, stop the corresponding service and wait until it has released the workspace.

## 7. Accept the private installation

For this runbook, administrator-only SSH forwarding is the explicit private access arrangement. It preserves browser loopback Host/Origin values and does not create public website access. The administrator already has host authority over both workspaces; these tunnels are **not** operator authentication or isolation.

From the administrator computer, keeping the terminal open:

```bash
ssh -i /absolute/path/to/oci-admin-key -N -o ExitOnForwardFailure=yes \
  -L 127.0.0.1:18001:127.0.0.1:8001 \
  -L 127.0.0.1:18002:127.0.0.1:8002 ubuntu@VM_PUBLIC_IP
```

Open `http://127.0.0.1:18001/home` and `http://127.0.0.1:18002/home` in the administrator's browser. If these local ports are occupied, change only the local side of the forwarding and corresponding browser URL. Do not grant untrusted users SSH access as a workaround for the hosted gate.

Verify both workspaces and their distinct IDs, Home, Properties, Owners, Leasing, file metadata/downloads, and Settings. Confirm Maple House's two tenants and Spruce House's three students. Make a harmless preference change in A and confirm it survives an A service restart without changing B. Reboot the VM and repeat readiness/browser checks. No real provider calls should occur.

## 8. Hosted-access gate and subsequent Cloudflare setup

**Stop here for public demo access with the current release.** Do not route a hostname to either existing local-mode server. The following is the deployment sequence for a future tested hosted release, not an available `--hosted` CLI option or gateway included in this repository.

Before publishing DNS/tunnel routes, obtain acceptance evidence for:

- A hosted launch/configuration contract with an exact HTTPS hostname per workspace and origin verification independent of the local policy.
- Verified Cloudflare Access JWT signature, issuer, audience and expiry at the origin, with subject-to-operator/workspace binding. Neither email headers nor display codes grant authority.
- Revocable sessions and expiry, CSRF protection on unsafe methods, authorization on bootstrap/API/files/audit/recovery/receipts, verified actor propagation, and restricted administration/backup endpoints.
- Cross-device conflicts and original-result recovery; independent drafts or explicit draft takeover; no background overwrite of unsaved edits; no offline mutation queue.
- Enforced server-side storage/upload quotas, demo expiry/reset, and a tested off-host restore. A displayed `du` value is monitoring, not quota enforcement.

Then configure the hosting layer in this order:

1. Put the domain in Cloudflare and create two Access applications, one for `demo-a.example.com`, one for `demo-b.example.com`.
2. Configure email one-time PIN login. Allow only A's provisioned email on A's application and B's on B's; avoid broad “any valid email” policies. Start with the design's eight-hour sessions and 14-day demo expiry, subject to the application's implemented revocation controls. See [Cloudflare OTP](https://developers.cloudflare.com/cloudflare-one/integrations/identity-providers/one-time-pin/).
3. Record each application's issuer/team domain and audience in the protected hosted registry outside the portable workspaces. Provision identity bindings through the hosted release's administration interface.
4. Install an official Linux ARM64 `cloudflared` release and configure a named tunnel using the [official tunnel guide](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/local-management/create-local-tunnel/). Protect its credentials from both application users; do not record tunnel secrets in shell history or the workspace.
5. Deploy the release's authenticated origin processes/gateway using its tested launcher. Replace the local-only service launch configuration as that release requires, while retaining one writer per workspace. Do not invent a reverse-proxy rewrite to bypass the current middleware.
6. Map each hostname to its fixed authenticated origin. Configure unmatched hostnames to return 404. Have the origin validate JWTs as documented by [Cloudflare](https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/authorization-cookie/validating-json/), even when Access also checks at the edge.
7. Allow outbound tunnel traffic on port 7844: UDP for QUIC or TCP for HTTP/2, using Cloudflare's [firewall requirements](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/configure-tunnels/tunnel-with-firewall/). Keep inbound web/application ports closed.
8. Prevent shared caching of private HTML, API responses and downloads; only fingerprinted public assets may be shared-cacheable. Run the matrix below before handing out addresses.

Public-browser origins must remain their real HTTPS origins throughout authorization. Authentication failures must not fall through to a localhost app. Disable public routes if the hosted boundary is unavailable; use the private administrator path for diagnosis.

## 9. Backups, restore and replacement releases

For the current headless installation, use an administrator-run manual backup with a passphrase prompt. An unattended desktop keyring is not assumed. Configure automatic backup only after its supported credential store works under the actual service identity; otherwise disclose the manual schedule.

For A, using the pinned `EPM_VENV` from section 4:

```bash
sudo systemctl stop epm@a
sudo -u epm-a "$EPM_VENV/bin/python" -m app --config /var/lib/epm-a/config.json \
  configure-backup-destination /var/backups/epm-a
sudo -u epm-a "$EPM_VENV/bin/python" -m app --config /var/lib/epm-a/config.json backup
sudo -u epm-a "$EPM_VENV/bin/python" -m app --config /var/lib/epm-a/config.json \
  validate-archive /var/backups/epm-a/REPLACE_WITH_CREATED_ARCHIVE.epm-backup
sudo systemctl start epm@a
```

Repeat for B at a different time. If backup/validation fails, investigate before claiming protection; explicitly restore the service to a known usable state. Transfer completed encrypted archives to another provider or a separately controlled administrator device, with passphrases recoverable independently of this VM. A different directory on the boot disk is only staging, not off-host protection. Use a private administrator transfer location when copying root/service-private archives out; do not make service directories world-readable.

Initial policy: daily complete backups, seven daily off-host copies, and a disclosed recovery point of up to 24 hours of edits. Keep the release bundle and seed separately. Database replication without matching attachment recovery points is not a complete workspace backup. Do not promise automatic schema migration, minutes of whole-workspace data loss, or an SLA from the commercial plan.

Before relying on backups, rehearse [restore](../../manual/data-and-recovery.md#restore-a-backup) into a **new** private folder, with its own new config locator, matching release and server stopped. Validate the archive, restore database/files together, run `workspace-status`, then open a trial instance to compare IDs, leases/participants, financial totals, attachments and audit history. Do not run the trial and original as two writers to one folder. In a future hosted deployment, exclude restored copies from public routing and revoke old sessions before cutover; the business archive does not restore hosted authorization or credentials.

For upgrades or resets: drain and stop the affected service, create a final validated recovery point, install a fresh versioned runtime or independently seeded workspace, verify it, and switch the pinned service/config explicitly. Keep the old process fenced off. Restart the one writer and test; never overwrite a live database or merge schema directories. Roll back only to a compatible release/data pair, restoring into a fresh folder when formats differ.

## 10. Acceptance and operating checklist

Record results and release IDs; commands in this document have not been executed against an Oracle VM.

| Area                          | Required evidence                                                                                                                                    |
| ----------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| ARM installation              | `aarch64`, recorded CPython patch, dependency check, compilation and installed assets/schema verification                                            |
| Persistence                   | Independent A/B workspace IDs; committed changes survive restart/reboot; only one process owns each workspace                                        |
| Current private boundary      | Only SSH is remotely reachable; application listeners are loopback-only; administrator forwarding works                                              |
| Hosted access, before release | Missing/invalid/expired JWT, foreign Host/Origin and missing CSRF fail; A cannot read B by changing URLs, IDs, file paths, recovery or receipt keys  |
| Concurrency/retry             | Two devices conflict on stale revisions; interrupted financial writes recover their original result without another effect; dirty input is preserved |
| Rollback/failure              | Failed domain/audit/commit has no partial success; unavailable auth keys/tunnel, full disk and failed reset have bounded, visible failure            |
| Backup/restore                | Fresh-host compatible restore recovers complete records and exact evidence, excludes credentials, and preserves audit/receipt history                |
| Performance/query budgets     | Four active browsers plus a report/backup workload; record peak memory, latency, lock waits and bounded refresh/query costs                          |
| Demo restrictions             | Synthetic content only, no external credentials/calls, enforced hosted quotas and expiry, restricted host administration                             |
| Recovery/cost                 | Off-host backup age monitored; cloud budget/usage reviewed; capacity/reclamation and domain renewal have an owner                                    |

Check `systemctl status`, service restart counts, `free -h`, `df -h`, workspace disk growth and backup age. Restrict and rotate logs; do not log bodies, tenant narratives, credentials or Access tokens. An external health check must verify intended readiness through the approved authentication path rather than exposing a diagnostic endpoint publicly. A tunnel failure or reclaimed VM should lead to recovery or an explicit outage, not a bypass of authorization.

On demo expiry, disable/revoke access first, drain writes, stop the service, and retain or remove the workspace and its backups according to the agreed retention policy. Review provider resources separately so unused capacity does not remain billable. No VM, tunnel, DNS record or account was created by writing this runbook.
