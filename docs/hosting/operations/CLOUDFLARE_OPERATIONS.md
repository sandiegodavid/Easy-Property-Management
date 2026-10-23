# Cloudflare and VM deployment record

Consolidated October 24, 2026. This is the cumulative record of the completed Google
Cloud/Cloudflare/R2 setup and subsequent operations. Append new dated operations here; keep
one current resume action in the [qualification
plan](../qualification/HOSTED_DEMO_PUBLIC_ACCESS_PLAN.md). Dates are America/Los_Angeles
unless explicitly UTC. Recorded values are snapshots, not live monitoring.

## Human review guide — October 24, 2026

Two independent synthetic portfolios run on authenticated hosted processes. Both intended
operators are active, use their own Home, and passed reported device/all-session logout and
Task persistence/foreign-record, File/result-isolation, receipt-isolation, and search/bootstrap-isolation checks. Cloudflare DNS is Active; exact A/B origin routes and the tunnel are active for
acceptance. **The tunnel remains disabled at boot; general invitations and the full
acceptance completion are pending.** Policy tester decisions match A-only/B-only. Reference
custody includes current bindings.

For purpose and requirements read [design](../design/HOSTED_DEMO_DESIGN.md); for commands
use [deployment](../deployment/GOOGLE_CLOUD_DEMO_DEPLOYMENT.md) and
[operations](HOSTED_DEMO_OPERATIONS.md). For remaining qualification gates, use the
qualification plan.

## Infrastructure and path inventory

| Component | Latest recorded configuration | Evidence / qualification boundary |
| --- | --- | --- |
| Google Cloud | Project `project-47b72bb7-ba90-42c9-910`, VM `epm-demo`, Oregon `us-west1-b`; Ubuntu 24.04 x86_64, E2 medium, 30 GB disk | [Initial VM setup](../deployment/GOOGLE_CLOUD_DEMO_DEPLOYMENT.md); the trial/billing Console remains authoritative for actual credit/expiry |
| Administrator SSH | IAP tunnel; VM tag `epm-admin`; instructed SSH source range `35.235.240.0/20`, TCP 22 | Initial firewall/IAP procedure is in the Google guide; no fresh effective-firewall audit was performed for this summary |
| Domain | `epmdemo.xyz`, Cloudflare Full DNS / Free; Porkbun remains registrar | Operator screenshot showed Active after delegation to `bonnie.ns.cloudflare.com` and `vasilii.ns.cloudflare.com` |
| Public application origins | Exact `https://demo-a.epmdemo.xyz` and `https://demo-b.epmdemo.xyz` | Provisional routes active; approved operators reached Home; broader acceptance pending |
| Identity | Team `epmdemo.cloudflareaccess.com`; two distinct Access audiences; separate supplied A/B sign-in emails | Inputs privately captured; operator confirmed exact-host, single-email Allow, PIN-only login, eight-hour duration, no broad/Bypass grant; real sign-in passed per operator |
| Current release | `/opt/epm/releases/signin-nav-20261024/venv`; package 0.1.0, Python 3.14.9; qualified baseline plus narrow sign-in navigation fix | [Fix and verification](../evidence/HOSTED_DEMO_SIGNIN_NAVIGATION_FIX_2026-10-24.json); wheel SHA-256 `c57d4cfc5803d1ff2cd06b9d49c16bacf068b43b30232388009cd6d15633f95a`; frontend/schema/dependencies unchanged |
| Current processes | `epm-hosted@a.service` and `epm-hosted@b.service`, active/enabled; Unix users `epm-a` / `epm-b`; listeners only `127.0.0.1:8001` / `8002` | [Private switch evidence](../evidence/HOSTED_DEMO_PRIVATE_SWITCH_2026-10-24.json); one writer per workspace |
| Current workspace locators | `/var/lib/epm-a/hosted-local.json` and `/var/lib/epm-b/hosted-local.json` | Use these in current hosted administration/backup commands |
| Current business data | `/var/lib/epm-a/volume/workspace` and `/var/lib/epm-b/volume/workspace` | Fresh current-format synthetic portfolios; IDs below |
| Storage budget | Root-owned `/var/lib/epm-volumes/epm-a.ext4` and `epm-b.ext4`; each 262144000 bytes, fully allocated; complete ext4 mounts with `rw,nodev,nosuid,noexec` | Both automatically remounted after approved reboot; TMPDIR is each volume's private `tmp`; [boot evidence](../evidence/HOSTED_DEMO_AB_BOOT_2026-10-24.json) |
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

The protected configuration's draft enablement window is October 24, 18:51:09 UTC through
November 7, 18:51:09 UTC. It was generated during preparation, before operator activation.
Review the intended dates before general invitations or renewal; the fourteen-day limit is
enforced, and documentation does not silently renew it.

