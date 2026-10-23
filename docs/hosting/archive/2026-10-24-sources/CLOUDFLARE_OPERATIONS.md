# Cloudflare operations log

This is the cumulative Cloudflare operations record. Append new operations here
under dated headings in chronological order; do not create separate daily logs.
Dates use America/Los_Angeles unless explicitly marked UTC. Keep observed,
operator-reported and pending work distinct. Never include credentials,
passphrases or operator email addresses.

The October 23 and October 24 daily records are consolidated below. Statements
about missing setup describe the state on their entry date; later entries record
subsequent progress. Continue from the
[public-access checkpoint](../../qualification/HOSTED_DEMO_PUBLIC_ACCESS_PLAN.md).

## Human review guide — October 24, 2026

This guide summarizes the latest **recorded** setup and links to the evidence.
The dated entries below remain the detailed operation history. Writing the guide alone does not perform setup or verification; new operations
are explicitly recorded in the dated history below. Recorded
process IDs, memory samples and backup ages are snapshots, not live monitoring.

### Overall result and boundary

Two separate synthetic portfolios run privately on the Google Cloud VM. Their
current hosted application processes require identity and authorization; both
operators have now been activated after verified pending enrollment. Cloudflare DNS is Active, Access settings have been
reviewed by the operator, and a named tunnel has been created. **Exact A/B DNS and provisional origin routes
are now installed for acceptance; the tunnel is running but remains disabled at
boot. Both intended verified identities are active; no invitations have been sent.** Both public
hostnames redirect unauthenticated browser requests to Cloudflare Access. Real
PIN/pending enrollment and administrator activation passed; both authenticated Home pages subsequently loaded, as confirmed by the operator. Full
authenticated isolation/cache/performance acceptance remains pending.

Both current administrator-reference export/upload/decryption drills have now
passed, in addition to the business-backup recovery drills. Post-enrollment exports have now been uploaded, independently downloaded/decrypted
and compared with current approved/pending identity bindings. Earlier exports remain retained.

### Infrastructure, identity and path inventory

| Component | Latest recorded configuration | Evidence / qualification boundary |
| --- | --- | --- |
| Google Cloud | Project `project-47b72bb7-ba90-42c9-910`, VM `epm-demo`, Oregon `us-west1-b`; Ubuntu 24.04 x86_64, E2 medium, 30 GB disk | [Initial VM setup](../../deployment/GOOGLE_CLOUD_DEMO_DEPLOYMENT.md); the trial/billing Console remains authoritative for actual credit/expiry |
| Administrator SSH | IAP tunnel; VM tag `epm-admin`; instructed SSH source range `35.235.240.0/20`, TCP 22 | Initial firewall/IAP procedure is in the Google guide; no fresh effective-firewall audit was performed for this summary |
| Domain | `epmdemo.xyz`, Cloudflare Full DNS / Free; Porkbun remains registrar | Operator screenshot showed Active after delegation to `bonnie.ns.cloudflare.com` and `vasilii.ns.cloudflare.com` |
| Public application origins | Planned exact `https://demo-a.epmdemo.xyz` and `https://demo-b.epmdemo.xyz` | Provisional HTTPS routes now present; real PIN/enrollment and business access pending |
| Identity | Team `epmdemo.cloudflareaccess.com`; two distinct Access audiences; separate supplied A/B sign-in emails | Inputs privately captured; operator confirmed exact-host, single-email Allow, PIN-only login, eight-hour duration, no broad/Bypass grant; real sign-in remains pending |
| Current release | `/opt/epm/releases/signin-nav-20261024/venv`; package 0.1.0, Python 3.14.9; qualified baseline plus narrow sign-in navigation fix | [Fix and verification](../../evidence/HOSTED_DEMO_SIGNIN_NAVIGATION_FIX_2026-10-24.json); wheel SHA-256 `c57d4cfc5803d1ff2cd06b9d49c16bacf068b43b30232388009cd6d15633f95a`; frontend/schema/dependencies unchanged |
| Current processes | `epm-hosted@a.service` and `epm-hosted@b.service`, active/enabled; Unix users `epm-a` / `epm-b`; listeners only `127.0.0.1:8001` / `8002` | [Private switch evidence](../../evidence/HOSTED_DEMO_PRIVATE_SWITCH_2026-10-24.json); one writer per workspace |
| Current workspace locators | `/var/lib/epm-a/hosted-local.json` and `/var/lib/epm-b/hosted-local.json` | Use these in current hosted administration/backup commands |
| Current business data | `/var/lib/epm-a/volume/workspace` and `/var/lib/epm-b/volume/workspace` | Fresh current-format synthetic portfolios; IDs below |
| Storage budget | Root-owned `/var/lib/epm-volumes/epm-a.ext4` and `epm-b.ext4`; each 262144000 bytes, fully allocated; complete ext4 mounts with `rw,nodev,nosuid,noexec` | Both automatically remounted after approved reboot; TMPDIR is each volume's private `tmp`; [boot evidence](../../evidence/HOSTED_DEMO_AB_BOOT_2026-10-24.json) |
| Authorization state | Separate `/var/lib/epm-<instance>/access/hosted-access.sqlite`, outside business volume | Both intended subjects now verified and activated; browser sessions require explicit Continue. Portable business backups cannot grant access |
| Protected configuration | `/etc/epm/hosted-{a,b}.json`; port files `/etc/epm/hosted-{a,b}.env`, root-owned/service-group-readable | Actual contact/emails/AUDs are private inputs, not repository contents |
| Old installation | `demo-001`; old `/var/lib/epm-<instance>/workspace` and `config.json` retained; `epm@a.service` / `epm@b.service` inactive/masked | Historical fallback data only. Do not start alongside the hosted unit or select the old locator for current backups |
| Named tunnel | `epm-demo`, UUID `c29cb930-4166-4105-90a3-32d72fc04f46`; cloudflared 2026.10.3; dedicated non-login `epm-tunnel` user | Initial 404-only check passed; exact A/B origin routes now active/boot-disabled for acceptance; unmatched hostname 404 |
| R2 | Private recovery bucket `epm-private-recovery`; independent A/B deployment/workspace object prefixes and verification ledgers | Real authenticated upload/read-back/restore evidence exists; dashboard privacy/location settings were instructed, not independently inspected |
| Daily operations | Administrator-run encrypted backups, seven successful daily points, separate reference custody | First business points verified; scratch R2 pruning/retry passed with simulated dates; unattended execution and elapsed multi-day history unproven |

Current fresh workspace identities:

| Instance | Current hosted UUID | Retained old private UUID |
| --- | --- | --- |
| A | `611d3445-0cce-4858-a10d-b5d5202d601a` | `0efb09a0-5af2-4e6f-904f-154a50ab9445` |
| B | `facd33be-7ff7-4d91-bff1-9a3f85af658b` | `3390ed71-0bd9-40f7-8e7f-702df257e880` |

The protected configuration's draft enablement window is October 24, 18:51:09 UTC
through November 7, 18:51:09 UTC. It was generated during preparation, before
operator activation. Review the intended trial dates before activation; the
fourteen-day limit is enforced, and documentation does not silently renew it.

### What happened, in order

1. **Initial Google Cloud deployment.** Provisioned the VM, restricted SSH through
   IAP, uploaded checksum-verified release artifacts, installed `demo-001` and
   restored two private portfolios. Corrected project-name versus project-ID use,
   restore destination selection and shared temporary-lock permissions. See the
   [initial installation record](../../deployment/GOOGLE_CLOUD_DEMO_DEPLOYMENT.md).
2. **Scratch qualification and R2 bootstrap.** The operator created the bucket and
   entered credentials privately on the VM. A disposable third workspace exercised
   real SQLite FULL/rollback, concurrent 50 MiB upload admission, encrypted backup,
   R2 full read-back, independent restoration and encrypted reference recovery.
   Corrected loop allocation, temporary upload overlap and new-code permissions;
   built/qualified the pinned wheel and separately approved a scratch boot test.
3. **Domain and Access setup.** Imported parking records, observed pending status,
   discovered Porkbun still had its four nameservers despite account connection,
   then the operator replaced them with Cloudflare's pair. Screenshot confirmed
   Active. Created/reused the Free Zero Trust organization and exact A/B Access
   applications; captured actual issuer/AUDs privately and later reviewed policies.
4. **Tunnel preparation.** Authorized cloudflared on the Mac; account certificate
   stays there. Created the named tunnel; transferred only its scoped credential
   over IAP. Installed the verified Linux binary and stopped 404-only VM service.
5. **Old-data backup and format discovery.** Created/validated old A/B archives.
   Current-release restoration rejected their audit CHECK constraints. The operator
   chose fresh synthetic data and reaffirmed greenfield scope; no compatibility
   layer or migration was added and no validator was weakened.
6. **Fresh candidates and real recovery.** Created new 250 MiB volumes, seeded
   independent portfolios through real application APIs, and verified counts,
   relationships, schema and financial scenarios. Rebound only candidate settings
   to the new UUIDs. Published fresh encrypted A/B archives to R2, independently
   downloaded/restored and verified them. Corrected an audit-comparison helper's
   omission of the legitimate correlated retention event.
7. **Persistent storage.** Reviewed exact fstab/unit candidates, received explicit
   reboot approval, installed only A/B mount entries, rebooted once and confirmed
   automatic remount, full allocation and unchanged original service health.
8. **Private hosted transition.** Received separate approval, stopped/masked A's
   old writer, enabled its hosted replacement and validated it before switching B.
   The first A probe lacked HTML Accept and triggered successful private-service
   fallback; corrected the probe, not the application, and completed both switches.
9. **Reference and connector checks.** Access policy flags are verified. Separate
   A/B administrator references were encrypted, published and independently
   downloaded/decrypted successfully. A temporary 404-only connector check reached
   readiness with four edge connections, then stopped. No application DNS route,
   operator activation or invitation has occurred.

### Verification results and practical limits

| Area | Recorded result | What it does not establish |
| --- | --- | --- |
| Synthetic portfolios | Each: 14 properties, 15 spaces, 20 providers, 9 leases, 12 tenants, 40 expenses, 6 communications, 4 maintenance issues, 6 quotes, 3 appointments, 9 funded deposits and 1 follow-up task; identity/ownership/financial scenarios passed | Operator testing with real customer data; all application workflows under load |
| Fresh A recovery | 422727-byte encrypted archive; independent R2 restore; 105 tables / 1432 retained rows and 737 shared audit events unchanged; full financial/domain verifier passed | Fresh dataset has no managed files; it adds no populated file-byte proof |
| Fresh B recovery | 421320-byte encrypted archive; operator completed strict B-only comparison and independent R2 restore; agent read retained scenario report and verified ledger metadata | Agent did not re-enter the passphrase or repeat the remote download during its follow-up check |
| Evidence bytes | Earlier scratch restore matched both files, 51 MiB total | Its repetitive content compressed to a 120115-byte encrypted archive; this was not a 51 MiB R2 transfer benchmark |
| Physical host pressure | Disposable outer disk at 8% available rejected writes (503), retained reads/logout, no partial Task/receipt; after filler removal create/replay/receipt passed with one Task; all test mounts detached | VM root was never filled; synthetic identity/in-process HTTP, no public-client proof |
| Physical quota | Real kernel-backed 250 MiB ext4, SQLite FULL/rollback, reserved recovery space, upload admission/staging and remount checks passed within the documented scratch/A/B scopes | Host-filesystem-full injection or every upload endpoint under every fault |
| Boot | Both the original-service volume reboot and subsequent hosted-unit reboot passed; hosted units auto-started with unchanged bindings and inactive/unbound authorization | No previously active real-user session existed; actual enrolled-session restart/expiry acceptance remains pending |
| Private hosted boundary | Sign-in HTML 200/no-store; missing identity APIs 401/no-store; wrong/cross Host and foreign Origin 403; protected HTML 303; loopback-only, zero restarts at checks | Real Cloudflare JWT/PIN enrollment, active-user sessions, mobile/four-browser isolation, public cache behavior or latency |
| Fallback | A returned to its original private service after a failed probe; B remained untouched; corrected retry succeeded | Arbitrary business-data rollback/reset or lost-host recovery with active enrollments |
| Scratch lifecycle faults | Real installed app/SQLite/RSA: disable, expired session/demo, prior-cookie restart denial, restore-marker fence, failed invalid-archive reset passed | In-process HTTP; key transport/clock injected; not a real Cloudflare outage or all reset/publication failures |
| Access | Operator inspected exact host/email/PIN/duration settings; exact A/B DNS created; unauthenticated browser probes to shell/API/receipt paths returned 302 to the matching team login with no-store | Real allowed/disallowed email PIN and authenticated identity/isolation tests pending |
| Recovery failure/retention | Actual scratch R2 put/full-read/list/delete, seven retained points, typed failure preservation and repair passed; A/B ledger hashes unchanged | Simulated dates and injected checksum/ledger/delete failures; no real provider outage or elapsed seven-day operation |
| Reference custody | Current A/B references each 915 bytes; encrypted R2 publication, full read-back, independent download/decryption and exact deployment/fresh-enrollment checks passed | Pre-enrollment references need refreshing after identity/config changes; this is not complete lost-host re-provisioning |