## Release and credential inventory

| Artifact | Recorded value / custody |
| --- | --- |
| Initial local release | `demo-001`, source f5c1518b7d97a309660e642964c45244516c0a54; original Mac Python 3.14.8, VM 3.14.9; retained masked/private only |
| Qualified hosted baseline | c8aab47415b42dba0dec3545b117143a95ce49ef; wheel 2982482 bytes, SHA-256 6adcfb4fea6d953c5a83697417c2a0c2a081e66d1cf4288ad781d8327297fa85 |
| Current installed release | `signin-nav-20261024`; source baseline c18869c257143060369cefdd134a350ce356b23e plus recorded navigation patch; wheel 2982550 bytes, SHA-256 c57d4cfc5803d1ff2cd06b9d49c16bacf068b43b30232388009cd6d15633f95a |
| Wheel content delta | Only hosted middleware and RECORD differ from qualified wheel; frontend/schema/dependencies unchanged |
| Linux runtime | CPython 3.14.9, SQLite 3.53.1, SQLAlchemy 2.1.6, Pydantic 2.14.1, cryptography 46.0.7; boto3/botocore 1.43.118; exact constraints retained with qualified release |
| Effective service override | `/etc/systemd/system/epm-hosted@{a,b}.service.d/20-signin-navigation.conf`; template retains baseline, override pins current interpreter |
| cloudflared | 2026.10.3 Linux AMD64 SHA-256 053b80b0a23031a038fdbf3c073f59f82b8f1f152aa67971d7383ffafc0dbab0 |
| Current ingress SHA-256 | aa081c7467fafe70adbc75e94b8af504a66a82083952e108398b200fe865d87e |
| Closed-ingress fallback | `/opt/epm/qualification/public-routes-20261024/closed-config.yml`; SHA-256 8dd9df8a5771de7f39bff2b41d84348083a59564619dda4946393d20adc5f0c9 |
| Private Mac inputs | `/Users/dcai/Desktop/Property-Management-Data/hosted-demo-epmdemo.inputs.json`, mode 0600; root-private VM copy `/etc/epm/hosted-epmdemo.inputs.json` |
| Tunnel secret custody | Mac management cert stays `~/.cloudflared/cert.pem`; scoped JSON only at VM `/etc/epm-tunnel/credentials.json`, root:epm-tunnel 0640 |
| Recovery configs/ledgers | `/etc/epm/recovery-{a,b,scratch}.json` root 0600; `/var/lib/epm-recovery/{a,b,scratch}/ledger.json`, private root-owned folders |
| R2 deployment bindings | A 49fdb458-48a0-4029-9c4f-95e9710f8eb8; B 485044ba-07d6-41fe-8448-3735033f6930; object prefixes also contain exact workspace UUID |

Do not print private input/configuration or decrypted reference files. Runtime environment
carries ports/TMPDIR, not S3 credentials or account management certs. Agent SSH account is
`dcai`; human VM login is `dctech92130`. Shared helpers live under `/opt/epm/admin`, not
either user's home-dependent `~/` paths.

## Completed operations — October 23, 2026

1. Established Google trial Ubuntu E2 medium, separate non-login A/B identities,
   initial verified wheel/schema bundle and independently seeded private portfolios.
   IAP administrator access and private local-mode port forwarding were recorded.
2. Created private R2 Standard recovery bucket with operator-held S3 credentials.
   Dashboard privacy/scope/default location were instructed and operator-reported;
   S3 authenticated success is not an independent dashboard configuration audit.
   Endpoint is the standard 32-hex-account form; jurisdiction variants unqualified.
3. Provisioned isolated scratch Linux quota filesystem and installed dependency
   environment. Real SQLite FULL/rollback, concurrent 50 MiB upload/staging,
   original-result and byte checks passed within documented scope.
4. Created encrypted synthetic archive, real R2 full read-back, independent restore
   and encrypted reference recovery; matched 42 rows/105 tables and two files
   totaling 51 MiB. Archive was 120115 bytes and reference 1008 bytes; no objects
   pruned in that first-point drill. Scratch deployment ID
   44fb3d77-0ae8-4fab-a815-a8f528aa3c56, workspace
   1eb0d18b-f130-45a0-a043-1cd3d27979cf. Local test passphrases remain root-private;
   that scratch custody is not the operational password-manager policy.
5. Qualified installed wheel/service sandbox and persistent scratch boot remount
   through a separately approved reboot. Startup 17.661 seconds, sampled peak
   memory 204075008 bytes, zero automatic restarts; these are idle startup samples,
   not workload capacity. Original A/B data/commands remained unchanged at that stage.

## Completed operations — October 24, 2026

1. Delegated `epmdemo.xyz` from Porkbun to the assigned Cloudflare nameservers;
   operator screenshot confirmed Active. Reviewed exact-host email/PIN Access
   applications, distinct audiences and eight-hour constraints; actual inputs
   captured privately. Established scoped tunnel credential and dedicated sandbox.
2. Created fresh current-format portfolios inside independent fully allocated
   250 MiB volumes. Greenfield scope keeps strict current schema and no migration
   compatibility. Each seeded portfolio: 14 properties, 15 spaces, 20 providers,
   9 leases, 12 tenants, 40 expenses, 6 communications, 4 maintenance issues,
   6 quotes, 3 appointments, 9 deposits/receipts, 1 Task and 1 condition report.
   Stable IDs/ownership/financial scenarios passed. Catalog/journal remain in quota.
3. Created and verified complete fresh business recovery points. A archive
   `/var/backups/epm-a/fresh-hosted-20261024T190113Z.epm-backup`, 422727 bytes,
   SHA-256 18bd8fdc1743456c24b7302f0d81f7d420f49c4cfea37c86bfdf60a1e974eaec;
   B `/var/backups/epm-b/fresh-hosted-20261024T190456Z.epm-backup`, 421320 bytes,
   SHA-256 46ed79dbf29d40eb52bb8d04a0c20c413c6e917b7719fd5df35ca2d46fec93e0.
   Real R2 independent downloads/restores passed; A compared 105 tables/1432 rows,
   737 shared audit events and complete financial/domain verification. All shared
   history unchanged; only exact correlated post-snapshot backup/retention and
   destination restore events allowed. Fresh portfolios contain no managed files.
4. Installed approved A/B fstab mounts and verified reboot remount/full allocation.
   Host fstrim uses `--listed-in` honoring `X-fstrim.notrim`; no image TRIM.
   Switched A then B to hosted services, keeping one writer and old units masked.
   Private probes: sign-in 200/no-store, no identity API 401/no-store, wrong Host/
   foreign Origin 403, protected HTML 303. Compatible private-service fallback was
   exercised; deployment paths and preserved old identities remain in inventory.
5. Verified initial A/B encrypted administrator references (915 bytes each) and
   a temporary 404-only tunnel readiness check (four HA connections, 3.109 seconds,
   18591744 bytes sampled memory, zero restarts), then closed it. Readiness only
   established connector transport/credential/sandbox behavior.
6. Rebooted hosted units in an approved interruption window: auto-start, exact
   mount/configuration/workspace bindings and old-unit masking passed. Boot ID
   178f0700-e391-4974-a154-4b1947f6e488; preceding ID
   a240dc3f-7d1f-4fb4-a4b5-0966ad592726. This was before real enrollment and current
   per-instance release overrides, not proof of final active-session persistence.
7. Isolated installed-app lifecycle drill verified key-fetch outage/recovery,
   restore-marker fencing, disablement, prior-cookie restart denial, session/demo
   expiry and invalid-archive reset preserving acknowledged data. Synthetic RSA/
   key transport/clock were explicit fixtures; VM clock and A/B unchanged.
8. Disposable 512 MiB outer disk with 250 MiB inner workspace verified physical
   host-pressure admission: available bytes 227225600 → 40869888 → 227225600 out
   of 510873600. Write 503, no partial Task/receipt, reads 200/logout 204; recovery
   create 201 and same-key replay/receipt with exactly one effect. Filler removed,
   mounts/loops detached, images retained. VM root not filled; available snapshot
   22850138112 bytes. Final result supersedes the partial report, which is retained.
9. Isolated R2 publication/retention drill kept seven encrypted points, performed
   one actual scratch delete and full object/hash verification. Typed upload/missing
   read/checksum/ledger/prune failures preserved proof and retry repaired retention.
   Dates simulated over verified ciphertext; A/B ledgers unchanged. Scratch prefix
   `epm/53a9ef22-291b-499b-851b-5dabc569e9f1/29b77670-efe7-440e-83c5-b2e2d612d6cb`.
10. Added exact A/B CNAMEs, verified Access interception of unauthenticated shell/
    API/receipt paths, validated fixed ingress/unmatched 404 and started provisional
    tunnel. Browser-header probes: 302 to matching team application login with
    private/no-store; generic non-browser probes may receive 403. No credentials
    or redirect query/cookie/token captured. Tunnel stays boot-disabled.
11. Installed current navigation-compatible wheel A then B. Effective per-instance
    overrides persist; original qualified release retained. Top-level public sign-in
    navigation 200/no-store; cross-site APIs/files/foreign Origin 403. Forty focused
    transport/composition tests and three-file Ruff checks passed. User confirmed
    real Cloudflare return, pending verified enrollment and both assigned Homes.