The complete archive hashes and observations are in the evidence files. Retained
row comparisons include stable IDs and relationships. The audit comparison permits
only the exact post-snapshot backup/retention pair and destination restore event;
shared history must match unchanged. Historical success and backup-age snapshots
are not proof that today's daily backup has run or R2 remains reachable.

### Failure corrections to review

| Failure / mismatch | Diagnosis and correction | Protection retained |
| --- | --- | --- |
| Restore rejected live destination | Used a separate bootstrap locator for an external restore destination | No overwrite of live workspace |
| B could not create restore lock | Used owning account's private TMPDIR | No shared-lock permission broadening |
| Loop image lost allocation | Disabled discard/deferred initialization; checked allocation after format/mount; corrected only explicitly disposable scratch image where needed | Root-owned fixed image, reserved recovery capacity |
| Large upload exhausted staging | Corrected spool replay cleanup and bounded FULL error handling; focused regressions and actual scratch retry proof | Existing 50 MiB file ceiling and whole-volume quota |
| New interpreter inaccessible | Corrected read/execute modes only in new code environment | Data and credential privacy unchanged |
| Domain stayed pending | Account connection had not replaced registrar delegation; operator saved exact assigned nameservers | No VM-IP exposure or premature application route |
| Old archive rejected current schema | Confirmed old audit constraints; chose fresh current-format portfolios | Strict schema/audit validation, no migration workaround |
| Fresh recovery comparison rejected valid audit delta | Required both correlated backup creation and retention evaluation with exact expected snapshots | No blanket audit exclusion; all shared rows/history still match |
| First hosted sign-in probe returned 404 | Added `Accept: text/html` to diagnostic request; exercised fallback then retried | Content negotiation, auth and host/origin restrictions unchanged |

### Safe human inspection

These commands inspect the current state; they do not deploy, restore, restart or
activate anything. Run the SSH command on the **Mac**, using its authenticated
Google account:

```bash
gcloud compute ssh epm-demo \
  --project=project-47b72bb7-ba90-42c9-910 \
  --zone=us-west1-b \
  --tunnel-through-iap
```

Then run inside the **VM**:

```bash
sudo systemctl is-active epm-hosted@a.service epm-hosted@b.service
sudo systemctl is-enabled epm@a.service epm@b.service
sudo systemctl show epm-cloudflared.service -p ActiveState -p UnitFileState
sudo findmnt --mountpoint /var/lib/epm-a/volume
sudo findmnt --mountpoint /var/lib/epm-b/volume
sudo stat -c '%s %b %a %U %n' /var/lib/epm-volumes/epm-a.ext4
sudo stat -c '%s %b %a %U %n' /var/lib/epm-volumes/epm-b.ext4
```

Expected recorded states: hosted units active; old units masked (that command may
exit nonzero because masked is intentionally not enabled); tunnel inactive/disabled;
both ext4 mounts with the required restrictions; each image 262144000 bytes,
512008 allocated 512-byte blocks, mode 600/root. Loop device numbers and PIDs can
change on reboot and are not identity checks by themselves.

For A's current workspace/schema binding and local recovery ledger:

```bash
sudo -u epm-a env TMPDIR=/var/lib/epm-a/volume/tmp \
  /opt/epm/releases/qual-c8aab474/venv/bin/python -m app \
  --config /var/lib/epm-a/hosted-local.json \
  validate-hosted-config /etc/epm/hosted-a.json

sudo /opt/epm/releases/qual-c8aab474/venv/bin/python -m app \
  --config /var/lib/epm-a/hosted-local.json \
  hosted-recovery-status /etc/epm/recovery-a.json
```

Repeat with B's paths/account for B. Recovery status reads the local ledger only;
it neither decrypts the archive nor contacts R2. The configuration check may reject
an expired trial; do not extend dates or bypass validation merely to make it pass.

For the private unauthenticated A boundary:

```bash
curl --max-time 5 -sS -D - -o /dev/null \
  -H 'Host: demo-a.epmdemo.xyz' -H 'Accept: text/html' \
  http://127.0.0.1:8001/sign-in

curl --max-time 5 -sS -D - -o /dev/null \
  -H 'Host: demo-a.epmdemo.xyz' -H 'Accept: application/json' \
  http://127.0.0.1:8001/api/properties
```

Expected 200/no-store for sign-in and 401/no-store for unauthenticated business
reads. Use B's hostname and port 8002 for B. These local probes do not authenticate
an operator or verify public Cloudflare behavior. Never print credentials,
certificate contents, passphrases, decrypted references or session tokens for review.

### Evidence and detailed reading order

1. [Google Cloud initial provisioning](../../deployment/GOOGLE_CLOUD_DEMO_DEPLOYMENT.md) — VM,
   account, firewall, IAP, initial installation and restore corrections.
2. [Linux quota](../../qualification/reports/HOSTED_DEMO_LINUX_QUOTA_2026-10-23.md),
   [systemd/upload](../../qualification/reports/HOSTED_DEMO_SYSTEMD_UPLOAD_2026-10-23.md),
   [scratch R2 recovery](../../qualification/reports/HOSTED_DEMO_RECOVERY_2026-10-23.md) and
   [installed release/boot](../../qualification/reports/HOSTED_DEMO_INSTALLED_RELEASE_2026-10-23.md) — original
   qualification scope, failures, runtime/build hashes and physical evidence.
3. [Fresh A recovery](../../evidence/HOSTED_DEMO_FRESH_A_RECOVERY_2026-10-24.json),
   [fresh B recovery](../../evidence/HOSTED_DEMO_FRESH_B_RECOVERY_2026-10-24.json),
   [A/B boot](../../evidence/HOSTED_DEMO_AB_BOOT_2026-10-24.json) and
   [private hosted switch](../../evidence/HOSTED_DEMO_PRIVATE_SWITCH_2026-10-24.json) —
   latest deployed evidence. Each file describes its limits and its observation date.
4. [Operating runbook](../../operations/HOSTED_DEMO_OPERATIONS.md) and
   [configuration/enrollment contract](../../deployment/HOSTED_DEMO_CONFIGURATION.md) — ongoing
   manual backup, disablement, recovery and administrator actions. Examples are
   operational procedures, not evidence that every listed action has occurred.
5. [Public-access plan](../../qualification/HOSTED_DEMO_PUBLIC_ACCESS_PLAN.md) — current checkpoint,
   remaining acceptance gates and stop-at-usage rule. Older checkpoint paragraphs
   describe historical states; the newest checkpoint and this review guide identify
   the latest recorded state.
6. The [October 23](#october-23-2026) and [October 24](#october-24-2026) entries below
   — full chronological handoffs, approvals, paths, checksums and corrections.

### Remaining work before public completion

Operator-reported Billing update: trial ends **January 22, 2027**; **$30 monthly
budget alerts configured**. Review funding by January 15; no reminder automation
was created. Credit balance/provider billing were not independently audited.

- Retain the verified reference passphrases independently and refresh encrypted
  references after approved subject enrollment or configuration changes.
- Complete the remaining Slice 7 fault/reset/maintenance evidence and later
  real-enrolled-session persistence checks, retaining truthful limits for faults
  not physically injected. Hosted-unit boot persistence with inactive authority passed. Do not
  fill the production VM host filesystem to simulate host-full.
- Qualify protected application routing and fail-closed public outage behavior;
  the 404-only connector connectivity check passed, but it did not forward to A/B
  or exercise a public application outage.
- Test real email PINs/verified-subject approval, A/B and uninvited-user isolation,
  session/CSRF/logout/expiry, mobile/four-browser use, private caching and measured
  public latency. No operator is activated yet.
- Confirm operational passphrase custody, daily backup/alert responsibility,
  actual billing/trial dates and intended demo enablement/expiry before invitations.

The administrator-reference wizard is complete; do not rerun it merely to review
the result. See [reference evidence](../../evidence/HOSTED_DEMO_REFERENCE_RECOVERY_2026-10-24.json)
and [connector evidence](../../evidence/HOSTED_DEMO_TUNNEL_CONNECTIVITY_2026-10-24.json).
The separately approved hosted-unit reboot check is complete; see
[hosted boot evidence](../../evidence/HOSTED_DEMO_HOSTED_BOOT_2026-10-24.json). Remaining
fault/reset and real-provider/client acceptance gates still precede public completion.
No setup operation was performed merely to write the original review guide.

## October 23, 2026

This entry records setup and execution on October 23, rather than a claim that
public hosting is complete. The recovery reports use October 24 UTC, corresponding
to October 23 PDT.

### Account and R2 setup

The operator completed the Cloudflare dashboard steps and reported the bucket and
S3 credentials saved. The agent did not operate the dashboard or independently
inspect its settings. The walkthrough was:

1. Sign in to Cloudflare and open **Storage & databases → R2 → Overview**.
   Complete R2 activation/checkout if prompted. No paid website plan or domain is
   needed for private R2 backups. The account's exact billing/payment selections
   were not recorded or independently verified.
2. Create bucket **`epm-private-recovery`**, using **Standard** storage and
   automatic/default location/jurisdiction. Keep public `r2.dev` access disabled
   and do not attach a public custom domain. These were the instructed settings;
   authenticated S3 success alone does not independently verify public-access or
   dashboard location settings.
3. In **R2 Overview → Account Details → API Tokens → Manage**, create an R2
   **Account API token**; a User API token was an acceptable fallback if that was
   the available UI. The actual chosen token type was not independently recorded.
4. Use the suggested name **`epm-demo-backup`**, choose **Object Read & Write**,
   and restrict it to **`epm-private-recovery`**. Do not choose Admin permissions
   or all buckets. The name and scope were instructed, not inspected afterward.
5. Save the **S3 Access Key ID**, **Secret Access Key**, and **S3 endpoint** in the
   operator's password manager. Use those S3 values, not the general Cloudflare
   API-token value. The operator confirmed they were saved; nothing was pasted
   into chat.

The adapter currently accepts the standard endpoint shape
`https://<32-lowercase-hex-account-id>.r2.cloudflarestorage.com`. Jurisdictional
endpoint variants were not configured or qualified. The account identifier and
actual endpoint are intentionally not repeated here.

### Private VM credential handoff

The operator ran this already-installed, credential-free interactive wizard in
the Google Cloud VM terminal:

```bash
sudo bash /opt/epm/qualification/quota-39fcc45c/setup-r2-scratch.sh
```

It collected the saved endpoint and S3 keys, with hidden entry for both key fields,
and created a separate scratch configuration. It made no R2 network calls itself.
The wizard refuses to overwrite an existing configuration; do not rerun it as a
rotation procedure.

| Resource | Verified state |
| --- | --- |
| `/etc/epm/recovery-scratch.json` | Root-owned, mode `0600`; real application loader passed |
| `/var/lib/epm-recovery/scratch` | Root-owned, mode `0700`; verification ledger location |
| `/var/lib/epm-recovery/scratch/staging` | Root-owned, mode `0700`; external administrator staging |
| Workspace binding | `1eb0d18b-f130-45a0-a043-1cd3d27979cf`, synthetic scratch only |
| Deployment prefix ID | `44fb3d77-0ae8-4fab-a815-a8f528aa3c56` |

Temporary credential capture was confined to a private root-owned `/run` folder
with exit cleanup. Keys were not placed in command arguments, the service
environment, Git, workspace archives, or A/B settings. The saved configuration
holds the real credentials and must remain private. Do not print or copy it into
support messages.

### Authorized R2 operations and results

After local validation, the operator explicitly approved isolated S3 dependencies
and the synthetic backup/upload/read-back/restore drill. The existing release
environment initially lacked boto3. Dependencies were installed separately under
`/opt/epm/qualification/quota-39fcc45c/s3-deps`; boto3 and botocore were both
`1.43.118`. A subsequent isolated installed release also includes its S3 dependency.
A/B's existing `demo-001` environment was not changed.

The [complete recovery report](../../evidence/HOSTED_DEMO_RECOVERY_2026-10-23.json) records
the exact object keys, sizes, checksums, timestamps and results:

| Operation | Result |
| --- | --- |
| Create synthetic encrypted business backup | Production encryption, stopped-writer lock and full archive validation passed |
| Upload archive to R2 | Passed under the isolated `epm/<deployment>/<workspace>/<UTC-day>/` prefix |
| Full archive read-back | Entire length and SHA-256 matched; verification ledger saved |
| Independent archive download and restore | Passed complete retained-data validation; all 42 original rows across 105 tables survived unchanged |
| Restored file comparison | Both original files, 51 MiB total, matched their original hashes |
| Export encrypted administrator reference bundle | Passed as the owning `epm-scratch` account |
| Upload/read back/download/decrypt reference | Passed under the same isolated prefix's `references/` folder |
| Remote deletion/pruning | **No objects deleted**; the archive ledger began empty |

The encrypted archive is **120,115 bytes**: the synthetic 51 MiB attachment content
is highly repetitive and compresses well. The encrypted reference is **1,008
bytes**. Two encrypted synthetic objects were retained in R2; exact paths are in
the report. Reference objects have separate manual retention and are not counted
as business recovery points by the archive ledger.

The first reference export was invoked as root and correctly rejected because
the administrative database belongs to `epm-scratch`. Retrying export as its owner
passed; only the encrypted output was then handled by the root publisher. No
ownership check was weakened. The bundle preserves identity references, requires
fresh enrollment, and excludes usable sessions, leases and provider credentials.

Publication reported `needsAttention=false` and `retentionPending=false`. A later
local status check after the approved VM reboot still reported both false, with
snapshot age **916 seconds**. These are historical observations, not a continuing
monitor or proof of current remote availability.

To inspect the local verification ledger without contacting R2 or printing keys:

```bash
sudo /opt/epm/releases/qual-c8aab474/venv/bin/python -m app \
  --config /var/lib/epm-scratch/config.json \
  hosted-recovery-status /etc/epm/recovery-scratch.json
```

### Related VM work and retained artifacts

[Recovery qualification](../../qualification/reports/HOSTED_DEMO_RECOVERY_2026-10-23.md) also records restore
onto a new bounded image, unchanged file bytes and database rows, clean remount,
and fresh inactive administration. [Installed release and boot qualification](../../qualification/reports/HOSTED_DEMO_INSTALLED_RELEASE_2026-10-23.md)
records the combined wheel/service checks and the separately approved VM reboot.
A/B returned healthy with their original commands, configurations and workspace
IDs; bounded property reads returned 200. The original scratch volume now mounts
persistently, with its application stopped; the recovery image remains detached.
These VM actions did not configure Cloudflare public hosting.

Private local archives, downloads, decrypted reference JSON, reports and generated
synthetic test passphrases remain under the protected scratch paths documented in
those records. The test passphrases remain root-only on the VM; this is not a
production off-host passphrase-custody or complete lost-host recovery procedure.
No encrypted archive, plaintext reference or credential file was copied into Git.

### Cloudflare work not performed on October 23

- No domain registration or transfer; the operator confirmed they do not yet own
  a domain for this deployment.
- No DNS changes, named tunnel, `cloudflared` deployment or public application
  route was created.
- No Cloudflare Access application/policy, audience, real identity/PIN enrollment,
  or operator invitation was configured.
- No Cloudflare cache rules, compression or real-client latency were qualified.
- No A/B recovery configuration or hosted release switch was performed.
- Multi-day retention, credential rotation/revocation, remote failures and actual
  lost-host recovery were not physically exercised by this successful first-point
  drill. The fixture also does not independently qualify populated financial totals.

Continue from the [public-access checkpoint](../../qualification/HOSTED_DEMO_PUBLIC_ACCESS_PLAN.md).
Remaining deployment/fault gates and actual domain/identity inputs still precede
public routing and invitations.

## October 24, 2026

Continuation of the October 23 entry and
[public-access checkpoint](../../qualification/HOSTED_DEMO_PUBLIC_ACCESS_PLAN.md). This records observed
state separately from planned or operator-reported configuration. No credentials
or operator email addresses are stored here.

### Domain and public DNS observations

The operator supplied `http://epmdemo.xyz/`. The accepted hostnames become
`https://demo-a.epmdemo.xyz` and `https://demo-b.epmdemo.xyz`. They are planned
origins; no application was published at either hostname during these checks.

Initial recursive DNS queries returned:

| Query | Observed answer |
| --- | --- |
| NS `epmdemo.xyz` | `maceio.ns.porkbun.com`, `salvador.ns.porkbun.com`, `curitiba.ns.porkbun.com`, `fortaleza.ns.porkbun.com` |
| A `epmdemo.xyz` | `207.207.210.229`, `207.207.210.107` |
| CNAME `demo-a.epmdemo.xyz` | `pixie.porkbun.com` |
| CNAME `demo-b.epmdemo.xyz` | `pixie.porkbun.com` |
| MX, TXT, DS and CAA at the apex | No answers returned by these initial queries |

These are public DNS observations, not an exhaustive DNS export or proof that no
other records/services exist. Review the registrar's complete DNS records before
switching delegation. Parking responses do not identify an EPM application or
tunnel. The apex website could not be inspected through the web tool.

### Manual setup boundary

Local browser control is disabled in this session. No Cloudflare account-management
connector is available; the existing R2 S3 keys are not account/DNS credentials.
No attempt was made to reuse them for zone or Access administration.

The proposed wizard stages are:

1. Add `epmdemo.xyz` to the existing Cloudflare account and select Free.
2. Review/import the existing DNS records and capture the exact assigned Cloudflare
   nameservers. Save only those public nameserver values in a local scratch file.
3. Update the nameserver delegation at Porkbun after reviewing the DNS records.
4. Verify public delegation and Cloudflare's Active status. Do not add application
   routes or point records to the VM's public IP during this stage.

The operator confirmed this sequence and supplied distinct A/B Gmail sign-in
addresses. Actual addresses are saved mode `0600` outside Git in
`/Users/dcai/Desktop/Property-Management-Data/hosted-demo-epmdemo.inputs.json`,
alongside exact origins/workspace UUIDs. This input record is not a usable deployment
configuration: issuer, audiences, administrative contact and activation dates remain
to be resolved. Addresses are not repeated in repository documentation.

The ephemeral four-stage script is prepared at
`/private/tmp/epm-domain-20261024.IIuBS1/setup-domain.sh`. Its library matches the
wizard template unchanged. Bash syntax and isolated nameserver-format checks pass;
ShellCheck is unavailable locally. It saves only the assigned public nameservers
to a sibling private `nameservers.env`, with no password or token capture. It has
not been run end-to-end by the agent; the operator must run it interactively.
Pending propagation exits with status 2 rather than claiming activation.
No registrar, DNS, Access or tunnel change is yet claimed.

Primary instructions checked today:

- [Cloudflare primary DNS setup](https://developers.cloudflare.com/dns/zone-setups/full-setup/setup/).
- [Porkbun nameserver editing](https://kb.porkbun.com/article/22-how-to-change-nameservers).
- [Cloudflare DNSSEC onboarding](https://developers.cloudflare.com/dns/dnssec/).

### VM verification

Both private A/B services were active. The original scratch volume remains mounted
with `rw,nosuid,nodev,noexec`; its protected recovery configuration is present.
The host reports approximately 23 GiB free and 20% disk use. `cloudflared` was not
found on the executable path. No application or host configuration was changed.

The installed-release, quota and R2 evidence from October 23 remains scoped to its
documented drills. Real Access/PIN, A/B hosted deployment, remaining fault checks
and public-browser acceptance remain pending.

### Operator handoff

The prepared wizard was handed off with this command, to run in the **Mac
terminal, not the VM terminal**:

```bash
bash /private/tmp/epm-domain-20261024.IIuBS1/setup-domain.sh
```

The operator was instructed to choose the Free plan and return the two assigned
Cloudflare nameservers plus the dashboard status (**Active** or **Pending**).
Passwords, API tokens and email PINs are not needed in chat.

At this append, no wizard execution result, assigned nameservers or activation
confirmation has been reported. The handoff is complete; dashboard changes and
DNS propagation remain unverified. The next step is operator execution followed
by independent DNS verification. No new Cloudflare or VM operation was performed
while appending this record.

### Nameserver change and activation — approximately 11:07 PDT

The operator began the wizard and supplied dashboard screenshots. Porkbun first
showed its Cloudflare account connection, but the operator confirmed that all
four registrar nameservers were still Porkbun's. Account connection alone had
not changed delegation. Cloudflare showed the zone pending with these assigned
nameservers:

- `bonnie.ns.cloudflare.com`
- `vasilii.ns.cloudflare.com`

The operator reported removing the four Porkbun nameservers, entering the two
assigned Cloudflare nameservers and saving the change. A subsequent screenshot
showed Cloudflare checking propagation. At approximately 11:07 PDT, the operator's
Domains screenshot showed **epmdemo.xyz — Active — Free**. This confirms dashboard
activation from supplied screenshot evidence; an independent public DNS query
was attempted earlier but interrupted without a result and is not claimed here.
The wizard's final exit status has not been reported.

The preceding DNS screenshot showed two apex A records (`207.207.210.107` and
`207.207.210.229`) and wildcard/www CNAMEs pointing to `pixie.porkbun.com`, all
proxied. These imported parking records do not publish the EPM applications.
The dashboard's missing mail-record warning does not block Gmail-based operator
sign-in. Access configuration, tunnel deployment, A/B service changes and public
application acceptance remain pending.

### Access setup handoff — October 24 continuation

Following dashboard-confirmed domain activation, the operator requested continued
setup. Current Cloudflare primary instructions were checked for organization
onboarding, PIN identity providers, self-hosted applications and audience tags.
New organizations default to Cloudflare-account login; One-time PIN must be added
explicitly and selected for these two applications.

A four-stage Mac wizard is prepared at
`/private/tmp/epm-access-20261024.xg40kkxf/setup-access.sh`:

1. Create/reuse the existing account's Zero Trust organization on Free and capture
   the actual team domain/issuer.
2. Add/reuse One-time PIN under Integrations → Identity providers.
3. Create/configure EPM Demo A for exactly `demo-a.epmdemo.xyz`, with one Allow
   policy for the previously supplied A email, PIN-only login and eight-hour session.
4. Repeat for EPM Demo B at exactly `demo-b.epmdemo.xyz`, restricted to B's email.

Each app's AUD is copied from Configure → Additional settings. The wizard saves
only team domain/issuer, an operator-confirmed PIN setup flag and the distinct
64-character AUD identifiers to a private sibling `access.env`; it does not
capture passwords, login assertions or PINs. Email bindings are read from the
previously authorized private input record when preparing the ephemeral script.
No actual emails are recorded in this log.

The wizard library is unchanged, macOS Bash-compatible syntax validation passed,
and invalid AUD formats are rejected. ShellCheck remains unavailable. The wizard
has not been executed by the agent; dashboard settings remain pending operator
execution and later verification. No tunnel, DNS route, VM service or invitation
was changed by this preparation. Usage check: 92% five-hour and 54% weekly remaining.

Sources checked:

- [Zero Trust onboarding](https://developers.cloudflare.com/cloudflare-one/setup/).
- [One-time PIN setup](https://developers.cloudflare.com/cloudflare-one/integrations/identity-providers/one-time-pin/).
- [Self-hosted Access applications](https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/self-hosted-public-app/).
- [Application audience identifiers](https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/authorization-cookie/validating-json/).

### Access inputs saved and Mac tunnel authorization prepared

The operator reported **Access setup saved**. The local `access.env` is a regular
mode-0600 file containing `epmdemo.cloudflareaccess.com`, its exact HTTPS issuer,
the PIN-setup confirmation and two distinct correctly formatted AUD identifiers.
These values were validated without executing the env file and copied into the
existing mode-0600 private deployment input JSON outside Git. Actual email policy
contents, eight-hour sessions and PIN-only selection remain operator-reported;
no real sign-in or independent account API inspection has occurred.

Installed `cloudflared` **2026.10.3** on the administrator Mac via Homebrew after
command approval. Homebrew also auto-updated its taps; no unrelated installed
packages were upgraded by this command. No background service was started.

The next manual browser handoff is the single-stage wizard
`/private/tmp/epm-tunnel-login-20261024.bhqx1hym/authorize-tunnel.sh`.
It runs `cloudflared tunnel login`, asks the operator to select `epmdemo.xyz` and
authorize, checks that the resulting default Mac `~/.cloudflared/cert.pem` is
nonempty, and restricts directory/file modes to 0700/0600. Existing certificates
are not overwritten and require explicit operator confirmation of the account;
symlink paths are refused. Wizard library unchanged; Bash syntax check passed.
Execution is pending. The certificate must stay on the Mac and must not be pasted
into chat or transferred to the VM. This step creates no tunnel, DNS route or
application process. The agent has not read a certificate or tunnel secret.

Cloudflare's [locally managed tunnel instructions](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/local-management/create-local-tunnel/)
were checked. Next: complete Mac browser authorization, then create/reuse the
named tunnel and prepare its restricted VM credential/configuration. A/B service
switches, public routing, enrollment and remaining acceptance gates are pending.
Latest usage: 88% five-hour and 53% weekly remaining.

### Mac authorization and stopped VM tunnel service prepared

The operator reported **Tunnel authorization saved**. Metadata-only checks found
a nonempty regular Mac account certificate with mode 0600 under a mode-0700
`.cloudflared` directory. The certificate contents were not read or transferred.
An authenticated tunnel list returned no tunnels. Created locally managed tunnel
**epm-demo**, UUID `c29cb930-4166-4105-90a3-32d72fc04f46`. Its Mac credential was
created mode 0400; only this tunnel-scoped JSON was transferred privately over IAP.
No DNS routes were created and no tunnel connection was started.

The official GitHub release metadata supplied the Linux amd64 2026.10.3 binary
SHA-256 `053b80b0a23031a038fdbf3c073f59f82b8f1f152aa67971d7383ffafc0dbab0`.
The VM download matched it and the pinned runtime is installed at
`/usr/local/lib/epm-cloudflared/2026.10.3/cloudflared` (root-owned executable).
Created dedicated system account/group `epm-tunnel`, non-login with no home.

Prepared root-owned `/etc/epm-tunnel` mode 0750, with configuration and credential
mode 0640, group `epm-tunnel`. Neither `epm-a` nor `epm-b` can read the credential.
The temporary credential upload copy was removed after protected installation.
The administrator supplied a support contact, saved only in private inputs.

Installed `/etc/systemd/system/epm-cloudflared.service`, running the pinned binary
as `epm-tunnel` with explicit config/credential paths, no account certificate,
no auto-update, restricted filesystem/privileges, loopback-only metrics and
128 MiB high / 256 MiB maximum memory. Its only ingress rule returns HTTP 404.
Config validation passed; a rule check for `https://demo-a.epmdemo.xyz` matched
that 404 fallback. `systemd-analyze verify` passed. After daemon-reload the unit
is **inactive and disabled**; actual connected-service behavior and these resource
limits are not yet qualified. A/B remained active on their original services.

Both credential and account certificate remain outside Git. No tunnel secret was
printed. Tunnel metadata is retained in the durable private input JSON. The next
step is preparing the A/B backup/maintenance transition and completing deployment
gates before adding real ingress rules or DNS routes. Latest usage check: 83%
five-hour and 52% weekly remaining.

### Next operator handoff: pre-switch A/B backups

Read-only inspection confirmed original A/B commands still use `demo-001`, each
with its private `/var/lib/epm-<instance>/tmp`, private owning-user backup directory
and loopback listener (8001/8002). Prepared the next VM wizard at
`/home/dcai/epm-backup-before-hosted.sh` (local source:
`/private/tmp/epm-tunnel-vm-20261024/backup-before-hosted.sh`). Library unchanged;
Bash syntax check passed. The script has not been executed.

The operator saves backup passphrases independently in their password manager,
then explicitly confirms sequential maintenance. For each instance, the script
stops only its original service, exports a fresh timestamped encrypted archive
under `/var/backups/epm-<instance>/pre-hosted-<UTC-timestamp>.epm-backup`, runs
independent archive validation with a second private passphrase prompt, and
restarts/checks that original service before proceeding. An EXIT trap attempts
to restart a service left stopped after a failure/interruption and reports if
restart fails. No passphrase is captured by the wizard or stored in commands.
This creates local recovery points only; R2 publication and hosted switching are
not included. No A/B interruption has yet occurred during this preparation.

### Backup wizard path correction

The operator's VM login is `dctech92130` with home `/home/dctech92130`, whereas
IAP automation uploaded the wizard under `/home/dcai`. The initial `~/` handoff
therefore failed with No such file or directory before any script execution.
Installed a credential-free copy at the stable administrator path
`/opt/epm/admin/backup-before-hosted.sh`, root-owned mode 0755. Bash syntax/read
validation passed as `dctech92130`. Correct invocation from either VM login:
`bash /opt/epm/admin/backup-before-hosted.sh`. No backup or service interruption
was performed while correcting the path. The older upload copy is not the
canonical handoff path.

### A/B backups reported complete; new candidate volumes/configurations prepared

The operator reported **A/B backups saved**. Both original services were verified
active afterward. New account-owned mode-0600 archive metadata/checksums:

| Instance | Archive under its private backup directory | Bytes | SHA-256 |
| --- | --- | --- | --- |
| A | `/var/backups/epm-a/pre-hosted-20261024T184804Z.epm-backup` | 422178 | `2d783a2b12e1d65e605d5dd60722331175bf95ff79afb0e22ea7883515228071` |
| B | `/var/backups/epm-b/pre-hosted-20261024T184851Z.epm-backup` | 419517 | `dbe108632cc898062a48cc24fb54ee04bbd12a31307af253a146d4d2bf58ab83` |

The completed wizard includes independent archive validation; its success is
operator-reported. The agent verified metadata/hashes, without passphrases or
independent decryption. Existing locators still select the original local-storage
workspaces; measured file sizes were approximately 3.7 MB each.

Prepared new images only, preserving old workspaces and services:

- `/var/lib/epm-volumes/epm-a.ext4`, mounted as `/dev/loop5` at
  `/var/lib/epm-a/volume`.
- `/var/lib/epm-volumes/epm-b.ext4`, mounted as `/dev/loop6` at
  `/var/lib/epm-b/volume`.

Both images are root-owned 0600, exactly 262144000 bytes with 512008 allocated
512-byte blocks after format and first mount. Formatting used the qualified
`-m 10 -E nodiscard,lazy_itable_init=0,lazy_journal_init=0` recipe under a serialized
provisioning lock. Mounts are complete ext4 with `rw,nosuid,nodev,noexec`; mounted
roots and tmp directories are private to their service accounts. Separate access
and backup-staging directories were prepared. **No fstab change or reboot was
performed**; these new mounts are not yet persistent or boot-qualified.

Created root-protected `/etc/epm/hosted-a.json` and `hosted-b.json` with supplied
origins, actual issuer/AUD/email bindings, contact, distinct operator UUIDs and
external administrative database paths. The draft fourteen-day window is
2026-10-24T18:51:09Z through 2026-11-07T18:51:09Z; review before activation so it
matches the intended enabled period. New `hosted-local.json` locators select the
candidate volume workspaces; original `config.json` files remain unchanged.

Created root-only `/etc/epm/recovery-a.json` and `recovery-b.json`, each with a new
deployment UUID, pinned business UUID and independent root-private ledger/staging
under `/var/lib/epm-recovery/a` or `b`. They reuse the previously saved bucket-scoped
R2 credential privately on the VM. Neither credentials nor actual operator/contact
emails were printed or written to Git. Real deployment/recovery loaders passed
for both instances. No R2 operation was executed during this preparation.

Next operator handoff, in the VM terminal:
`bash /opt/epm/admin/restore-publish-before-hosted.sh`.
This root-owned mode-0755 wizard passed Bash syntax checks as `dctech92130` and
retains the unchanged wizard library. After confirmation, for A then B it restores
the exact archive into the new empty volume workspace, validates identity and
physical quota, initializes fresh inactive administration, and separately confirms
private R2 upload/full read-back and ledger creation. Passphrases are entered only
through application prompts. Execution/results remain pending. Original writers
stay running; the operator was asked to keep their data unchanged until switching.
No public route, enrollment approval or service switch occurs in this wizard.
Latest usage: 68% five-hour and 50% weekly remaining.

### Restore blocked by old-format audit schema — awaiting data decision

The operator ran Stage 1 of the restore/R2 wizard. The qualified current release
rejected A's extracted archive with `audit_events has incompatible constraints`
before publishing the new workspace. The archive had been created and validated
by the old `demo-001` release, whose schema differs from the hosted release.
The agent should have checked this compatibility before handing off restoration.
No schema validator or constraint was weakened.

Read-only live database inspection confirmed both A and B have the old actor-kind
CHECK permitting `local_operator`, `system`, `connector` and `ai_assistant` only.
The hosted release requires `hosted_operator` as well as its non-null UUID-length
actor-reference constraint. This is a real format mismatch, not a bad passphrase
or failed Cloudflare/R2 connection. Other schema differences have not yet been
exhaustively compared; the audit mismatch is the first confirmed blocker.

Post-failure checks: both original services active; A's volume contains only
`tmp` and `lost+found`, with no workspace or restoring directory; no candidate A
administrative database or R2 ledger exists. Stages 2–4 were not reached. Existing
archives and original workspaces remain intact. Do not rerun the restore wizard
against these old archives until the data strategy is resolved.

Asked the operator to choose fresh current-format synthetic demo data (recommended,
retaining old workspaces/backups unchanged) or explicitly authorize a one-time
record-preserving conversion as an exception to AGENTS.md's greenfield rule:
“Keep only the latest format and schema” and “Do not add migration effort or
migration compatibility work.” No conversion, reseeding or production source
change has been performed. Latest usage check: 56% five-hour / 48% weekly remaining.

### Greenfield decision: fresh portfolios generated and verified

The operator selected fresh current-format demo data, then clarified that this
remains a greenfield project and old data may be wiped if needed. No migration
or compatibility layer was added. Deletion was unnecessary: old workspaces,
archives and original private services are retained, while fresh portfolios were
created on the already prepared candidate volumes.

The source at current HEAD `a74f2e1d9d5fa2c543b723895be0661d079c3cc6` has no
changes to the demo generator or app package relative to qualified release source
`c8aab47415b42dba0dec3545b117143a95ce49ef`. Generator inputs:

| File | SHA-256 |
| --- | --- |
| `application/demo/seed.py` | `82c2658ee635ff6ce830dde81e5ecba258472159aa37a1616825fb35223b4701` |
| `application/demo/verify.py` | `33ddfc825bf8132ad35d76c218f286fffb73b48fc4e57a89ba335f81c6f9f360` |
| `application/demo/dataset.json` | `1b4e417698c60b36a48e5e1c5cccd1bc1c07d27de711d34de83dccfd5284a3d8` |

Installed root-owned generator inputs and a separate seeding venv under
`/opt/epm/qualification/seed-c8aab474`. Its explicit `.pth` references the pinned
qualified app package; the serving venv was not changed. Only this seeding venv
adds httpx2/httpcore2 2.13.1 and truststore 0.10.5. The first dependency smoke check
incorrectly imported `httpx` rather than this project's `httpx2`; it failed before
generation. The corrected import/client check passed, then generation completed
through the real in-process application HTTP contracts as each owning account.

| Instance | Fresh workspace ID | Candidate path |
| --- | --- | --- |
| A | `611d3445-0cce-4858-a10d-b5d5202d601a` | `/var/lib/epm-a/volume/workspace` |
| B | `facd33be-7ff7-4d91-bff1-9a3f85af658b` | `/var/lib/epm-b/volume/workspace` |

Both scenario dates are October 24 in America/Los_Angeles. Each independent
portfolio passed the generator's complete verifier: SQLite integrity/foreign
keys/current schema, exact counts, owner shares, tenant/provider identities,
expense totals and links, deposits, leases, vacancy/leasing and rent scenarios.
Each has 14 properties, 15 spaces, 20 providers, 9 executed leases, 12 tenants,
40 expenses, 6 communications, 4 maintenance issues, 6 quotes, 3 appointments,
1 condition report, 9 deposit accounts/receipts and 1 follow-up task. Both show
six vacant spaces, one late unpaid rent and the expected future prepayment.
Reports/catalogs/journals are retained account-private under the volume's
`workspace-demo-runtime` directory, included in the physical volume budget.

Updated only the candidate hosted/R2 configurations and durable private inputs
to the fresh UUIDs, retaining previous private UUIDs as metadata. Qualified-release
`validate-hosted-config` passed for each candidate; initialized separate inactive
administrative stores with no approved subject. Real physical storage validators
passed as the owning accounts with the correct bounded TMPDIR. Both images still
have 512008 allocated 512-byte blocks and exact 250 MiB size. Original services
remain active on old locators; no public route, activation or switch occurred.

### Replacement handoff: protect fresh portfolios and prove R2 recovery

The earlier old-archive restore wizard is superseded. The new shared VM command is:
`bash /opt/epm/admin/protect-fresh-demos.sh`.
It has six stages: fresh backup, R2 publication, independent download/restore proof
for A, then the same for B. Passphrases are entered only through the application's
private prompts and must be saved independently by the administrator.

Root-owned helpers `/opt/epm/admin/download-recovery.py` and `compare-recovery.py`
perform a bounded independent GET using the verified ledger, check complete length
and SHA-256, and compare each fresh candidate with its restoration: workspace ID,
all retained rows/stable IDs/relationships and file hashes. The audit comparison
permits only the one source `backup_created` event after the archive snapshot and
the destination's one `workspace_restore`/`restored` event, while requiring shared
audit history to match exactly. The full scenario verifier is then run on the
restored workspace, including financial totals. This is a prepared drill, not a
claim it has run or passed.

Wizard library unchanged; Bash syntax checks passed and helper Python sources
compiled successfully. No repository implementation source changed. R2 operations
and recovery results await operator execution. New mounts still need persistence
and boot qualification; later service/enrollment/public-client gates remain open.
Latest usage: 29% five-hour / 44% weekly remaining, above both stop thresholds.

### Fresh A R2 restore verified; strict audit comparison corrected

The operator completed A's fresh backup/publication and independent R2 GET/restore.
Downloaded archive: 422727 bytes, SHA-256
`18bd8fdc1743456c24b7302f0d81f7d420f49c4cfea37c86bfdf60a1e974eaec`.
Restore destination is
`/var/lib/epm-a/volume/recovery-proof-20261024T190113Z/workspace`.
The helper then failed because it incorrectly expected only one source-only audit
event. Read-only comparison confirmed 737 shared events unchanged, two legitimate
source-only post-snapshot events (`backup_created` and retention `evaluated`), and
only the expected destination restore event. This was a drill-helper assumption,
not data loss or a production validation failure.

Corrected the operational helper to require exactly those two classifications,
the same correlation ID, system actor/reason, unchanged shared rows, matching
archive identifiers and exact first-point retention outcome (one considered/retained,
zero deleted). All other tables and file hashes still require exact agreement.
No production source, archive validator or schema constraint was changed.

Reused the already restored A proof: comparison passed across **105 tables and
1432 retained rows**; its full scenario verifier passed, including financial
relationships/totals, identity links, current schema, integrity and foreign keys.
There are no managed files in this fresh dataset, so this does not add a populated
file-byte drill; the prior scratch recovery separately covers those bytes.
Historical recovery status: last verified backup 2026-10-24T19:01:31.342562Z,
154 seconds old at check, `needsAttention=false`, `retentionPending=false`.
Both original private services remain active. See
[nonsecret A recovery evidence](../../evidence/HOSTED_DEMO_FRESH_A_RECOVERY_2026-10-24.json).

The B-only continuation is installed root-owned at
`/opt/epm/admin/protect-fresh-demo-b.sh`; Bash syntax checked as `dctech92130`.
Run `bash /opt/epm/admin/protect-fresh-demo-b.sh` in the VM to perform B's three
remaining stages with private passphrase entry. Do not rerun the original six-stage
wizard: A's backup, publication, independent restore and verification are complete.
The B-only wizard uses the corrected strict helper. No B result is yet claimed.
No service switch, new persistent mount entry, reboot or public route was performed.
Latest usage: 18% five-hour / 42% weekly remaining, above the saved stop thresholds.

### Fresh B recovery completed; transition candidates reviewed

The operator reported **Fresh B recovery verified**. The B-only wizard's strict
comparison precedes scenario verification and stops on error; its completion is
operator-reported. Independently read the retained restored scenario report at
`/var/lib/epm-b/volume/recovery-proof-20261024T190456Z/workspace-demo-runtime/verification.json`:
all expected counts and financial/domain scenarios passed. The local R2 ledger
contains the verified 421320-byte object with SHA-256
`46ed79dbf29d40eb52bb8d04a0c20c413c6e917b7719fd5df35ca2d46fec93e0`,
created 2026-10-24T19:05:11.337679Z, verified 19:05:26.560377Z. At check, backup age
was 79 seconds, `needsAttention=false`, `retentionPending=false`. Both original
services remain active. See [B recovery evidence](../../evidence/HOSTED_DEMO_FRESH_B_RECOVERY_2026-10-24.json).
No passphrase, new decryption or remote operation was needed for this verification.

Prepared review-only transition files under root-owned
`/opt/epm/qualification/hosted-transition-20261024`:

- `fstab.before`: SHA-256 `98c4a7d9397af04f1b3f47983f3552b00d494b0e852753099a11c9d75b45dc10`.
- `fstab.candidate`: SHA-256 `f5e7e5b14e51c6def06ffda83e6998bc65b339746bed54415892e26dbf3ed8f7`.
  Adds only A/B image mount entries with
  `loop,rw,nodev,nosuid,noexec,nofail,X-fstrim.notrim`; retains the existing scratch
  entry and all other existing entries.
- `epm-hosted@.service`: SHA-256 `77e72153a5e9f5d3f06209ee1ce8e44a2b87dc55d34282a085568dab73ebbcad`.
  Pins `qual-c8aab474` and the new `hosted-local.json` locator rather than changing
  old private `config.json`. Other template confinement/mount/resource settings
  are retained. This unit is only a candidate, not installed or started.

`systemd-analyze verify` passed. `findmnt --verify --tab-file` found zero parse
errors and zero errors, with three expected regular-file loop-source warnings
(one for each scratch/A/B image). No live fstab, service, public route or reboot
was changed. Next proposed maintenance action: install the two prepared persistent
mount entries, reboot once, verify both new images remount with full allocation,
revalidate current-schema candidates and confirm original private A/B services
return healthy. Keep hosted switching and public routing separate and closed.
Reboot approval is pending because it briefly interrupts the original private
services; the earlier scratch reboot approval was already used.

Requested explicit approval for the prepared mount installation and one reboot;
waiting for the operator response. The five-hour window reset during this turn;
latest usage is 94% five-hour / 41% weekly remaining. No usage threshold reached.

### Approved A/B persistent mounts and boot verification completed

The operator explicitly approved installing the two reviewed persistent-mount
entries and one VM reboot, with hosted switching/public routing excluded.
Before installation, the installer verified live/candidate fstab hashes, saved
`boot-before.json` under the transition directory, and captured original service
command/config/unit hashes. Atomically installed the exact reviewed candidate:
fstab SHA-256 `f5e7e5b14e51c6def06ffda83e6998bc65b339746bed54415892e26dbf3ed8f7`.
Daemon reload and fstab validation passed (zero errors; three expected regular-file
loop-source warnings). Only one reboot request was issued. An early reconnect
still saw the old boot ID; a subsequent IAP connection failed during the restart,
then connectivity returned. No second reboot or firewall change was attempted.

Post-reboot verification completed at October 24, **12:10 PDT** (19:10 UTC):

- Boot ID changed from `50210b75-684f-4cb8-99ed-00a05e59d68b` to
  `a240dc3f-7d1f-4fb4-a4b5-0966ad592726`.
- A mounted automatically as `/dev/loop3` at `/var/lib/epm-a/volume`; B as
  `/dev/loop6` at `/var/lib/epm-b/volume`, complete ext4 with
  `rw,nosuid,nodev,noexec`.
- Each image remains exactly 262144000 bytes, 512008 allocated 512-byte blocks.
  Owning-account physical storage validators and qualified-release candidate
  workspace/config/schema validation passed.
- Original private A/B services are active (PIDs 585/586). Their command, config
  and unit hashes match the pre-reboot snapshot. Both bounded private property
  reads returned HTTP 200 using the explicit local CLI header.
- The tunnel unit remains inactive. No hosted service, ingress/DNS route,
  operator activation or invitation was enabled.

Root-private `boot-before.json` and `boot-after.json` remain under
`/opt/epm/qualification/hosted-transition-20261024`; no secrets are included in the
[repository evidence copy](../../evidence/HOSTED_DEMO_AB_BOOT_2026-10-24.json).
The evidence file is saved in the working tree; it has not been committed by the
agent. The reviewed hosted unit remains a candidate only.

Next proposed transition: install the pinned hosted template and separate port
settings, then switch A followed by B while enforcing one writer, fresh inactive
authorization and loopback-only listeners. Validate public sign-in shell and
rejection of unauthenticated business/API requests before any real tunnel route.
On startup failure, stop/disable the failed hosted unit and unmask/restart the
original private service. Separate approval is required for this service switch;
the completed reboot approval did not include it. No new reboot is proposed.

Final hosted-switch review settings are prepared alongside the unit:
`hosted-a.env.candidate` contains only `EPM_PORT=8001` (SHA-256
`831e771b17a01eee2d8be7d9b58a254d9c82d4f438169d9c4222ca6b0d6ca44f`);
`hosted-b.env.candidate` contains only `EPM_PORT=8002` (SHA-256
`ebc240f460f969b34a45e5f3dcee7ce253b310d4e085b64eeb3448f97983e2a9`).
Mode 0600 review copies; actual `/etc/epm/hosted-{a,b}.env` and installed hosted
template are absent. Repeated systemd template validation passed. Approval requested
for the separate A-then-B private hosted service transition; no public routing,
operator activation, invitation or reboot is included. Latest usage: 67% five-hour /
36% weekly remaining, above both stop thresholds. `git diff --check` passed.

### Approved private hosted-service transition completed

The operator explicitly approved sequential A/B private switching, excluding
reboot, public routing, operator activation and invitations. Installed the exact
reviewed root-owned hosted template (SHA-256
`77e72153a5e9f5d3f06209ee1ce8e44a2b87dc55d34282a085568dab73ebbcad`), pinned to
`qual-c8aab474`, with root-owned service-group-readable 0640 port files
`/etc/epm/hosted-a.env` (8001) and `hosted-b.env` (8002).
The hosted template uses the new `hosted-local.json` locators. Old `config.json`
locators/data remain unchanged for private fallback; they are no longer selected
by the running hosted services. Each old instance was stopped/masked before
its hosted replacement was enabled/started, preserving one writer per workspace.

The first A attempt started normally, but the diagnostic helper omitted
`Accept: text/html` and received the correctly enforced 404 sign-in response.
After its readiness window, fallback stopped/disabled hosted A, unmasked and
restarted original private A successfully. B was untouched. Journal inspection
confirmed normal startup/clean shutdown and no restarts. Corrected only the
operational probe's Accept header and allowed safe reuse of the exact reviewed
port file (contents, owner/group/mode checked). No application source, authentication
check or route restriction was relaxed. The retry passed, then B was switched.
This physically exercised original-service fallback without public exposure.

At **12:18 PDT** (19:18 UTC):

| Instance | Hosted service | Old service | PID | Startup memory snapshot |
| --- | --- | --- | --- | --- |
| A | `epm-hosted@a.service`, active/enabled | `epm@a.service`, inactive/masked | 2404 | 196366336 bytes |
| B | `epm-hosted@b.service`, active/enabled | `epm@b.service`, inactive/masked | 2621 | 197287936 bytes |

Both use their verified fresh UUIDs and loopback-only listeners. Checks passed:
HTML sign-in 200/no-store; unauthenticated properties/session APIs 401/no-store;
wrong Host 403; protected page 303 to sign-in. Follow-up checks confirmed both
still active with zero restarts, each rejects the other instance's Host and
Origin with 403, and each administrative store remains inactive, subject-unbound,
with zero sessions and zero pending enrollments. No tokens or subjects were
captured. Tunnel remains inactive, with 404-only configuration and no DNS routes.

Root-private reports `switch-a.json`, `switch-b.json`, `switch-combined.json` remain
under the transition directory. See
[private hosted-switch evidence](../../evidence/HOSTED_DEMO_PRIVATE_SWITCH_2026-10-24.json).
Current hosted administration/backup commands must use
`/var/lib/epm-<instance>/hosted-local.json`; the old `config.json` selects the old
private portfolio. Updated configuration/operations examples accordingly.
No new reboot was performed. Enabled-unit persistence is configured but an
actual reboot of these hosted units, real Cloudflare/PIN/caching/latency/four-browser
acceptance, remaining fault/reset checks and encrypted administrator reference
custody still need completion before public invitations. This is private hosting,
not completed public access. Remaining qualification gates in the plan still apply.

Next manual handoff is a read-only Access review wizard on the Mac:
`bash /private/tmp/epm-access-review-20261024.zxnrn69c/check-access-policies.sh`.
It opens the existing account and asks the operator to inspect each exact app's
hostname, eight-hour duration, attached single-email Allow policy and PIN-only
login settings, with no One Client authentication or broad/Bypass grant. It
captures only two confirmation flags in private sibling `access-policy-review.env`,
not emails, assertions or PINs. It makes no API/DNS/service changes and stops if
any setting differs. This is needed because local browser control is disabled
and account policy contents have so far been operator-reported, not independently
inspected. The read-only settings mirror the approved setup; no new grant is
requested. Wizard library unchanged and Bash syntax validation passed. Execution
is pending; real sign-in/isolation tests remain separate acceptance gates.

### Access policies checked; administrator-reference handoff prepared

The operator reported **Access policies checked**. The private review file is a
regular mode-0600 file with exactly `DEMO_A_POLICY_CONFIRMED=yes` and
`DEMO_B_POLICY_CONFIRMED=yes`; copied only this confirmation state to the durable
private input JSON. This is operator inspection evidence, not an independent
Cloudflare API audit or real-user authentication test. Actual emails remain
outside Git. The first usage lookup failed; retry succeeded above both stop
thresholds, so preparation continued.

The next pre-routing recovery gate is separate encrypted administrator references.
Prepared and installed four-stage interactive VM wizard:
`bash /opt/epm/admin/protect-admin-references.sh`.
It exports A's current deployment/identity references with production scrypt/AES-GCM,
confirms encrypted R2 publication/full read-back/independent GET and verifies
successful decryption, then repeats for B. The operator saves a reference
passphrase of at least twelve characters in their password manager, separate
from the business-backup passphrase. Passphrases are entered only through existing
application getpass prompts; they are not arguments, environment variables or
wizard-captured data. No service interruption, activation, reboot or route change
is included.

Installed root-owned helpers:

- `/opt/epm/admin/reference-transfer.py`: bounded 64 KiB encrypted source/read-back,
  exact workspace/deployment binding, root-private copy, full checksum verification,
  separate `references/<SHA>.enc` object and independent encrypted download.
- `/opt/epm/admin/reference-validate.py`: strict production RecoveryBundle model,
  exact deployment equality, fresh-enrollment policy and currently empty subject
  references. Prints only nonsecret verification metadata.

Exports go to owning-user-private `/var/backups/epm-<instance>/admin-reference-<UTC>.enc`.
Root-private drill outputs/report are under
`/var/lib/epm-recovery/<instance>/reference-<UTC>/`; only the encrypted bundle goes
to R2. The decrypted verification file remains root-only, outside business storage
and Git. No reference objects are pruned automatically. Reference bundles exclude
usable sessions, token hashes, leases, Access tokens and provider/R2 secrets.
Because operators are not yet enrolled, these are pre-enrollment references;
refresh reference custody after approved enrollment or configuration changes.
They do not grant access when unpacked.

Wizard library unchanged; Bash syntax check passed locally and as `dctech92130`.
Both Python helpers passed Ruff check and Ruff format --check using the project
configuration, with no suppressions. ShellCheck is unavailable. Real publication
and decryption are pending operator execution. Both hosted A/B services were
reconfirmed active; tunnel inactive/disabled. Latest usage: 88% five-hour and 50%
weekly remaining. No threshold reached. Remaining private fault/persistence and
real-provider/client acceptance gates still precede public invitations.

### Documentation consolidated for human review

At the operator's request, added the front-of-document human review guide with
latest recorded topology, current/old paths and UUIDs, approval/operation sequence,
verification results and limits, failure corrections, safe read-only inspection
commands, evidence reading order and explicit remaining gates. Preserved the full
chronological history instead of treating earlier pending states as current.
Marked the original Google Cloud guide as a historical installation record and
linked it to the current guide. No remote setup, verification, restart, publication
or reference export was performed during this documentation-only update.

### Administrator reference recovery verified; 404-only connector check passed

The operator reported **Administrator reference recovery verified**. Independently
read both nonsecret root reports: each encrypted reference is 915 bytes; full R2
read-back, independent GET, authenticated decryption, exact deployment equality
and fresh-enrollment policy passed. Both currently contain no approved/pending
subject references. No decrypted contents or passphrases were read by the agent.
Encrypted object keys/checksums and limits are in
[reference recovery evidence](../../evidence/HOSTED_DEMO_REFERENCE_RECOVERY_2026-10-24.json).
Only encrypted references were published; root-private decryption proof remains
on the VM. No reference objects were deleted. Refresh references after enrollment
or changes to the protected deployment. This is not a grant of usable authority.

Read the exact nonsecret tunnel configuration and validated it as `epm-tunnel`:
only `http_status:404`, explicit scoped credential path and loopback metrics.
Temporarily started the unchanged installed connector under its dedicated identity
without enabling it or creating DNS/application routes. At 19:40 UTC (12:40 PDT),
`/ready` returned 200 and metrics showed four HA connections in 3.109 seconds,
zero restarts, approximately 18.6 MB memory at the sample. Finally stopped it;
verified inactive/disabled, unchanged configuration hash and both hosted A/B active.
See [connector evidence](../../evidence/HOSTED_DEMO_TUNNEL_CONNECTIVITY_2026-10-24.json).
This proves outbound edge connectivity with the intended credential/sandbox, not
application origin reachability, Access enforcement or public outage behavior.

Current primary references checked for these observations:
[Cloudflare tunnel observability](https://developers.cloudflare.com/tunnel/observability/)
distinguishes connector health from origin availability; the official
[readiness example](https://developers.cloudflare.com/tunnel/guides/kubernetes/)
documents `/ready` semantics. Kubernetes was not installed or proposed.
The temporary checker passed project Ruff lint/format checks and restored the
connector's stopped state even on failure.

Prepared a read-only hosted-unit boot preflight and post-boot checker at
`/home/dcai/epm-tunnel-stage-20261024/hosted-boot.py`, source from
`/private/tmp/epm-hosted-boot-20261024/hosted-boot.py`. Python Ruff lint/format checks
passed. Preflight confirmed active/enabled hosted units, masked old units, exact
images/mount validators, workspace/schema bindings, sign-in 200, unauthenticated
business 401, and inactive/unbound authorization with zero sessions/enrollments.
Saved root-private `hosted-boot-before.json` in the transition directory. No reboot
or service setting changed in this preflight. Proposed next action is one reboot
and post-boot comparison of unit/command/config/deployment hashes and authority
state. The previous volume reboot used old private units; actual new hosted-unit
boot recovery is still unverified. Separate approval is pending because the last
approved service transition explicitly excluded a reboot. Public routes remain
closed. Latest usage: 62% five-hour / 46% weekly remaining.

Explicit approval requested for the prepared hosted-service reboot verification;
waiting for the operator response. No further reboot was issued.

### Approved hosted-unit reboot verification completed

The operator approved one additional reboot specifically to qualify the enabled
hosted units. Pre-execution checks confirmed the saved boot ID and unchanged
fstab, unit, locator, deployment and port-file hashes. Issued exactly one reboot
request; SSH briefly timed out during startup, then reconnected. No route, service
configuration, identity binding or firewall was changed.

At **12:45 PDT** (19:45 UTC), boot ID changed from
`a240dc3f-7d1f-4fb4-a4b5-0966ad592726` to
`178f0700-e391-4974-a154-4b1947f6e488`. Both hosted units automatically started
active/enabled; old private units remained masked/inactive. A PID 586, B PID 587.
Each exact 250 MiB image automatically mounted (A loop4, B loop5), retaining
512008 allocated blocks and required `rw,nosuid,nodev,noexec` restrictions.
Owning-account physical storage and current workspace/schema/config validation
passed. Unit/command/locator/deployment/port hashes matched the pre-boot snapshot.

Both sign-in pages returned 200 and both unauthenticated business APIs returned
401. Both administrative stores remained inactive/unbound with zero sessions and
pending enrollments; no earlier active-user session existed in this test. Tunnel
remained inactive/disabled. Raw root-private before/after records are in the
transition directory; the nonsecret
[hosted boot evidence](../../evidence/HOSTED_DEMO_HOSTED_BOOT_2026-10-24.json) records exact
hashes and limits. Actual active-session restart and provider/client acceptance
remain pending. No public application route or invitation was created.

Saved checkpoint after boot verification. Latest usage: 45% five-hour and 43%
weekly remaining; neither stop threshold was reached. Documentation whitespace
and new evidence JSON syntax checks passed. No production source changed.

### Isolated lifecycle/fault drill passed; billing inputs supplied

Continued remaining qualification without public routing or A/B mutation. Read-only
health/inventory checks found both hosted units active, VM root disk 22% used with
about 22 GiB free. Inspected retained scratch driver source (not private keys or
captured session files). Prepared a new independent scratch fixture at
`/var/lib/epm-scratch/volume/lifecycle-20261024`, with root-protected deployment
`/etc/epm/hosted-lifecycle-scratch.json` and separate private admin DB under
`/var/lib/epm-scratch/lifecycle-access-20261024`. Existing scratch evidence and A/B
were retained. No new service, mount, fstab entry or network route was created.

Ran the installed qualified application through TestClient using the isolated
seeding environment. Real SQLite, Linux quota validation, actual application
composition, production RSA signature/claim verification, pending enrollment,
explicit synthetic approval, secure session/CSRF and domain Task creation were
used. Only signing-key transport and the application clock were fixture seams;
no application code or storage facts were mocked. The VM clock was not changed.

Checks passed:

- Key cache invalidated plus injected key-fetch OSError rejected business with
  401/`hosted_assertion_rejected`; fixture transport recovery restored access.
- Source-owned restore-marker change fenced the prior session and required fresh
  pending enrollment/approval. Restored the fixture marker baseline afterward,
  without forging business audit events or modifying production data.
- Administrative disablement immediately rejected a previously valid session.
- Closed the app and attempted restore from an invalid archive to a new candidate.
  Restore failed, no replacement/staging survived, source DB bytes were unchanged,
  and its acknowledged Task remained. Full schema/integrity validation passed.
- Fresh application composition with the explicitly replayed prior cookie still
  denied disabled access (`hosted_session_expired`). This is persistence across
  application restart, separate from the earlier inactive A/B boot proof.
- After explicit synthetic reactivation/fresh sign-in, a nine-hour fixture clock
  advance rejected session expiry; a later jump beyond demo expiry rejected a
  still-valid signed proof with 403/`hosted_demo_expired`.

Final fixture operator is disabled. Signing private key/raw cookies were memory-only
and never printed. Driver/report remain account-private or root-owned under the
recorded paths. Both helper Python files passed project Ruff lint/format checks.
See [lifecycle evidence](../../evidence/HOSTED_DEMO_LIFECYCLE_2026-10-24.json) for precise
limits: key transport is injected, HTTP is in-process, marker fencing is simulated
through the owning store, and failed reset covers invalid-archive preparation.
None is described as a real Cloudflare network outage or complete host-loss drill.

The operator supplied trial expiry **January 22, 2027**, and confirmed the **$30
monthly budget alerts configured**. Record these as operator-reported Billing
values; no Console audit or remaining-credit amount was obtained. Review funding
at least seven days before expiry: **January 15, 2027**. This is a manual operations
deadline, not a scheduled reminder or promise of free ongoing E2 hosting.

Next physical gap: real host-disk maintenance admission. Do not fill VM root.
A safe next qualification can use a new bounded disposable outer loop filesystem
as the test host-image pool, containing its own separate 250 MiB workspace image.
Fill only that isolated outer filesystem to cross the production host-pressure
threshold, verify write rejection/read/logout behavior and no partial Task/receipt,
remove only its known test filler, then verify recovery. This has **not** been
provisioned or executed. Preserve all existing volumes/data; no new VM or external
service is proposed. Other remaining gates include remote publication failures,
real provider/client identity/isolation, protected routing, cache and latency.

### Saved usage-threshold stop

After saving lifecycle evidence, Billing inputs and review-guide updates, verified
both hosted services active and the tunnel inactive/disabled. Latest usage became
**8% five-hour remaining / 37% weekly remaining**: the user's five-hour stop
threshold was crossed. Saved this checkpoint and stopped; no new disk-pressure
resource or public route was created, and no process remains running on the agent's
behalf. Resume with the isolated physical host-pressure test plan above only after
usage resets sufficiently and the operator directs continuation. Final checks:
helper Ruff lint/format, evidence JSON syntax and documentation diff whitespace
passed. No production implementation source changed in this turn.

### Physical disposable-disk pressure drill — partial result and usage stop

Resumed above both guards (32% five-hour / 31% weekly remaining). Prepared bounded
512 MiB root-owned disposable outer image
`/var/lib/epm-volumes/epm-pressure-host.ext4`, mounted temporarily at
`/var/lib/epm-pressure-host`, containing its own fully allocated 250 MiB
`images/workspace.ext4`, mounted at `/var/lib/epm-scratch/pressure-volume`.
Used separate synthetic workspace, TMPDIR and administration with real installed
storage facts/RSA/application composition. No A/B image, original scratch image,
fstab or public route was modified. Root disk was not filled.

Attempt 1 stopped before pressure: private umask made root-owned `images/` 0700,
preventing the service identity from statting its pinned image. Validator correctly
rejected it. Controller detached both test mounts. Retained all images/evidence.
Retry explicitly set only this root directory to 0711; the image remains root 0600.
Used a fresh scratch authorization DB and preserved the first DB and failure log.
No image was reformatted for retry.

Attempt 2 reached the assertion-guarded `release` message: physical outer-filesystem
pressure produced 503/`hosted_write_maintenance`, zero Task writes, 404 for the
would-be operation receipt, successful reads (200) and logout (204). The root
controller removed its known test filler. The child then stopped during post-logout
sign-in: its diagnostic driver reused the previous assertion. No recovery-write or
replay success is claimed. Prepared a local correction to advance the fixture
clock two seconds and mint a fresh signed proof before sign-in, consistent with
the existing logout/reauthentication contract; this correction was lint/formatted
but **not uploaded or executed** before the usage guard. Production code unchanged.

Both test mounts/devices are detached; images retained. VM root still had
22888321024 bytes available. Final A/B health check found both hosted services
active; tunnel inactive/disabled. No orphan child or filler remains. See
[partial pressure evidence](../../evidence/HOSTED_DEMO_PRESSURE_PARTIAL_2026-10-24.json).

Root reports/logs are under `/var/lib/epm-recovery/pressure-20261024`:
`attempt-1.json`, `child-attempt-1.log`, current `report.json`, `child.log`.
Installed code is under `/opt/epm/qualification/host-pressure-20261024`; staged
retry helper is `/home/dcai/epm-tunnel-stage-20261024/retry.py`.
Durable private Mac helper copies (including corrected child) are saved outside Git:
`/Users/dcai/Desktop/Property-Management-Data/hosting-qualification/pressure-20261024/`.
These are administrative qualification code, not credentials. Do not blindly rerun
the one-time controller/retry: paths/databases now exist. On resume, preserve this
attempt's report/log, remount only the exact retained images without formatting,
use a new scratch authorization DB, deploy the corrected child and finish recovery
and same-key replay checks. The fresh-provision controller's images-directory
creation also needs explicit chmod if ever reused for another fresh test.

Latest usage reached **8% five-hour / 27% weekly remaining**; user threshold crossed.
Saved partial evidence, helpers and checkpoint and stopped. All three helpers passed
project Ruff check/format checks; documentation diff whitespace passed. The physical
pressure gate remains **partial**, not passed, and public acceptance stays blocked.

### October 24, 2026, 17:09 PDT — pressure recovery completed

Resumed after usage reset (94% five-hour / 26% weekly remaining). Checked A/B
active, tunnel inactive/disabled and test mounts detached. Uploaded corrected
private `child.py` and new guarded `retry2.py`; helpers passed project Ruff lint
and format checks. Preserved attempt 2 report/log as `attempt-2.json` and
`child-attempt-2.log`. Remounted only retained disposable images without formatting;
used a new `hosted-access-retry2.sqlite`. No A/B configuration or data changes.

Fresh post-logout proof fixed the diagnostic driver. Complete third run:
00:08:50–00:09:03 UTC October 25 (17:08:50–17:09:03 PDT October 24).
Outer disk total 510873600 bytes; available 227225600 before, 40869888 under
pressure, 227225600 after filler removal. Write 503/hosted_write_maintenance,
zero partial Tasks, missing receipt 404, reads 200 and logout 204. Recovery create
201; same-key replay and receipt matched, exactly one Task persisted. Scratch
operator disabled on exit. Root report remains in the original pressure report
folder; retained failure logs explain earlier attempts.

Controller removed only its filler and detached both mounts/loop devices. Independent
postcheck: A/B active, tunnel inactive/disabled, neither test mount nor outer loop
mapping present. VM root available 22850138112 bytes. No public routes, restart,
reboot or fstab change. See [complete scoped evidence](../../evidence/HOSTED_DEMO_PRESSURE_2026-10-24.json);
the older partial JSON remains historical. Next: publication/retention fault checks
in a separate scratch prefix, then remaining actual provider/client gates.

### October 24, 2026, 17:10 PDT — R2 failure and retention qualification

Ran installed publication service/adapter against a new isolated scratch prefix,
`epm/53a9ef22-291b-499b-851b-5dabc569e9f1/29b77670-efe7-440e-83c5-b2e2d612d6cb`.
Used a private copy of the previously validated 422727-byte A ciphertext; matched
its recorded SHA-256, without reading passphrases or decrypting again. Root helper:
`/opt/epm/qualification/hosted-transition-20261024/publication-check.py`;
root evidence/ledger/source: `/var/lib/epm-recovery/publication-faults-20261024`.
Private Mac helper saved in `hosting-qualification/publication-20261024/check.py`
under the private data root. Project Ruff lint/format passed.

Actual R2 uploads/full GETs/listing/deletion passed. Refused loopback upload and
real R2 missing-object GET produced typed failures with unchanged prior ledger;
checksum mismatch and ledger-save failure were injected after actual read-back,
with no pruning. Seven simulated daily points plus an eighth candidate exercised
injected deletion failure: eight points retained, old/new objects readable and
attention/pending set. Retry performed one actual scratch-object deletion, retained
seven points and cleared attention; repeat same-day publication did not inflate
points. Actual object listing exactly matched ledger and all seven full hashes
matched. A/B business ledgers stayed byte-identical. No A/B object deletion occurred.

These dates were simulated over the same encrypted bytes; this does not establish
seven elapsed days of operations, real R2 outage, or credential revocation. Seven
small encrypted scratch objects remain for inspection. See
[scoped report](../../evidence/HOSTED_DEMO_PUBLICATION_FAULTS_2026-10-24.json).

### October 24, 2026, 17:10–17:12 PDT — provisional public acceptance routes

Rechecked [Cloudflare's locally managed tunnel procedure](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/local-management/create-local-tunnel/).
Using the existing Mac account certificate through cloudflared (never reading or
transferring its contents), created exact CNAME routes for `demo-a.epmdemo.xyz`
and `demo-b.epmdemo.xyz` to the existing tunnel. Initial tunnel config stayed
404-only/stopped while verifying the edge. Browser-header probes to `/`,
`/api/properties` and an unknown receipt path on both names returned 302 to each
matching path under `epmdemo.cloudflareaccess.com`, with private/no-store cache
policy. Following sign-in redirect returned the Cloudflare Access sign-in page.
A generic Python client without browser Accept/User-Agent received 403 instead;
that failed redirect expectation did not reveal application data or trigger a
policy change. No PIN, JWT, cookie or query-bearing redirect was saved in Git.

Prepared exact candidate routes A→127.0.0.1:8001, B→127.0.0.1:8002 and final
http_status:404. Preserved closed configuration under root-only
`/opt/epm/qualification/public-routes-20261024/closed-config.yml`. A first installer
probe stopped before any mutation because `systemctl is-enabled` returns nonzero
for a disabled unit; corrected the read-only probe to `systemctl show`.
Validated candidate ingress and matched A/B/unmatched test URLs using installed
cloudflared. Started provisional tunnel; readiness 200; A/B stayed active.
Current config SHA-256:
`aa081c7467fafe70adbc75e94b8af504a66a82083952e108398b200fe865d87e`.
No Host/Origin rewrite, port exposure, operator activation, or invitation.
Tunnel is **active but disabled at boot** until acceptance; a reboot will close it.
Installer rolls back to closed config and stops tunnel on its own failure.
[Route report](../../evidence/HOSTED_DEMO_PROVISIONAL_ROUTES_2026-10-24.json).

The next manual step needs the intended operators' email PINs, which the agent
cannot supply. Prepared a two-stage wizard using the unchanged wizard template
library at private Mac path
`/Users/dcai/Desktop/Property-Management-Data/hosting-qualification/routes-20261024/request-enrollment.sh`.
It opens each exact `/sign-in`, asks the user to use separate browser identities,
enter PIN only in browser, and click **Continue to workspace** once. Expected:
**Enrollment is waiting for administrator approval. No workspace access has been granted.**
Only non-secret observed-success flags are saved in sibling `enrollment-check.env`.
Wizard syntax checked; shellcheck unavailable; not run by agent. This is a human
PIN boundary, not an additional deployment-approval requirement. Keep PINs/tokens
out of chat. After user reports both pending, inspect verified pending identities
before explicit activation, refresh administrator reference custody after binding,
and continue real isolation/caching/fault/performance acceptance before invitations.

Final independent authorization check: A/B inactive, unbound, zero sessions and
zero pending enrollments. Six post-start HTTPS probes also returned the expected
Access redirect/no-store; [sanitized edge evidence](../../evidence/HOSTED_DEMO_EDGE_2026-10-24.json).
Latest usage: 73% five-hour / 22% weekly remaining, above both guards. Saved at the
human PIN step, not a usage stop. No background qualification helper remains;
the supervised provisional tunnel remains running intentionally for sign-in.
All administrative Python helpers passed project Ruff lint/format; wizard bash
syntax, new evidence JSON parsing and documentation whitespace checks passed.
No production application code changed and no full suite was required.

### October 24, 2026, 17:20 PDT — repair Cloudflare return navigation

Operator reported `hosted_origin_rejected` immediately after entering the email
PIN, before reaching the application Continue button. Source inspection found the
blanket cross-site Fetch Metadata denial applied even to the public sign-in shell.
A normal top-level browser return from the external identity site can carry
`Sec-Fetch-Site: cross-site`; the previous acceptance probes never exercised this
authenticated browser return. Exact browser request headers were not collected;
that diagnosis is based on the reported phase and reproduced middleware behavior.

Narrow fix: only `GET /sign-in`, no Origin header, Fetch Mode `navigate`, Fetch
Destination `document`, and accepted `text/html` may enter across sites. Host and
loopback checks remain in force. This returns only the existing public no-store
shell; identity/session/enrollment remain required for business access. APIs,
files, unsafe methods, iframe/fetch requests and foreign Origin headers remain
denied. No Access policy, Host rewriting or CSRF relaxation was introduced.

Added nine focused transport cases plus one real-composition shell regression.
Both focused modules: **40 passed**. Ruff check/format passed for all three changed
Python files, using the existing configuration from `application/`. An initial
explicit-config lint invocation from repo root did not resolve the relative
per-file patterns and reported existing implementation-style findings; rerunning
from the documented application directory passed without changing any rule.

Built a new combined wheel using unchanged packaged frontend assets. Compared
all ZIP member names/bytes with the qualified baseline: only middleware source
and RECORD differed. Wheel 2982550 bytes, SHA-256
`c57d4cfc5803d1ff2cd06b9d49c16bacf068b43b30232388009cd6d15633f95a`.
Source baseline is current HEAD `c18869c257143060369cefdd134a350ce356b23e`
plus the saved working-tree middleware patch; app/schema/frontend sources matched
qualified baseline except this fix/tests. Build needed access to the existing uv
cache; no dependencies upgraded.

Staged isolated `/opt/epm/releases/signin-nav-20261024`, copied qualified dependency
venv/schema resources and installed the new wheel offline/no-deps. Verified new
interpreter prefix/import location, service-account access and installed schema/
frontend resource discovery. Qualified release remains untouched for rollback.
Added per-instance systemd drop-ins
`/etc/systemd/system/epm-hosted@{a,b}.service.d/20-signin-navigation.conf`, overriding
only ExecStart to the new interpreter. Restarted/verified A before B; each switch
would remove its drop-in and restart the qualified baseline on failure.

Installed loopback probes on both instances: real cross-site top-level sign-in
navigation returns 200/no-store HTML; cross-site business/file reads return
403/hosted_origin_rejected; foreign Origin sign-in remains 403. Final A/B/tunnel
active. No workspace, authorization path, deployment input or tunnel rule changed;
no operator activation. Root deployment report:
`/opt/epm/qualification/signin-navigation-20261024/report.json`.
Private deployment helper saved under the Mac private data root in
`hosting-qualification/signin-navigation-20261024/deploy.py` (Ruff passed).
[Sanitized release evidence](../../evidence/HOSTED_DEMO_SIGNIN_NAVIGATION_FIX_2026-10-24.json).

Next: operator retries the exact `/sign-in` URL / existing enrollment wizard.
Actual Cloudflare return, PIN and enrollment are still user-verification gates;
installed synthetic-header probes are not claimed as completed browser evidence.
Per-instance ExecStart overrides persist across boot, but no new reboot proof was
performed; tunnel remains boot-disabled for acceptance. Refresh the administrator
reference bundles after eventual approved identity binding as already planned.

### October 24, 2026 — real PIN enrollment and intended identity activation

Operator confirmed the browser return problem is fixed. Read-only SQLite checks
then found exactly one pending enrollment in each demo, both matching their
protected configured email; both operators were inactive/unbound with zero
application sessions. Thus real Access PIN return and the application's verified
pending-enrollment path have now been exercised, rather than inferred from the
synthetic navigation tests.

Activated each intended pending identity through the application administrator
path, which validates workspace binding and verified enrollment. Ran as `epm-a`
then `epm-b`; no raw subject/email/PIN/token was printed or entered in shell args.
An initial attempt as root was rejected by the store's owner-only check before
activation; used the owning identities instead, without changing ownership or
permissions. Both activation calls succeeded. No administrator-created browser
sessions or business record changes. [Sanitized enrollment evidence](../../evidence/HOSTED_DEMO_ENROLLMENT_2026-10-24.json).

Next human step: click **Continue to workspace** in each existing browser session
and verify its Home loads. Remaining acceptance includes wrong-identity/cross-host
rejection, authenticated client behavior/caching/performance, and reference-bundle
refresh now that identities are bound. Existing encrypted references remain
pre-enrollment and are not claimed to contain these bindings. Tunnel remains
provisional active/boot-disabled; no invitations have been sent.

### October 24, 2026 — both authenticated Homes confirmed; reference refresh ready

Operator reports both browsers successfully opened their assigned Home after
activation. This establishes real PIN return, enrollment approval and successful
application-session/Home entry for both identities, as reported by the operator.
It does not yet establish wrong-email rejection, multiple-device isolation,
cache/compression behavior or the quantitative latency gates.

Prepared `/opt/epm/admin/refresh-admin-references.sh`, reusing the unchanged wizard
library and existing encrypted transfer/decryption procedure. It uses the new
`signin-nav-20261024` release and timestamped output folders, preserving all old
bundles. New root-only `reference-validate-current.py` compares decrypted deployment
and approved/pending references to live administrative bindings by read-only SQL;
it prints only booleans/counts and ciphertext object metadata. Previous validator
expected unbound subjects and remains unchanged for the earlier evidence.

Four stages: A export (private passphrase), A R2 upload/read-back/independent
GET/decryption/identity comparison, then equivalent B stages. Only encrypted
bundles leave the VM. Plaintext verification files remain root-private; no sessions,
tokens, signing keys or provider credentials are included by the application model.
Use the administrator-reference password-manager passphrase, distinct from business
archive passphrases. No service interruption, activation or route change.

Installed new helper/wizard; bash syntax and project Ruff lint/format pass.
Shellcheck remains unavailable. The wizard was not run by the agent and current
post-enrollment reference recovery remains pending until the operator completes it.
Run in the **VM terminal**:
`bash /opt/epm/admin/refresh-admin-references.sh`.
Then report **Post-enrollment reference recovery verified**, without passphrases.
Private Mac copies: private data root `hosting-qualification/reference-refresh-20261024/`.
Latest usage at preparation: 49% five-hour / 19% weekly remaining, above both guards.

### October 24, 2026, 17:28–17:29 PDT — post-enrollment references verified

Operator completed the refreshed four-stage wizard. Agent inspected only the new
non-secret root-private reports, not decrypted payloads or passphrases:
A `/var/lib/epm-recovery/a/reference-20261025T002808Z/report.json`,
B `/var/lib/epm-recovery/b/reference-20261025T002852Z/report.json`.
Each encrypted bundle is 987 bytes. Full R2 read-back, independent download,
decryption, exact deployment match, approved subject match, pending references
match (one each) and fresh-enrollment-required restoration policy all passed.
Both exports now include their approved identity references; neither contains
usable sessions/tokens or provider credentials. Previous encrypted bundles remain.
A SHA-256 `1aa0c8f425b9ca50bb5361a9686f5e95796f4417af3f7aed76651a04dac8eea8`;
B `176ec24ecfde99c23eeae9c599426b83e79ddbe6332c64bc904d6f08247466cb`.
[Complete sanitized reports](../../evidence/HOSTED_DEMO_POST_ENROLLMENT_REFERENCES_2026-10-24.json).
All three supervised services active at check. This is not a bare-host rebuild proof.

Next acceptance step requires actual browser identities. Prepared a three-stage
wizard at private Mac path
`/Users/dcai/Desktop/Property-Management-Data/hosting-qualification/isolation-20261024/check-isolation.sh`:
A-only fresh session denied at B, B-only fresh session denied at A, then original
assigned Home pages still usable. It saves only yes/no observations in sibling
`isolation-check.env`. A login form alone is explicitly inconclusive; the user
must stop/report rather than mark it passed. Profiles/private-cookie separation
is specified to prevent an old target-account cookie from invalidating the test.
No policy change, token collection, mutation or automatic sending. Uses unchanged
wizard library, syntax checked; not run by the agent. Shellcheck unavailable.
API/file/receipt isolation, third uninvited identity, session lifecycle,
caching/compression and quantitative load/latency acceptance remain separate.
Usage at start of this check: 44% five-hour / 18% weekly remaining, above guards.

### October 24, 2026, 17:43 PDT — cross-account test expectation corrected

Operator screenshot after A-only sign-in and navigation to B shows Cloudflare's
**Log in to EPM Demo B** email form, not B business data or an explicit denial.
This is inconclusive for wrong-identity rejection. The wizard expected an explicit
denial too early; a separate OTP application can request email identity again.
No Access policy/application change is justified by that screen.

Checked [official OTP documentation](https://developers.cloudflare.com/cloudflare-one/integrations/identity-providers/one-time-pin/)
and [troubleshooting](https://developers.cloudflare.com/cloudflare-one/troubleshooting/access/).
Only policy-allowed addresses receive PIN mail; the UI says a code was emailed
even when it was not, to prevent enumeration. Non-delivery alone is not conclusive
because delivery can also fail. Authentication log entries require code submission,
so merely requesting a blocked address must not be claimed as a logged denial.

Corrected private wizard stage instructions: in B's form try the A address, never
switch to B identity; report any newly delivered B-login PIN at A address. Mirror
for B at A. Retain explicit-denial confirmation guards; neither a login form,
code-sent text nor missing mail is accepted as a passed check. Existing running
wizard still uses its old instructions: answer N at its current prompt. No
cross-account pass recorded. Next requires the wrong-email attempt and, when
mail is suppressed, separate policy-evaluation evidence rather than invented denial.
Wizard bash syntax checked; no production code, policy or route change.

### October 24, 2026 — application policy tester confirms the A/B decision matrix

Operator reports all four application-level Cloudflare policy tester results
match: Demo A allows only the configured A identity and denies B; Demo B allows
only B and denies A. Both identities already completed real Access sign-in, so
the tester can evaluate their existing identity records. This is operator-reported
policy evaluation, not an agent/provider API audit. [Sanitized evidence](../../evidence/HOSTED_DEMO_ACCESS_POLICY_2026-10-24.json).

Operator also reports no PIN delivery when requesting A at B or B at A. Retain
those as supporting observations only; they were not promoted into explicit
browser denials. The original isolation wizard's immediate-denial expectation
was incorrect for this OTP flow and its confirmation flags remain unmarked.
The policy tester supplies the email-policy decision evidence instead. Broader
API/file/receipt/foreign-ID isolation and an additional uninvited identity remain
separate gates, alongside sessions, caching and performance.

Read-only service/storage check: A, B and tunnel active; tunnel still boot-disabled.
Root filesystem 25% used (22 GiB available); A/B mounted volumes 5% used (181 MiB
available each), snapshot only. No restart, route or policy changes.

Prepared next manual wizard at private Mac path
`/Users/dcai/Desktop/Property-Management-Data/hosting-qualification/session-20261024/check-sessions.sh`.
Two stages cover each account's Sign out this device, refresh while signed out,
Renew Cloudflare sign-in with a new email PIN, and explicit Continue back to its
Home. Warns that renewal may sign out broader Access sessions; requires assigned
identity, no private data before renewed sign-in, and no unsaved work at start.
Only success flags go to sibling `session-check.env`; no PIN/cookie/token captured.
Library byte-identical to wizard template; bash syntax passed, shellcheck unavailable.
Not run by agent, so session checks remain pending. Usage at preparation:
35% five-hour / 16% weekly remaining, above both guards.

### October 24, 2026 — device logout/refresh/fresh sign-in passed

Operator reports both device logout checks passed. Local private wizard result
contains `DEMO_A_LOGOUT_REFRESH_REAUTH=yes` and the equivalent B flag. Recorded
behavior: Sign out this device hides private content, refresh stays signed out,
new Cloudflare sign-in plus explicit Continue restores assigned Home. No PIN,
identity JSON or raw session cookie was collected.
[Scoped evidence](../../evidence/HOSTED_DEMO_DEVICE_LOGOUT_2026-10-24.json).

Read-only administration snapshot: both approved operators active. A had three
stored/currently eligible sessions, B two. Device-only logout leaves other sessions
valid by design; these counts do not prove all-device revocation or identify which
client owns a session. A/B/tunnel all active; tunnel remains disabled at boot.

Next prepared manual test uses two independent sessions per operator: computer
plus phone preferred, or separate browsers/profiles; ordinary cookie-sharing tabs
are insufficient. Sign out all devices on A must close both A sessions within one
visible-browser check interval (60 seconds), while B stays usable BEFORE any
Cloudflare renewal. Then explicitly restore A. Mirror for B. Provider-wide renewal
can affect broader Access sessions, so other-account check happens first.

Wizard private Mac path:
`/Users/dcai/Desktop/Property-Management-Data/hosting-qualification/multisession-20261024/check-multiple-sessions.sh`.
Two stages, four success flags saved in sibling `multisession-check.env`; no
business mutation or server changes. Save/discard unsaved input first. Shared
wizard library preserved exactly; bash syntax passed, shellcheck unavailable.
Not run by agent; no multi-session result claimed. This test does not complete
shared-editing/transaction/file/receipt/cache/performance acceptance. Usage at
preparation: 32% five-hour / 16% weekly remaining, above both guards.

### October 24, 2026 — both multi-session sign-out checks passed

Operator reports both two-session Sign out all devices checks passed; all four
private wizard flags are yes. Recorded observations: two independent sessions
for each identity closed within 60 seconds, other account remained usable before
provider renewal, then both same-account sessions explicitly reopened after fresh
identity proofs. Exact devices/network were not captured; do not infer a particular
phone model, browser, network or measured latency. [Scoped evidence](../../evidence/HOSTED_DEMO_MULTISESSION_LOGOUT_2026-10-24.json).
No production application/configuration/policy/route change.

Prepared next two-stage Task persistence/foreign-ID browser wizard at
`/Users/dcai/Desktop/Property-Management-Data/hosting-qualification/record-isolation-20261024/check-records.sh`.
Uses existing real `task.create` workflow: one unique-labelled synthetic Task per
workspace, acknowledged creation once, saved-record refresh and second-session
visibility, then change ONLY the hostname in its saved-record URL and open under
the other account's own valid session. Foreign Task must be unavailable with no
record data while own Home works; a Cloudflare login page is inconclusive.
Stop on ambiguous creation rather than creating a second operation. Leave both
Tasks for later read-only owning database/receipt/audit verification. Private
`expected-titles.json` records unique labels; only successful observation flags
and labels go to `record-check.env`. Both remain outside Git. No files, expenses
or customer records are requested; successful test will add two synthetic Tasks.
The next business backup must account for these new edits; existing recovery
points predate them. Wizard library preserved, bash syntax passed, shellcheck
unavailable; agent has not run it and record tests are pending.
Usage at preparation: 27% five-hour / 15% weekly remaining, above both guards.