12. Matched one verified pending identity per account and activated through the
    owner-account administrator path. Refreshed current-binding references:
    A 987 bytes, SHA-256 1aa0c8f425b9ca50bb5361a9686f5e95796f4417af3f7aed76651a04dac8eea8;
    B 987 bytes, SHA-256 176ec24ecfde99c23eeae9c599426b83e79ddbe6332c64bc904d6f08247466cb.
    Full R2 GET, independent download/decrypt and current approved/pending match
    passed. Approved references present; one pending reference each; fresh
    enrollment still required on restoration. Decrypted proofs remain root-private.
13. Operator reported all four application policy tester decisions correct. Both
    wrong-application email attempts received no PIN; those are supporting only,
    not explicit denial proof. Operator and saved flags confirm device logout/
    refresh/fresh login and independent-session all-device revocation within 60
    seconds, with the other account usable before provider renewal. Exact
    devices/network were not captured.
14. Operator completed the unique two-Task persistence/foreign-ID browser check. Each Task
    remained visible after refresh and in a second independent session; the same saved-record
    URL under the other authorized hostname was rejected without foreign business data.
    Read-only database inspection independently found exactly one own Task, no counterpart
    Task, one creation receipt, and one `created` Audit event attributed to
    `hosted_operator` in each workspace. Synthetic titles and identifiers remain private.
15. Operator completed the two synthetic maintenance-evidence File checks. Each owner saw
    its own metadata and downloaded matching bytes; the other authorized demo received no
    metadata or content bytes. Each owner recovered its upload result by idempotency key and
    operation ID, while the other demo was rejected on both paths. Read-only inspection found
    one owner-only available local File/link/upload receipt/`hosted_operator` creation audit
    per workspace; the stored 47-byte objects matched their retained SHA-256 values.
16. Operator completed the seeded rent-receipt isolation check. Each owner viewed its own
    receipt; the other authorized demo was rejected by both the UI route and direct receipt
    API. Read-only inspection found one owner-only receipt and allocation, no counterpart
    receipt, and one retained `recorded`/`local_operator` audit event per workspace. Those
    seeded records predate hosted enrollment, so their historical actor is expected.
17. Operator completed exact synthetic Task search and bootstrap-binding checks. Each demo
    found only its own Task and no counterpart Task result. Each bootstrap response reported
    its own workspace binding only. Read-only inspection confirmed distinct A/B workspace
    manifest UUIDs and exactly one own/no counterpart source Task row per workspace.

## Artifact and evidence lookup

| Retained VM artifact | Purpose |
| --- | --- |
| `/opt/epm/qualification/hosted-transition-20261024` | Switch/boot/connector/lifecycle reports and helpers |
| `/opt/epm/qualification/public-routes-20261024` | Closed ingress fallback and provisional route report |
| `/opt/epm/qualification/signin-navigation-20261024` | Current release's loopback navigation/security verification |
| `/var/lib/epm-recovery/a/reference-20261025T002808Z/report.json` | Current A reference proof (UTC timestamp) |
| `/var/lib/epm-recovery/b/reference-20261025T002852Z/report.json` | Current B reference proof (UTC timestamp) |
| `/var/lib/epm-recovery/pressure-20261024` | Completed physical-pressure report and retained earlier observations |
| `/var/lib/epm-recovery/publication-faults-20261024` | Isolated R2 fault/retention ledger, ciphertext and report |
| `/opt/epm/qualification/host-pressure-20261024` | Pressure protocol/helper code; one-time provisioning must not be replayed |
| `/var/lib/epm-scratch/volume/lifecycle-20261024` | Retained isolated lifecycle fixture; operator disabled after drill |
| `/Users/dcai/Desktop/Property-Management-Data/hosting-qualification/` | Private Mac helper copies and observed-success flags |

Detailed checksums, timestamps, private proof destinations, source test totals, interruption
scopes and retained scratch artifacts are in the [qualification
register](../qualification/HOSTED_DEMO_PUBLIC_ACCESS_PLAN.md), raw [evidence](../evidence)
and [preserved source records](../archive/README.md). Preserve evidence limitations:
operator reports are not independent provider audits; injected time/transport and simulated
retention dates are not elapsed production history; archive validation does not prove
current provider reachability; reference recovery is not a complete lost-host rebuild.
General invitations, final sizing and performance acceptance remain pending.

## New operations

Append future dated setup/verification records here. Include purpose, exact scope,
release/configuration binding, operation/results, evidence paths and remaining limits; never
add credentials or repeated resume checkpoints. Update the single qualification checkpoint
when the next action changes.
