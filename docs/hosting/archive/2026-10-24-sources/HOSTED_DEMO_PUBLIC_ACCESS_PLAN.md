# Public access for the two-workspace Google Cloud demo

For a human review of the complete recorded setup and verification history, start
with the [operations review guide](../../operations/CLOUDFLARE_OPERATIONS.md#human-review-guide--october-24-2026).

Date: October 23, 2026.

Status: design decisions accepted October 23, 2026, following the product owner's instruction to use the recommendations for all decisions. Implementation is in progress (Slices 1–6 implemented; Slice 7 source controls implemented with physical/off-host qualification pending; Slice 8 pending, as recorded below). Deployment acceptance is in progress: provisional Access-protected A/B routes are active; operator activation and invitations remain pending. Acceptance of the design is not evidence that a release gate passed or an instruction to publish the existing release.

## Goal and relationship to existing plans

Give two invited operators ordinary HTTPS links to their own persistent synthetic workspaces, usable from a phone or computer without SSH, Google Cloud accounts, or local software installation.

The existing [Google Cloud deployment](../../deployment/GOOGLE_CLOUD_DEMO_DEPLOYMENT.md) supplies the Ubuntu E2 VM, separate `epm-a`/`epm-b` identities and directories, current release, and private administrator access. The [hosted demo proposal](../../design/HOSTED_DEMO_DESIGN.md) supplies the candidate identity, session, isolation, concurrency, and lifecycle requirements. This plan sequences the remaining work against the current [architecture](../../../ARCHITECTURE.md), [product decisions](../../../DECISIONS.md), [local security contract](../../../platform/security-and-audit.md), [operator experience](../../../ui/operator-experience.md), and [frontend architecture](../../../ui/frontend-architecture.md).

The product brief and agreed decisions defer remote access and authentication beyond the local MVP. The product owner has accepted this bounded synthetic hosted experiment alongside that MVP, associated with SAAS-001, SEC-001, and SEC-002 in the [backlog](../../../FEATURE_BACKLOG.md#future-saas--cloud-identity-and-collaboration). It does not complete those larger features, change their ordered dependencies, introduce commercial billing, or authorize a shared portfolio. Normal local use remains available without an account or cloud dependency. This document is the accepted scope and decision record for the experiment; a second scope-approval step is not required.

## Current evidence and blockers

| Boundary | Present behavior | Required change |
| --- | --- | --- |
| CLI and listener | `app.__main__` binds to `127.0.0.1`; its configurable origins are loopback-only | An explicit hosted launch/configuration contract, still listening only on a private origin |
| Browser transport | `platform/browser_transport.py` rejects non-loopback Host/Origin; the local-client header is intent, not identity | Separate hosted policy with exact HTTPS origin, authenticated requests, and CSRF enforcement |
| Authentication | No hosted sign-in or revocable application session | Verify Cloudflare Access assertions and bind durable sessions to a provisioned identity |
| Authorization | One local operator; no hosted membership boundary | Bind each authorized subject, hostname, process, workspace, and capability set server-side |
| Audit | Actor kinds currently include `local_operator`, `system`, `connector`, and `ai_assistant` | Define and validate a hosted operator actor; propagate verified identity into owning operations |
| Browser state | Query/runtime identity, unfinished forms, revisions, and receipt recovery already exist | Include authenticated session/runtime transitions, expiry, revocation, and cross-device proof |
| Operations | Two systemd services, independent restored workspaces, private Mac SSH tunnel | Hosted runtime qualification, access expiry/revocation, quotas, current off-host backups, and recovery drill |

Domain APIs, Files, search, bootstrap, activity, and original-result lookup all expose workspace information. Protecting only HTML or hiding controls is insufficient. No Cloudflare configuration can make the current local-only release a qualified hosted release by itself.

## Target topology and boundaries

```text
Operator A → demo-a.<domain> → Cloudflare Access A → named tunnel → hosted process A → workspace A
Operator B → demo-b.<domain> → Cloudflare Access B → named tunnel → hosted process B → workspace B
```

Use two Access applications and exact email allowlists, one named tunnel with two fixed routes, and the existing isolated Unix users/workspaces. Each application process verifies its own configured Access issuer and audience, exact public origin, provisioned subject, expected workspace ID, and current session state. Unknown hosts and unmatched tunnel routes fail closed. Never select a workspace filesystem path from a request, email header, or client-supplied ID.

The application remains one process/writer per workspace. A hosted process replaces the corresponding local process; do not run both against the same workspace or add Uvicorn workers. Both processes share a VM failure domain. The administrator retains IAP SSH access; application operators receive no VM credentials.

## Accepted cost and latency policy

The recommendations from the [cost and latency review](../../qualification/reports/HOSTED_DEMO_COST_LATENCY_REVIEW_2026-10-23.txt) are adopted for this experiment. Recommendations in the commercial/MVP source notes do not override these choices.

- Keep the existing Oregon E2 `e2-medium`, Ubuntu VM, two systemd services, one named tunnel and combined frontend/backend release during qualification. E2 medium exposes two vCPUs but provides one sustained fractional vCPU in aggregate, with bursting; do not size it as two dedicated cores. Keep both workspaces running during their advertised demo period.
- Use Cloudflare's eligible free Zero Trust/Access plan, an existing administrator-controlled domain where available, and `demo-a.<domain>` / `demo-b.<domain>`. If no suitable domain exists, purchase one ordinary domain and record its actual registration/renewal cost before deployment. The domain and operator email values remain deployment inputs, not unresolved architecture choices.
- Do not add managed Postgres, relay servers, an AI gateway, Pages, Workers, a separate background host, Kubernetes, Spot capacity, or a paid load balancer for this demo. Use the current private origin and same-origin `/api` routing. Keep the external IPv4 until a cheaper alternative with working outbound connectivity is qualified; do not introduce Cloud NAT just to remove it.
- Keep live SQLite and attachments on local persistent disk, with file bytes served through authenticated owning APIs. Select R2 Standard as the off-host destination for completed, encrypted application archives only. Do not select it as the current S3 file provider: that adapter requires bucket versioning/VersionId, which R2 does not supply. Direct browser presigned transfers and thumbnails are deferred until file-traffic measurements justify a separately qualified contract.
- Qualify compression and caching for approved fingerprinted assets on the existing public origins. Verify actual `Content-Encoding`, browser reuse and Cloudflare cache eligibility/hits with Access enabled. Keep private HTML, APIs, sessions, errors and downloads non-shared and `no-store`. No Cache Everything rule, cross-origin API split or authentication bypass is allowed to improve apparent performance.
- Keep existing WAL/deferred-read/immediate-write behavior and the configured five-second busy timeout. Do not introduce `synchronous=NORMAL`, new read-pool assumptions, or mmap/cache tuning as unmeasured defaults. Inspect actual settings and measured hot query plans before tuning; acknowledged financial durability cannot be reduced as a latency optimization.
- Preserve live Home reads and independent attention refresh. A change marker is an additional fifteen-second visible-browser poll with jitter/backoff and hidden-tab suspension, not a replacement for focus/reconnect, periodic refresh or `nextTransitionAt`. No Home snapshot/cache is required initially. Any later cache must include authorized workspace/runtime/scope/filter/period identity and expire on both source changes and relevant time transitions; reconsider only after the existing latency gate fails under measured hosted load.
- Target USD 30/month for ongoing infrastructure before tax and domain registration, using actual regional/account prices and all compute, disk, IPv4, transfer and backup usage. This is a planning target, not a quote or spending cap. Retain the USD 30 budget notifications, record gross usage before trial credits, and review at least seven days before trial expiry. The product owner decides whether to fund ongoing hosting; do not silently upgrade billing or promise the demo beyond funded operation. Plan a final off-host backup and orderly suspension if funding is not arranged.
- Evaluate a 2 GB configuration only after the current baseline passes and measurements suggest sufficient headroom. Qualification must repeat on the smaller machine, with adjusted per-service limits, at least 25% total memory headroom, no OOM/restart failures, and the latency gates below under four-browser/background load. Trial credits alone are not a reason to change provider or region. Keep Oregon unless measured invited-user latency justifies a controlled move.

### Measurement and acceptance targets

These are accepted targets to measure, not claims that the VM already meets them. Separate origin execution from browser/network time and measure first login/PIN delivery independently. Record client location, device, network RTT/bandwidth, release, cold/warm cache state, p50/p95, request/byte counts, peak total/ per-service memory, CPU throttling, lock waits and restart counts.

| Measurement | Acceptance target |
| --- | --- |
| Warm authenticated Home/API origin response, including authentication | p95 at most one second for ordinary bounded reads; preserve owning query ceilings |
| Warm Home usable in browser | p95 at most 1.5 seconds on the reference network: RTT at most 100 ms and throughput at least 20 Mbps |
| Cold application assets plus initial Home, after identity sign-in | p95 at most three seconds on the reference desktop network; at most five seconds on the reference mobile network: RTT at most 150 ms and throughput at least 10 Mbps |
| Local shell/navigation feedback | p95 at most 100 ms; remote content loading remains visible and distinct |
| Ordinary non-file mutation completion | p95 at most 1.5 seconds on the reference network; never trade original-key recovery for a faster ambiguous result |
| Incremental local authentication/session overhead | p95 at most 20 ms; one indexed local authorization SELECT per protected request, no routine auth-maintenance write or provider call |

Use at least fifty observations per measured operation/cache condition, repeated in three runs. Exercise A and B with two visible browser sessions each, first without background load, then with a bounded report and staggered backup workload. A backup requiring that workspace's process to stop is a disclosed maintenance interruption; measure its duration and the other workspace's latency, rather than claiming uninterrupted service for the stopped workspace. Test actual operator networks separately and disclose slower links instead of presenting reference-network targets as universal guarantees. Prioritize query plans, request duplication, auth overhead and asset bytes before caches, extra processes or resizing.

## Ordered implementation slices

Each slice requires its documented focused tests and applicable lint/type checks. Slices 1–7 precede public application routing. Slice 8 qualifies the deployed release before operator invitations.

### Implementation progress

| Slice | Status and evidence |
| --- | --- |
| 1 | Implemented: strict protected deployment model/loader, existing-workspace binding validation, `validate-hosted-config` CLI and [route/configuration contract](../../deployment/HOSTED_DEMO_CONFIGURATION.md). Focused configuration/local-transport tests: 54 passed. No hosted server is enabled by this slice. |
| 2 | Implemented foundation: source-owned identity/session ports, real RS256 verification with bounded key discovery/cache, separate Alembic administrative baseline, pending enrollment/explicit approval/rebinding, opaque hashed sessions/CSRF, durable revocation and administrator CLI. Configuration/session/identity/local-transport checks: 77 passed; Ruff lint/format passed. Real Cloudflare qualification remains a deployed acceptance gate, not fixture evidence. |
| 3 | Implemented application composition: explicitly loaded/validated hosted deployment, outer authorization before packaged delivery/domain handlers, exact host/origin/CSRF, runtime UUID fencing, server capabilities, blocked administration/unknown paths, bounded spooled bodies and request rate, session routes and typed errors; hosted background AI recovery/automatic backups disabled. 152 focused hosted/local transport/web-delivery checks passed, followed by the route-wide pre-dispatch guard regression (five composition tests passed); Ruff lint/format passed. No public launcher or deployment is enabled yet. |
| 4 | Implemented: provider-neutral task-local operator scope propagated into threadpool application invocations; Audit records canonical hosted operator UUIDs, including bulk summaries and sensitive Intake reads. Current baseline and retained actor validators updated; original replay attribution unchanged. Startup binds the latest append-order restore marker and revokes sessions/enrollment after restore. 260 focused hosted/Audit/Files/Operator/local transport/web-delivery tests passed, including encrypted attachment/history round-trip and actor rollback/context cleanup. Ruff lint/format passed. |
| 5 | Implemented: typed session contracts/generated clients, private sign-in shell, explicit enrollment/sign-in/logout, expiry/revocation pause, same-identity editor retention, identity/cache teardown, late-response fencing, hosted capability controls and protected downloads. Query-bearing deep links survive sign-in; invalid assertions pause access. Six combined HTTPS packaged-browser tests pass with real RS256 synthetic proofs, secure cookies, SQLite sessions and domain APIs (including evidence bytes/expiry, two sessions, read-only controls and unavailable workspace). Five component tests, ten packaged local-shell tests and seven backend composition checks pass. Frontend lint/format/type and changed-Python Ruff checks pass. [Operator guide](../../operations/HOSTED_DEMO_OPERATOR_GUIDE.md) added. Actual Cloudflare/PIN/remote-network acceptance remains Slice 8. |
| 6 | Implemented: source-owned one-read change marker, fifteen-second jitter/backoff polling with hidden-tab suspension, stale-update feedback and runtime/private-context teardown. Shared drafts require explicit claim/takeover; independent forms stay independent. Five-minute session-bound hashed claims renew at most once a minute while actively edited; a source-owned authority port holds the administrative reservation through the complete recovery mutation, serializing takeover with owning revision/idempotency checks. Restore/revocation invalidate authority. Eleven combined HTTPS browser checks pass, including four sessions across A/B workspaces, copied-cookie/foreign-ID rejection, stale-save/input-preserving review/takeover, hidden polling, runtime teardown, and a lost expense response resolved through its original receipt with one financial effect and changed-payload conflict. All hosted tests plus the focused Operator foundation: 139 passed; six local recovery browser regressions passed. Ruff lint/format and frontend lint/format/type checks pass. |
| 7 | In progress: source controls, [real Linux SQLite FULL](../../qualification/reports/HOSTED_DEMO_LINUX_QUOTA_2026-10-23.md), [systemd/50 MiB upload](../../qualification/reports/HOSTED_DEMO_SYSTEMD_UPLOAD_2026-10-23.md), [actual R2 recovery/fresh-image remount](../../qualification/reports/HOSTED_DEMO_RECOVERY_2026-10-23.md), and [installed wheel/env-file plus approved boot mount](../../qualification/reports/HOSTED_DEMO_INSTALLED_RELEASE_2026-10-23.md) now pass within their recorded scope. The original scratch image is mounted persistently with its app stopped; the recovery image is detached. A/B returned on unchanged private commands/configuration/workspace IDs after the approved reboot. A/B private hosted transition and persistent-volume boot checks now pass; remaining physical fault/reset/rollback and actual hosted-unit boot/client gates still apply. |
| 8 | In progress: exact A/B DNS and provisional authenticated origin routes installed; unauthenticated browser shell/API/receipt probes redirect to matching Cloudflare Access login. Tunnel active but boot-disabled; real PIN/enrollment, authenticated isolation/caching/performance and invitations pending. |

Usage guard: pause implementation after saving a checkpoint if weekly remaining usage is at most 3% or five-hour remaining usage is at most 10%. The preceding source-implementation turn stopped at 10% / 70%. Scratch qualification resumed after reset; the final check for the approved systemd/upload task was **22% five-hour remaining and 58% weekly remaining**. The task stopped at its saved qualification/authority boundary, not the usage threshold. Source controls are based on `39fcc45ce04b3882a57d3380e1508c9cb158b36a`; the spool/error-handling fix, regressions and qualification evidence are saved in the working tree. Resume only when directed and both remaining-usage windows are above the stop thresholds. Remaining deployment inputs and qualification gates apply independently of available usage.

#### Resume checkpoint — October 24, 2026

**Current handoff — synthetic record persistence/foreign-ID acceptance:** operator
reports both independent-session Sign out all devices checks passed; all four saved
flags yes, including other-account availability before provider renewal and explicit
reopening. [Evidence](../../evidence/HOSTED_DEMO_MULTISESSION_LOGOUT_2026-10-24.json).
**Next human step (Mac Terminal):**
`bash "/Users/dcai/Desktop/Property-Management-Data/hosting-qualification/record-isolation-20261024/check-records.sh"`.
Creates one labelled synthetic Task per workspace, verifies saved record after
refresh/on second session, then tests foreign record ID by changing only hostname
and opening under the other identity's valid session. Login form alone is
inconclusive; no foreign record data may show. Stop on ambiguous creation and
leave both Tasks for read-only administrator DB/audit/receipt checks. Expected
titles saved privately; agent has not run wizard. Next verified business backup
must include these new edits. Tell agent **Both Task persistence and foreign-record
checks passed**. File/receipt/shared-edit/cache/performance acceptance still remains;
tunnel active/boot-disabled, no invitations. Usage 27% five-hour / 15% weekly remaining.


**Current handoff — multi-session account-scoped sign-out:** both device logout,
refresh-while-signed-out and fresh-provider-sign-in/explicit Home return passed
per operator and saved flags. [Evidence](../../evidence/HOSTED_DEMO_DEVICE_LOGOUT_2026-10-24.json).
A/B/tunnel active; current eligible sessions A=3, B=2 at snapshot, not all-device
revocation proof. **Next human step (Mac Terminal):**
`bash "/Users/dcai/Desktop/Property-Management-Data/hosting-qualification/multisession-20261024/check-multiple-sessions.sh"`.
Use two independent sessions per account, preferably computer+phone. Sign out all
devices must close both same-account sessions within 60 seconds while the other
account remains usable BEFORE Cloudflare renewal; then explicitly restore sessions.
Two-stage wizard syntax checked, not executed by agent; captures success flags only.
Tell the agent **Both multi-session sign-out checks passed**. Save/discard unsaved
work first. Shared editing/transactions/file/receipt/cache/performance still pending.
Tunnel stays active/boot-disabled. Usage: 32% five-hour / 16% weekly remaining.


**Current handoff — sign-out/refresh/fresh-sign-in acceptance:** operator reports
all four Cloudflare application policy tester decisions match A-only/B-only
allowlists. The OTP non-delivery observations remain supporting evidence, not
explicit denials. See [policy evidence](../../evidence/HOSTED_DEMO_ACCESS_POLICY_2026-10-24.json).
A/B/tunnel active; tunnel boot-disabled; root 25% used, A/B volumes 5% at check.
**Next human step (Mac Terminal):**
`bash "/Users/dcai/Desktop/Property-Management-Data/hosting-qualification/session-20261024/check-sessions.sh"`.
Each assigned browser session signs out, refreshes (no private content), renews
Cloudflare with a fresh PIN, then explicitly returns to Home. Only success flags
captured; syntax checked, not run by agent. Save/discard unsaved work first.
Tell the agent **Both logout and fresh sign-in checks passed** after completion.
Broader client isolation, lifecycle/multiple devices, file/receipt, caching and
quantitative performance gates remain; no invitations or tunnel boot enablement.
Usage at preparation: 35% five-hour / 16% weekly remaining. Older handoffs historical.


**Latest observation — cross-account check inconclusive:** A-only browser opening
B shows B's Access email form. This is not a failed isolation boundary or an
explicit denial. Wizard expected denial too early; corrected instructions now
attempt A's email at B (and vice versa), without switching identity. OTP code-sent
text and missing mail cannot alone prove denial; no pass recorded. User should
answer N at the old running prompt and report whether the wrong email receives
a new target-app PIN. Then establish policy-evaluation evidence if needed.
Reference recovery remains verified; application routes/configuration unchanged.


**Current handoff — cross-account browser acceptance:** post-enrollment encrypted
A/B references (987 bytes each) independently downloaded/decrypted and matched
current approved/pending identity bindings; sanitized reports inspected. Both
Home pages work per operator; all services active. See
[reference evidence](../../evidence/HOSTED_DEMO_POST_ENROLLMENT_REFERENCES_2026-10-24.json).
**Next human step (Mac Terminal):**
`bash "/Users/dcai/Desktop/Property-Management-Data/hosting-qualification/isolation-20261024/check-isolation.sh"`.
Three read-only stages use fresh A-only/B-only browser sessions to verify explicit
cross-account denial, then original Home availability. Login form alone is
inconclusive. Wizard syntax checked, not executed by agent. Tell the agent
**Cross-account checks passed** only after completion. Remaining API/file/receipt,
uninvited identity, session/caching/performance gates still apply; tunnel stays
active/boot-disabled. Usage at this check: 44% five-hour / 18% weekly remaining.
Older human-step paragraphs below are historical.


**Current human step — refresh post-enrollment recovery references:** operator
confirms both intended identities reached their own Home. Real sign-in/pending
approval/session/Home entry now observed by operator; full authenticated
isolation/cache/performance acceptance remains. Updated four-stage reference
wizard installed and syntax checked; current-binding validator passes Ruff.
**Run in VM terminal:** `bash /opt/epm/admin/refresh-admin-references.sh`.
Enter reference passphrase only in private VM prompts. Uses new release and fresh
timestamped outputs, preserving prior encrypted exports; no service interruption.
Tell the agent **Post-enrollment reference recovery verified** after all four stages.
Fresh encrypted upload/independent decryption is not yet claimed. Current tunnel
active/boot-disabled. Usage at preparation: 49% five-hour / 19% weekly remaining.


**Current handoff — both intended operators activated:** user confirmed the
Cloudflare-return fix. Independent checks found exactly one verified pending
identity per demo, matching its configured email. Application administrator
activation succeeded as each owning Unix identity. No business mutation or
administrator-created browser session. See
[enrollment evidence](../../evidence/HOSTED_DEMO_ENROLLMENT_2026-10-24.json).
**Next human step:** click Continue to workspace in both existing browser
sessions and confirm each Home loads. Refresh encrypted administrator references
for the new identity bindings, then finish actual authenticated isolation/cache/
performance acceptance before invitations. Tunnel remains active/boot-disabled;
old checkpoints below describe earlier states. Latest usage before this operation:
55% five-hour / 20% weekly remaining, above both stop thresholds.


**Latest correction — Cloudflare return navigation fixed and deployed:** operator
reported origin rejection immediately after PIN. Narrow public `GET /sign-in`
top-level HTML navigation exception implemented; APIs/files/mutations/foreign
Origin stay blocked. Forty focused tests and three-file Ruff checks passed.
New release `/opt/epm/releases/signin-nav-20261024` installed and verified A then B
through per-instance ExecStart overrides; old qualified release retained. Both
sign-in navigation probes 200/no-store; forbidden-origin/API/file probes 403.
Frontend/schema/dependencies unchanged. See
[fix evidence](../../evidence/HOSTED_DEMO_SIGNIN_NAVIGATION_FIX_2026-10-24.json).
**Next:** user retries the existing enrollment wizard / exact `/sign-in` links;
real browser return and pending enrollment remain unverified. Tunnel active and
boot-disabled; no operator activation or workspace/authorization path changes.


**Current handoff — real email PIN/enrollment required:** latest usage is **73%
five-hour / 22% weekly remaining** (above both guards). physical pressure/recovery
and scratch R2 publication/retention failure checks passed within their documented
scope. Exact A/B CNAMEs now exist; ingress maps A→8001, B→8002, unmatched→404.
Provisional tunnel active, boot-disabled; A/B active and operators inactive.
Unauthenticated browser probes redirect shell/API/receipt paths to the matching
Cloudflare Access login. No invitation or business access granted.
[Route evidence](../../evidence/HOSTED_DEMO_PROVISIONAL_ROUTES_2026-10-24.json),
[publication evidence](../../evidence/HOSTED_DEMO_PUBLICATION_FAULTS_2026-10-24.json).

**Next human step (Mac Terminal):** run
`bash "/Users/dcai/Desktop/Property-Management-Data/hosting-qualification/routes-20261024/request-enrollment.sh"`.
Use each intended identity in its own browser profile/session; enter PINs only in
browser. Click Continue to workspace and stop at administrator-approval message.
Tell the agent both enrollments are pending. Wizard captures only success flags;
it is syntax checked, not executed by agent. Then inspect pending verified identities,
explicitly activate intended bindings, refresh administrator references and finish
actual client/isolation/cache/latency acceptance before invitations. No new reboot
or service boot enablement has occurred. Older checkpoints below are historical.


**Latest checkpoint — physical host-pressure recovery passed (17:09 PDT):** resumed
with 94% five-hour / 26% weekly remaining. Retained test images were remounted
without formatting; a fresh scratch authorization database and fresh post-logout
proof completed the drill. At 40869888 available bytes out of 510873600, writes
returned 503 with zero Tasks/no receipt, reads 200 and logout 204. Removing only
the known filler restored 227225600 available bytes; same-key create/replay and
receipt matched with exactly one Task. Both test mounts/devices detached; A/B
active, tunnel inactive/disabled, no public routes. See
[complete pressure evidence](../../evidence/HOSTED_DEMO_PRESSURE_2026-10-24.json).
Earlier usage stops/partial results below are historical. Continue with remaining
publication/retention failure qualification, then protected public-client gates.


**USAGE STOP — physical host-pressure drill partial:** resumed with adequate usage;
latest check is **8% five-hour / 27% weekly remaining**, crossing the 10% five-hour
guard. Saved and stopped. A/B active; tunnel inactive/disabled. Test mounts/devices
detached and filler removed; no VM-root fill, A/B mutation, fstab or route change.

Created a disposable 512 MiB outer disk containing its own 250 MiB workspace image.
First attempt caught a directory traversal mode error, fixed only on the test
root directory. Retained-image retry passed pressure write rejection (503), reads
(200), logout (204), zero partial Tasks and missing receipt (404), but failed when
reusing a pre-logout proof for recovery sign-in. Full recovery/replay is unverified.
See [partial evidence](../../evidence/HOSTED_DEMO_PRESSURE_PARTIAL_2026-10-24.json).

**Resume next, above both guards:** use retained images without formatting. Preserve
current failure report/log and create a fresh scratch auth DB (previous paths exist).
Corrected child driver is saved privately on Mac at
`/Users/dcai/Desktop/Property-Management-Data/hosting-qualification/pressure-20261024/child.py`;
it mints a fresh synthetic proof after logout before testing recovery. Not deployed
or executed. Controller/retry helpers are saved alongside; do not rerun their
one-time setup blindly. VM code/reports and exact image paths are in the cumulative
log. Finish recovered write, same-key replay/one effect and receipt validation,
then proceed to remaining publication failure/retention and public-client gates.
Older saved stops and next-test plans below are historical.

**USAGE STOP — saved after lifecycle qualification:** latest provider check shows
**8% five-hour remaining / 37% weekly remaining**. The five-hour value crossed the
user's 10% threshold; stop work after this save. Resume only after usage is above
both guards and the operator directs continuation. No background jobs remain.

Lifecycle evidence and Billing inputs are saved below and in the cumulative log.
Final health check: both hosted units active; tunnel inactive/disabled. No A/B
mutation or public route occurred during the scratch drill. Fixture operator is
disabled; retained scratch data/report are under
`/var/lib/epm-scratch/volume/lifecycle-20261024`; root driver at
`/opt/epm/qualification/hosted-transition-20261024/lifecycle-check.py` and protected
config `/etc/epm/hosted-lifecycle-scratch.json`. Do not rerun the one-time prepare
helper over populated fixture paths.

**Resume next:** prepare the bounded disposable outer host-image filesystem / inner
250 MiB scratch workspace pressure drill described below. No new disk/image/mount
for that test exists yet. Verify maintenance writes reject without partial effects,
reads/logout remain possible and removal of only the known test filler restores
admission. Never fill VM root or reuse/format existing images. Remaining real
provider/client, remote failure/retention and public routing/caching/latency gates
still apply. Do not claim public completion or enable routes from this checkpoint.

**Latest checkpoint — isolated lifecycle drill passed:** installed app on new
scratch-only SQLite/quota data passed injected key-fetch failure/recovery,
restore-generation fencing, disablement, prior-cookie denial across app restart,
session/demo expiry and invalid-archive reset preparation with byte-identical
source DB/acknowledged Task retained. No production code, A/B configuration, VM
clock or public route changed. Fixture operator disabled; raw keys/cookies were
memory-only. See [scoped evidence](../../evidence/HOSTED_DEMO_LIFECYCLE_2026-10-24.json).
These are in-process HTTP and explicit key/clock fixtures, not real provider outage.

**Billing inputs:** operator reports Google trial ends January 22, 2027 and $30
budget alerts configured. Manual funding review due by January 15; no automation
created and credit balance not independently verified.

**Next safe physical test:** isolated disposable outer loop filesystem for the
host-image pool plus its own nested 250 MiB workspace image. Pressure only that
outer filesystem; verify real host-maintenance rejection, reads/logout and recovery
without filling VM root or touching existing images. Not yet provisioned or run.
Remote failure/retention, full lost-host, actual provider/client, routing/cache and
latency gates retain their documented limits. Continue only above the usage guards.

**Latest completed checkpoint — hosted-unit boot verified:** latest usage 45%
five-hour / 43% weekly remaining (above both stop thresholds). Approved reboot
completed once. Both hosted units auto-start active/enabled; old units remain
masked/inactive. Exact images remounted with full allocation and required options;
physical storage and schema/config validators pass. Unit/command/locator/deployment/
port hashes unchanged. Sign-in 200, unauthenticated business 401, authorization
inactive/unbound with zero sessions/enrollments. No real active-user session
existed, so later enrolled-session restart acceptance remains separate.
See [hosted boot evidence](../../evidence/HOSTED_DEMO_HOSTED_BOOT_2026-10-24.json).
Tunnel remains inactive/disabled, no public routes or invitations. Previous pending
reboot approvals below are now historical. Continue remaining isolated fault/reset
and real-provider/client acceptance gates; no additional maintenance is implied.

**Latest checkpoint — reference recovery and connector connectivity verified:**
both A/B administrator references passed encrypted R2 publication/full read-back,
independent download/decryption and exact deployment/fresh-enrollment validation.
See [reference evidence](../../evidence/HOSTED_DEMO_REFERENCE_RECOVERY_2026-10-24.json).
Pre-enrollment references must be refreshed after enrollment/config changes.
Temporary 404-only connector check passed `/ready` 200/four connections, then
returned to inactive/disabled with unchanged config; A/B stayed active. No DNS or
application route was added. See
[connector evidence](../../evidence/HOSTED_DEMO_TUNNEL_CONNECTIVITY_2026-10-24.json).

**Next proposed maintenance:** hosted-unit boot preflight passed and saved a
root-private snapshot; checker prepared/lint-validated. Request one reboot to verify
these new hosted units auto-start with unchanged bindings, exact mounted volumes
and inactive authorization, while old private units stay masked. The earlier boot
tested old services, and the last service-switch approval excluded reboot. No new
reboot has occurred; approval pending. Other fault/reset/public acceptance gates
remain. Latest usage: 62% five-hour / 46% weekly remaining. Earlier handoffs below
are historical.

**Current human step — administrator reference custody:** operator completed both
Access policy reviews; exact private confirmation flags validated and saved.
This is operator-reported inspection, with real Cloudflare sign-in/isolation still
pending. Run `bash /opt/epm/admin/protect-admin-references.sh` in the VM to export
separate encrypted administrator references, publish/full-read-back/independently
download from R2 and verify decryption for A then B. Use a separately saved reference
passphrase; no passphrase is sent to the agent or placed in arguments/environment.
The prepared wizard/helpers passed syntax and applicable Python Ruff checks;
execution/results remain pending. Both hosted units active; tunnel inactive/disabled.
These initial references have no approved subjects; refresh after enrollment or
configuration changes. No public route, invitation, activation, reboot or service
interruption is included. Latest usage: 88% five-hour / 50% weekly remaining.
Earlier handoffs below are historical.

**Current manual step:** inspect the existing Cloudflare Access app policies using
`bash /private/tmp/epm-access-review-20261024.zxnrn69c/check-access-policies.sh` on
the Mac. The read-only wizard records exact-host/single-email/PIN-only/eight-hour
configuration confirmations, with no DNS/service mutation or PIN capture. Execution
is pending; browser control is disabled. This does not replace later real-client
identity/isolation acceptance. Both private hosted services are active; no public
route or operator activation exists.

**Latest completed checkpoint — A/B private hosted services active:** approved
sequential transition completed using `qual-c8aab474`, the reviewed template and
new `hosted-local.json` locators. Old units are stopped/masked; new units are
active/enabled with one loopback listener each. Sign-in HTML 200/no-store,
unauthenticated APIs 401/no-store, wrong/cross Host and foreign Origin 403,
protected page 303; both have zero restarts and inactive/unbound authorization
with zero sessions/enrollments. An initial missing-Accept probe caused safe A
fallback; corrected probe/retry passed before B changed. No production code changed.
See [switch evidence](../../evidence/HOSTED_DEMO_PRIVATE_SWITCH_2026-10-24.json).

Tunnel remains inactive/404-only with no DNS routes; no operator activated or
invitation sent. No reboot was included in this transition. Running hosted-unit
boot persistence, remaining fault/reset checks, encrypted admin reference custody
and actual Cloudflare/client acceptance remain gates. Hosted CLI operations must
use `hosted-local.json`; old `config.json` is fallback data only. Earlier approval
requests and old-service-active checkpoints below are historical.

**Latest completed checkpoint — A/B persistent boot qualified:** operator approved
the two mount entries and one reboot; the reviewed fstab is installed. Boot ID
changed; exact A/B images remounted automatically, retain full allocation and
required restrictions, and pass physical storage plus current candidate schema/
config validation. Original private services recovered with identical command,
config and unit hashes; both property reads returned 200. Tunnel still inactive;
no hosted switch or public route occurred. See
[A/B boot evidence](../../evidence/HOSTED_DEMO_AB_BOOT_2026-10-24.json).

**Next proposed action:** install the reviewed pinned hosted unit/port settings
and switch A then B privately, masking each old service to prevent a second writer,
validating sign-in and unauthenticated business rejection, with original-service
fallback on failure. No reboot, public DNS routing, invitations or enrollment
activation included. Reviewed per-instance port candidates are ready (8001/8002); no hosted template
or port files are installed. Service-transition approval is requested and pending;
latest usage is 67% five-hour / 36% weekly remaining. Prior reboot approval
is complete. Older pending-reboot/handoff paragraphs below are historical.

**Latest checkpoint — both fresh recoveries complete:** operator completed B's
strict B-only recovery wizard; independently verified its restored scenario report
and current R2 ledger (no attention/retention issue). Both original private services
remain active. See [B evidence](../../evidence/HOSTED_DEMO_FRESH_B_RECOVERY_2026-10-24.json).
A/B recovery handoffs below are now complete and historical.

**Next maintenance proposal:** review copies under
`/opt/epm/qualification/hosted-transition-20261024` passed systemd and fstab
validation. Candidate fstab adds only the two qualified A/B image entries with
TRIM exclusion; the candidate unit pins the qualified release/new local locator.
Neither is installed. Proposed next action is installing mount entries and one
reboot to qualify remount, then verifying allocation/candidates and original A/B
service health. Reboot approval requested and pending due to brief A/B interruption. Latest usage
after the five-hour reset: 94% five-hour / 41% weekly remaining. No hosted
switch, public routing or invitation is part of this action; those later gates
remain. Exact hashes and expected loop-source warnings are in the operations log.

**Current handoff — A recovery complete; B only remains:** A's independent R2
GET and restoration succeeded. The operational comparison helper was corrected
to recognize both correlated post-snapshot backup creation and retention events;
all 737 shared audit events were identical. Reused A proof passed 105-table /
1432-row comparison and the complete financial/domain scenario verifier. A's
recovery ledger reports no attention/retention issue. Both original services remain
active. See [A recovery evidence](../../evidence/HOSTED_DEMO_FRESH_A_RECOVERY_2026-10-24.json).

Run `bash /opt/epm/admin/protect-fresh-demo-b.sh` in the VM for B's three remaining
stages. Do not repeat the superseded six-stage wizard or A's upload/restore. B's
execution/results remain pending; later mount persistence/boot, service transition,
enrollment and public acceptance gates still apply. Latest usage: 18% five-hour
/ 42% weekly remaining. Older handoffs below are historical.

**Latest checkpoint — fresh greenfield candidates ready:** operator selected fresh
demo data and authorized old-data removal if needed; no deletion or migration was
needed. Fresh A UUID `611d3445-0cce-4858-a10d-b5d5202d601a` and B UUID
`facd33be-7ff7-4d91-bff1-9a3f85af658b` are seeded on their bounded volumes. Both
complete scenario verifiers, current-release configuration checks and real quota
validators passed; administrative stores are initialized but inactive. Candidate
hosted/R2 bindings and private inputs now pin these new UUIDs. Original services
remain active on old workspaces. The old-format restore handoff below is obsolete.

**Current human step:** run `bash /opt/epm/admin/protect-fresh-demos.sh` in the VM.
It creates fresh encrypted backups, publishes/full-read-backs each to R2, downloads
independently, restores to new proof destinations and compares retained rows,
evidence and audit history, then reruns complete financial/domain scenarios.
Requires private passphrase entry; execution/results remain pending. No service
switch, reboot, real ingress, route or invitation occurs. New mounts still need
persistent/boot qualification. Latest usage: 29% five-hour / 44% weekly remaining.
See the cumulative operations log for source hashes, exact checks and limits.

**Current blocker — data decision required:** Stage 1 rejected the old A backup
because its audit actor CHECK constraints do not match the hosted release. Both
A/B live schemas have the confirmed old constraint. Failed extraction cleaned up;
original services remain active, and no candidate A workspace/admin DB/R2 ledger
was created. Do not rerun the prior restore/R2 handoff against these archives.
Operator choice pending: fresh current-format synthetic demos while retaining old
data/backups (recommended under the greenfield rule), or explicit authorization
for a one-time record-preserving conversion exception. No validator weakening,
conversion or reseed has occurred. Other format differences remain unaudited.
Latest usage: 56% five-hour / 48% weekly remaining. Earlier handoffs below are
superseded until this decision is resolved.

**Latest handoff:** A/B backups were reported complete; both original services
are active and private archive metadata/hashes verified. New separate 250 MiB
volumes are mounted with full allocation and required options; original locators
are unchanged. Candidate hosted/local/R2 configurations passed loaders. New mounts
are not yet in fstab or boot-qualified. The draft fourteen-day window ends
2026-11-07T18:51:09Z and must be reviewed before activation. Next, run in the VM:
`bash /opt/epm/admin/restore-publish-before-hosted.sh`. This requires private
passphrase entry to restore candidates, validate identity/quota, initialize fresh
inactive administration and confirm R2 upload/full read-back for A then B.
Execution/results remain pending; no service switch, real ingress, DNS route or
invitation has occurred. Keep original demos unchanged until the transition.
Latest usage: 68% five-hour / 50% weekly remaining. The prior handoffs below are
historical; the cumulative log records exact artifacts and verification limits.

**Current operator handoff:** run `bash /opt/epm/admin/backup-before-hosted.sh` in the VM
terminal. The prepared wizard asks the operator to save passphrases, confirm
sequential A/B interruptions, export and independently validate fresh local
archives, and restart each original service. Execution/results remain pending;
no service interruption or backup creation is claimed. Off-host publication and
hosted switching are separate later steps. This handoff is required for private
passphrase entry; do not send passphrases in chat.

**Tunnel preparation update:** Mac authorization succeeded; locally managed
`epm-demo` tunnel `c29cb930-4166-4105-90a3-32d72fc04f46` was created. The account
certificate stays on the Mac. The verified Linux 2026.10.3 runtime, dedicated
`epm-tunnel` identity, root-protected tunnel credential and stopped service are
installed on the VM. Config/rule/systemd checks passed; ingress is 404-only,
unit inactive/disabled, no DNS routes added. A/B remain active and unchanged.
Support contact is saved privately. A/B backup/maintenance preparation and all
remaining deployment/acceptance gates precede routing. Latest usage: 83% five-hour
/ 52% weekly remaining. See the cumulative operations log for exact paths/checksum.

**Access update:** operator reported setup saved. The private capture passed
format/permission checks, and actual team issuer plus distinct A/B AUD IDs are
saved in the durable private input JSON. Policies/login remain untested.
Mac `cloudflared` 2026.10.3 is installed; no service started. Next human step:
`bash /private/tmp/epm-tunnel-login-20261024.bhqx1hym/authorize-tunnel.sh`.
This performs browser authorization only and keeps the management certificate on
the Mac; execution is pending. No named tunnel, public route or A/B service switch
has occurred. Latest usage: 88% five-hour / 53% weekly remaining. Earlier status
paragraphs below are historical; see the cumulative operations log for sequence.

**Next human step:** the Access-only wizard is prepared at
`/private/tmp/epm-access-20261024.xg40kkxf/setup-access.sh`. It guides Free Zero
Trust onboarding, explicit email PIN setup and exact A/B application/email
policies, then saves actual issuer and distinct AUD values to private sibling
`access.env`. Execution and account verification remain pending. No tunnel route
or service switch is included. Latest usage: 92% five-hour / 54% weekly remaining.

**DNS update, approximately 11:07 PDT:** the operator reported replacing Porkbun's
four nameservers with `bonnie.ns.cloudflare.com` and
`vasilii.ns.cloudflare.com`. The supplied Cloudflare Domains screenshot now shows
**epmdemo.xyz — Active — Free**. Dashboard activation is confirmed by screenshot;
independent public DNS verification has not completed. The wizard's final exit
status remains unreported. Access issuer/audiences and all later deployment gates
remain pending. The initial observations below predate this update. See the
[cumulative operations log](CLOUDFLARE_OPERATIONS.md#october-24-2026).

The operator supplied **`epmdemo.xyz`**. Use the planned exact HTTPS origins
`https://demo-a.epmdemo.xyz` and `https://demo-b.epmdemo.xyz`; the supplied HTTP
apex URL is not an application origin. Initial usage: **98% five-hour remaining,
55% weekly remaining**, above both stop thresholds.

Read-only public DNS checks found Porkbun nameservers and parking responses,
including `pixie.porkbun.com` for both planned subdomains. Cloudflare DNS
activation has not been verified. Browser control is disabled in this session,
and no Cloudflare account connector is available. Manual account steps are being
prepared with the wizard workflow: add the domain on Free, review/import records,
capture the exact assigned nameservers, update Porkbun and verify activation.
Passwords, API tokens and PINs must not be entered in chat or the DNS wizard.
The operator confirmed the DNS sequence and provided both sign-in emails; actual
addresses are saved mode `0600` outside Git in
`/Users/dcai/Desktop/Property-Management-Data/hosted-demo-epmdemo.inputs.json`.
The tested ephemeral wizard is ready at
`/private/tmp/epm-domain-20261024.IIuBS1/setup-domain.sh`; it has not been run.
The assigned Cloudflare nameservers, active-zone confirmation, Access team/issuer
and application audiences are still pending human account steps. Do not invent
those identifiers or publish application routes to get them.

VM checks confirm both private services active, the original scratch volume
mounted on `/dev/loop4` with the required flags, the protected R2 configuration
present, about 23 GiB host disk free, and no installed `cloudflared` executable.
No application service, DNS record, registrar setting, Access application, tunnel,
or public route has been changed during this resume. Remaining Slice 7 gates and
review of the concrete A/B deployment still precede public routing. See today's
[Cloudflare setup record](CLOUDFLARE_OPERATIONS.md#october-24-2026).

#### Previous checkpoint — October 23, 2026

Today's dashboard setup, credential custody, actual R2 operations and unperformed
Cloudflare work are consolidated in the
[Cloudflare operations log](CLOUDFLARE_OPERATIONS.md#october-23-2026).

The operator ran the credential wizard; the real loader verified its root-owned
`0600` scratch configuration and `0700` ledger/staging paths. No keys were displayed
or saved in this repository. The operator then explicitly approved isolated S3
dependencies and the scratch encrypted backup/publication/read-back/restore drill.
[Recovery and fresh-volume evidence](../../qualification/reports/HOSTED_DEMO_RECOVERY_2026-10-23.md) now records
successful actual R2 operations, unchanged original rows/file hashes, encrypted
reference recovery, corrected clean formatting, complete bounded restore,
detach/remount and fresh empty authority. No remote objects were deleted. Both
scratch images were detached at that drill's end; the later approved boot state is
recorded below. Root-only test passphrases
and private artifacts remain on the VM; never copy them into chat or this repository.
The latest usage check reports **15% five-hour remaining and 56% weekly remaining**,
above both stop thresholds; no usage-limit stop was required for this drill.
The operator confirmed they do not yet own a domain. Stable public routing remains
unconfigured. The combined wheel built from `c8aab47415b42dba0dec3545b117143a95ce49ef`
now passes isolated installed-unit/environment-file and HTTP checks at
`/opt/epm/releases/qual-c8aab474`. The operator explicitly approved the scratch-only
fstab entry and VM reboot, including the brief A/B interruption. Boot remount and
installed storage/workspace validation passed; A/B returned with matching command,
configuration and unit hashes and workspace IDs, and both property reads returned
200. Their new PIDs are `572`/`573`. See the
[saved installed/boot evidence](../../qualification/reports/HOSTED_DEMO_INSTALLED_RELEASE_2026-10-23.md).
The original scratch volume remains mounted through fstab, its hosted app is not
running/enabled, and the separate recovery image is detached. No A/B release switch
or public route was authorized. Do not rerun provisioning over retained resources.
Continue Slice 7, not public routing or invitations.

Resume **remaining Slice 7 qualification**, not Slice 8. Original source-backed quota/upload evidence is retained alongside actual R2 recovery, fresh formatting/remount, installed-wheel startup and approved reboot results. The temporary scratch units disappeared at reboot; the original volume now mounts persistently without a running scratch server. Images, accounts, source, reports and immutable files were retained. `serve-hosted` remains loopback-only and requires real validated Linux storage; no synthetic fallback is packaged. A/B remain on the existing private release and require a separate reviewed hosted deployment. Reboot approval did not authorize changing their bindings/releases, exposing routes or inviting operators.

The source quota counts workspace/DB/journals/temp staging inside a fully allocated 250 MiB root-owned ext4 image. Admission reserves three body copies plus write/read headroom; the kernel hard ceiling covers underestimated growth. The adapter requires root-only recovery blocks; the unprivileged Linux drill proves SQLite FULL/rollback/integrity with reserved blocks retained. Synthetic admission tests separately cover host disk warning at 80% and write maintenance at 89%; they do not prove real host-full HTTP behavior. Initial mount deallocation was detected and rejected; re-reserving the original image yielded two passing runs. The corrected clean-format recipe subsequently remained fully allocated through restore and remount without correction, and the original image passed approved boot persistence. Actual R2 archive/reference recovery now passes with administrator-only credentials; bundles cannot restore sessions/leases. Recovery/reset procedures preserve one writer and require fresh authority.

Previous source validation: **266 focused backend tests passed, one Linux-only test skipped**, twelve packaged HTTPS hosted-browser tests and ten local-shell regressions passed; packaging/frontend lint/format/type and 27-file Python Ruff checks passed. After the physical upload discovery, the spool is closed on its last replay chunk, bounded errno-cause translation handles exhausted staging after cleanup, and late failures cannot start a second HTTP response. **225 focused backend tests now pass with one local Linux-only skip** across hosted access, Intake and transport/web delivery; new replay/error/response regressions pass and all four changed Python files pass Ruff lint/format. Frontend code/assets were unchanged in this delta. `git diff --check` passes. The real Linux proofs supplement the local skip; they do not qualify unrelated fault/deployment gates.

Still required: prepare and review A/B hosted deployment, quota mounts and separate recovery bindings with actual domain/Cloudflare/operator inputs, then record remaining physical failure/reset/rollback evidence in the [operations runbook](../../operations/HOSTED_DEMO_OPERATIONS.md). The scratch installed-wheel/unit/environment and boot-mount checks now pass; they do not qualify A/B's future hosted installation. Actual scratch R2 publication/download/restore and encrypted reference recovery pass, but the sparse fixture does not independently qualify populated financial totals or multi-day retention faults. One real Intake/File 50 MiB concurrent-admission/recovery path is evidenced, not universal qualification of every endpoint or physical fault. Do not publish routes or invite operators before these gates. Cloudflare/PIN/caching/latency qualification remains Slice 8. DNS, tunnel and invitations are unchanged; only isolated encrypted recovery objects were added to R2. A/B restarted through the approved reboot with their original release/configuration/workspaces.

### 1. Implement the accepted scope and hosted configuration contract

- Record the administrator-controlled domain, `demo-a`/`demo-b` hostnames, A/B allowed emails and deployment start time. The product owner/current Google Cloud project administrator owns operations, retention, recovery and trial-cost decisions; designate a contact before invitations. Use the R2 backup destination and retention policy below. Actual domain/email/account identifiers must be supplied, not invented.
- Use separate synthetic portfolios, Cloudflare email one-time PIN sign-in, an eight-hour absolute maximum application session, and a fourteen-day renewable demo starting when that operator is enabled. Keep external mail, payments, assistant/model calls and their credentials disabled. These are accepted demo decisions.
- Define an explicit deployment mode and typed, administrator-only configuration. Require public origin, issuer, Access audience, expected workspace ID, identity binding, expiry, and enabled capabilities at startup; reject missing/ambiguous configuration.
- Preserve the existing local transport policy and no-login launch behavior. Do not repurpose a development-origin exception, rewrite Host/Origin to loopback, trust arbitrary forwarded headers, or treat `X-EPM-Local-Client` as authentication.
- Produce a route inventory: public sign-in shell/static assets, authenticated workspace routes, denied host-administration functions, and operator session endpoints. Unknown routes must not become alternate access paths.

Exit evidence: startup/route-policy specifications implementing these accepted decisions and validated deployment inputs. Future launcher/API names are not usable commands until implemented and documented.

### 2. Implement the source-owned hosted identity/session boundary

- Use a `hosted_access` module to own identity bindings, sessions, revocation and demo policy, with domain/application/infrastructure/API separation. Keep Cloudflare/JWT verification in its infrastructure adapter behind application ports; business services must not interpret provider tokens or query its ORM tables directly.
- Bootstrap verifies the signed Access assertion: allowlisted algorithm, signature, issuer, application audience, expiry, and applicable time claims. Use fixed trusted key-discovery endpoints, bounded timeouts, bounded key caching/refresh, and fail closed when verification cannot complete.
- Bind the verified `(issuer, subject)` to the intended operator and workspace. Pre-provision the exact allowed email and workspace; first verified sign-in creates a pending enrollment without business access. The administrator confirms that verified subject before activation. Rebinding requires administrator disablement, revocation and explicit replacement; never silently rebind after an email/account change or authorize from a plain email header.
- Keep one service-owned administrative SQLite store per process at `/var/lib/epm-a/access/hosted-access.sqlite` or `/var/lib/epm-b/access/hosted-access.sqlite`, outside each portable `workspace/` and its bounded volume. The `hosted_access` infrastructure owns its separate SQLAlchemy/Alembic schema and retained validation. Root-owned service-readable configuration under `/etc/epm/` pins deployment/origin/workspace identity; no remote request selects paths or edits this binding. Admin CLI operations use the owning application ports. Protect each store with private owner permissions and the existing service isolation. Keep only the current greenfield schema, without migration-compatibility work.
- Generate 256-bit random opaque session tokens, persist only SHA-256 token hashes, and use `__Host-epm_session` cookies with Secure, HttpOnly, Path `/` and SameSite=Lax. Use a random session-bound CSRF value for exact-origin unsafe operations. Do not store tokens in URLs, browser localStorage, workspace tables, recovery forms, logs, or portable archives.
- On every protected request, require a valid Access assertion plus a valid application session and matching subject/host/workspace, active operator, session generation, and demo expiry. Bound application session expiry by the verified identity grant. Do not transparently renew a session solely because an old Access token remains valid.
- Verify JWTs locally with a bounded trusted-key cache, a fifteen-minute maximum cache age, single-flight refresh and a two-second refresh timeout. Known unexpired cached keys may verify assertions during a provider outage; unknown/expired keys that cannot be refreshed fail closed. On every protected request perform one indexed local session/operator/generation/expiry projection. Do not call remote introspection or update session last-seen for ordinary reads. Fixed session expiry is the earlier of eight hours, the verified grant expiry, and demo expiry.
- Current-device logout immediately revokes that app session, clears its cookie, and prevents that assertion from bootstrapping a replacement session. Other valid app sessions remain usable. All-device logout or disablement invalidates every app session through a durable generation/cutoff check. Bootstrap is an explicit sign-in action, never an automatic retry; reject blocked assertion fingerprints/old issuance times. Restoring administrative data never restores usable sessions.
- For full identity sign-out, use Cloudflare's documented `/cdn-cgi/access/logout` flow and clearly label its broader Access-session effect; it is not a per-application-only logout feature. Require a newly verified eligible assertion after revocation, and test that Access SSO cannot silently bypass the app's bootstrap fence. Permanent disablement also removes the email allow policy and revokes Access sessions administratively. App denial is immediate even when Cloudflare revocation propagation is delayed; no blanket provider-token cache can override it.

Exit evidence: restart-persistent sessions, explicit enrollment, bounded verification, fail-closed outage behavior, and tests for revoked, expired, foreign-subject/audience, and malformed assertions. Fixture tokens alone do not qualify the real identity-provider flow.

### 3. Enforce hosted transport and authorization before disclosure

- Compose hosted identity/authorization before workspace bootstrap or any protected response. Validate the configured HTTPS Host/Origin independently of the listener's loopback transport address. Trust forwarded metadata only through the defined private ingress, not arbitrary caller headers.
- Require a session-bound CSRF token and exact allowed Origin for unsafe requests, including multipart uploads. Specify the narrowly allowed navigation/session-bootstrap cases; missing Origin must not become a CLI-header bypass. Keep browser-generated API calls same-origin.
- Bind the process to exactly one provisioned workspace. Verify the configured workspace ID at startup and fence requests if the workspace/runtime changes unexpectedly. A session is not authority over another process or restored directory.
- Enforce coverage for domain APIs, bootstrap, search, audit, Intake evidence, Files metadata/downloads, saved-form recovery, original receipts, exports, and diagnostics. Reauthorize before returning an idempotent replay result.
- Keep workspace creation/open/relocation, arbitrary local-path import, portable backup/restore, credentials, hosted enrollment, and process administration unavailable to ordinary demo operators. Make these capability decisions on the server as well as in navigation. Review the current Settings and recovery endpoints explicitly.
- Serve live file bytes only through owning, authorized APIs using local storage. Apply the accepted same-origin compression/cache policy above; do not introduce presigned R2 URLs, Pages, cross-origin APIs or a shared private-response cache.
- Apply bounded request/body/upload handling and rate limits at relevant session and file boundaries. Specify typed errors that distinguish unauthenticated, forbidden, expired demo, CSRF, maintenance, and quota conditions without leaking another workspace's existence.

Exit evidence: a route-by-route authorization inventory, no direct-origin/header bypass, no cross-workspace data through errors/cache/receipt keys, and unchanged local-mode security tests.

### 4. Propagate verified actors without changing domain authority

- Pass a provider-neutral authenticated actor context from the request boundary into application operations. Do not let callers supply their own audit identity or infer identity from record ownership/contact fields.
- Extend Audit-owned actor validation/presentation and the current schema/retained-data validators for hosted operators. Retain the actor identity on every consequential domain action and required sensitive read within existing transaction boundaries.
- Preserve original actor attribution on replay; a second caller must not rewrite history. Keep domain mutations, audit events, receipts, and dependent records atomic.
- Preserve stable record/workspace IDs, relationships, financial totals, and append-only history in exports/restores. Portable business history may retain a safe hosted actor reference, but not live sessions, Access grants, signing/connector secrets, or restored authorization.
- After restore, require fresh hosted authorization binding and runtime/session identities. Restoring business history must not reactivate old browser sessions.

Exit evidence: actor-bearing domain and sensitive-read tests, atomic rollback, retained-history validation, and portable restore with authorization remaining revoked/unbound.

### 5. Deliver the complete operator sign-in/session experience

- Operator opens the assigned hostname, completes the Cloudflare email-PIN flow, and enters only the assigned workspace. Use the existing visual system and responsive/keyboard behavior rather than a separate prototype shell.
- Display the workspace label, "Demo — your changes are saved", synthetic-data reminder, expiry, current session state, and sign-out controls. Show truthful disabled/maintenance/expired states and a clear administrator contact path.
- Include current-device logout and all-device logout with feedback. Clear private query caches, recovery/editor context, and session-bound state on logout, subject change, or workspace/runtime change. A different identity must never receive retained private input from the preceding session.
- On authentication expiry, pause writes and preserve only permissible in-memory input for explicit same-identity/workspace reauthentication. Do not automatically resubmit a consequential action or show stale data as current. Restore submitted/unknown attempts through their original keys only after authorization succeeds.
- Hide host-only Settings/actions using server-provided capabilities and explain unavailable functions. Prove the server also rejects direct API calls to those functions.
- Add real-browser acceptance for sign-in, wrong email, logout/revocation, expiry during editing and download, deep links, narrow screens, both themes, keyboard focus, and meaningful error recovery.

Exit evidence: usable end-to-end operator workflows included in this work; no separate future UI backlog is required to finish the demo.

### 6. Qualify multiple devices, concurrency, and recovery

- Audit existing source revision checks and idempotent operation contracts on the exposed workflows. Lost financial responses must reconcile the original key rather than dispatch a new payment/expense. Changed payloads using the same key must conflict.
- Keep edits on stale-revision conflicts for explicit review; background refresh never overwrites a dirty form. Maintain one server writer and bounded database contention.
- Keep saved unfinished forms/source drafts owned by the provisioned operator and workspace. Independent drafts remain independent; shared-draft resume requires an explicit edit-lease claim/takeover plus the source revision. Use a five-minute lease renewed at most once per minute while that editor is visible and active. An expired/replaced lease rejects the former editor's next save without losing input; opening a page never silently takes over. Lease authority is transient hosted state excluded from portable business backups; restored drafts require a fresh claim.
- Preserve revision-safe shared preferences and per-device presentation state. Use the accepted focus/reconnect/time-transition refresh and fifteen-second bounded change poll. Retain independent live attention checks; a revision alone never proves time-sensitive information is current. No row-by-row polling or initial snapshot/cache infrastructure is required.
- Show disconnected/stale/partial states and retain the existing property-local time behavior. No queued offline mutations or automatic command replay after reconnect/sign-in.

Exit evidence: A and B each use at least two simultaneous devices/sessions, with tested stale edits, saved-form takeover, interrupted responses, independent drafts, and no cross-workspace cache/recovery contamination.

### 7. Finish demo controls and recovery operations

- Keep the existing private Unix directories and one writer per workspace. Carry the working per-account `TMPDIR`, systemd supervision, and resource limits into the hosted release; do not reintroduce shared `/tmp` restore-lock permission failures.
- Enforce a 250 MiB whole-workspace budget and the existing 50 MiB per-file ceiling, counting retained database/journal/evidence content and reserved in-flight upload/staging bytes. Reject operator writes exceeding the budget with a typed quota error; do not bypass reservations using concurrent uploads. Define bounded transaction/storage accounting and space for rollback/audit/cleanup before implementation completion, and test boundary growth rather than claiming that a displayed disk measurement enforces a quota. Backup archives live outside this budget but remain included in host disk monitoring. Warn the administrator at 80% host disk use and enter write-maintenance before 90%; reserve cleanup/recovery headroom.
- Implement administrator expiry, disable/re-enable, and reset procedures. Fence requests, drain/stop the owner process, retain a validated recovery point, prepare a replacement, verify it, and switch explicitly. Rotate runtime/session generations and invalidate stale browser continuations. Do not overwrite a live SQLite file.
- Use administrator-run daily application-consistent encrypted backups, retaining seven successful daily recovery points per workspace in a private R2 Standard bucket with distinct deployment/workspace/object names. Keep local live files. Enter encryption passphrases interactively from the administrator's password manager; do not introduce an unqualified headless keyring or claim unattended backups. A dedicated upload credential is held outside application workspaces and inaccessible to the app accounts; the administrator stages only completed encrypted archives for upload. Budget storage/operations using actual sizes; account free-tier allowances are shared and not guaranteed per workspace.
- Validate each archive, verify completed off-host publication and record backup age before pruning; retain the latest verified recovery point if a new attempt fails. Disclose up to twenty-four hours of edits at risk only while daily backup verification is current; otherwise show the actual stale recovery point and require administrator action. Back up the protected deployment configuration and enrollment information separately in an administrator-encrypted recovery bundle, excluding usable sessions, token hashes, edit leases, Access tokens and provider credentials. Host loss/administrative restore requires fresh enrollment or verified rebinding and new sessions.
- The product owner/current project administrator owns daily backup execution, alert checks and recovery for this two-operator trial. Stagger A/B backup maintenance and monitor the other workspace. Review failed/missing daily backups before allowing the demo to continue under an unchanged recovery claim. Unattended operation is a later qualified extension with an explicit headless secret-store design, not a hidden dependency for this manual schedule.
- Record release source, Python patch/dependencies, schema and wheel checksums, operator/workspace bindings, maintenance owner, trial expiry, and backup age. Keep credentials outside the record and business archives.
- Rehearse reboot, restore into a new private destination, operator disablement, expired demo, full disk, auth-key outage, tunnel outage, and failed reset. Define visible maintenance/rollback behavior and who acts on failures.

Exit evidence: current off-host recovery point and successful restore drill, enforced lifecycle/limits, recoverable administrator configuration, and bounded failure behavior. The Mac seed exports alone do not protect subsequent VM edits.

## 8. Cloudflare setup and deployment sequence

These are deployment steps for the accepted design, not instructions to publish `demo-001`. Recheck provider Console instructions when executing. Use the domain/invitation policy above; actual domain, operator emails, Cloudflare account, R2 bucket, credentials and enablement dates must be supplied before deployment. Design acceptance does not provision them.

1. **Prepare domain/DNS.** Select a domain controlled by the administrator, onboard its DNS to Cloudflare using the supported setup, and reserve `demo-a.<domain>` and `demo-b.<domain>`. If changing nameservers, preserve existing DNS/mail records and follow the registrar's process.
2. **Configure Access first.** Create a Cloudflare Zero Trust organization and enable email one-time PIN as the selected identity method. Create two self-hosted Access applications with exact hostnames, explicit per-operator email allow policies, and no broad bypass policy. Do not create an unprotected application route while doing this.
3. **Record trust configuration.** Capture each application's issuer/team domain, audience, and intended email binding in protected host-side configuration. Complete the explicit verified-subject enrollment procedure from Slice 2 before allowing business access. Do not paste tokens or email PINs into Git, chat, logs, or workspace configuration.
4. **Build the qualified hosted release.** Package tested frontend/backend/schema resources from one revision, record checksums and Linux runtime dependencies, and verify installation in a new versioned environment. Retain the compatible private release and current recovery point for rollback.
5. **Prepare the named tunnel.** Install a verified official Linux x86_64 `cloudflared` build, create a locally managed named tunnel, and supervise it under a dedicated Unix identity. Use a root-owned identity-readable tunnel credentials JSON and explicit config/credentials-file paths, not a token in process arguments, shell history or application configuration. Keep the account-management certificate on the administrator device; give the VM only the tunnel-scoped credential. Protect both from `epm-a` and `epm-b`, and validate this credential mode against the selected cloudflared release before startup.
6. **Switch one workspace at a time.** Stop the old local process, start the explicitly configured hosted process under the same owning account, validate its expected identity/workspace and startup health, and prevent any second writer. Keep application listeners private. Direct loopback requests without required hosted credentials must not disclose protected business content.
7. **Add fixed tunnel routes.** Map A's public hostname to only A's authenticated hosted listener and B's to only B's. Configure an unmatched-hostname fallback that returns 404. Use the implemented origin contract without Host/Origin rewriting to bypass local checks.
8. **Verify networking and caching.** Preserve IAP-only SSH and closed public application ports. Permit documented `cloudflared` outbound connections, including port 7844 as required by the chosen transport. Configure private-response cache bypass and verify actual response/cache headers.
9. **Run deployed acceptance before invitations.** Use the intended A/B identities plus an uninvited test identity. Prove API/file/receipt isolation, session/CSRF behavior, reauthentication, multiple devices, current backups, restart/reboot persistence, and tested rollback. Record evidence against the exact release and host configuration. Synthetic tests do not substitute for this step.
10. **Invite and operate.** The administrator sends each operator only their own HTTPS URL, sign-in email instructions, synthetic-data restriction, expiry, recovery expectations, and support contact. Continue backup-age, disk/memory, service-error, and billing checks. No operator needs a Google Cloud account or SSH key.

If acceptance fails, keep invitations/public use blocked and remove or disable the failing route. Revert only through the tested compatible release/data procedure; do not weaken authentication or expose the old local server to make the link work.

Cloudflare primary references, checked October 23, 2026:

- [Named tunnel and private origin connectivity](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/).
- [Validate Access JWTs at the origin](https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/authorization-cookie/validating-json/).
- [Email one-time PIN](https://developers.cloudflare.com/cloudflare-one/integrations/identity-providers/one-time-pin/).
- [Tunnel firewall requirements](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/configure-tunnels/tunnel-with-firewall/).
- [Access session and logout behavior](https://developers.cloudflare.com/cloudflare-one/access-controls/access-settings/session-management/).

Cost/storage/durability references checked for the accepted review recommendations: [E2 shared-core capacity](https://docs.cloud.google.com/compute/docs/general-purpose-machines), [Cloudflare free Access plan](https://www.cloudflare.com/plans/zero-trust-services/), [R2 versioning compatibility](https://developers.cloudflare.com/r2/api/s3/api/), [R2 Standard allowances](https://developers.cloudflare.com/r2/pricing/), and [SQLite synchronous durability](https://www.sqlite.org/pragma.html#pragma_synchronous).

## Validation matrix and release gate

| Area | Required evidence |
| --- | --- |
| Happy paths and UI | Both invited operators sign in on phone/desktop, use their own records/files, save changes, and sign out with clear feedback |
| Invalid combinations | Missing/invalid/expired JWT or session, wrong audience/subject/workspace, wrong Host/Origin, missing CSRF, disabled operator, and expired demo fail before disclosure or mutation |
| Isolation | A cannot read/write B through changed hosts, IDs, source links, downloads, search, bootstrap, audit, recovery, receipts, or cached responses; direct API calls cannot bypass hidden controls |
| Retry and idempotency | Lost financial response resolves original result with one effect; changed payload conflicts; unauthorized users cannot probe original-result keys |
| Concurrency | Stale revisions and stale draft edit leases reject without losing input; independent drafts remain independent; one writer per workspace |
| Transaction rollback | Audit/domain/session setup failures leave no partial business consequence or usable unauthorized session; failed reset has a usable prior state or explicit maintenance state |
| Persistence/schema | Current schema, retained validators, hosted actor contracts, administrative state, and runtime binding agree; restart/reboot preserve valid data without reviving revoked sessions |
| Backup/restore | Complete records/evidence/history restore with stable business IDs/totals; credentials and sessions excluded; fresh authorization/runtime required; off-host recovery drill succeeds |
| Query budgets / N+1 | At most one indexed local auth SELECT per protected request; no routine remote introspection or session-maintenance write; no per-row membership/File reads; owning sensitive-read audit remains intact; auth and domain budgets measured separately |
| Cost and latency | Recorded regional gross cost and trial-expiry action; accepted p95/byte/request/memory/CPU gates pass under four-browser/report/staggered-backup load before resizing or new infrastructure |
| Time freshness / cache | Follow-up and property-local date transitions refresh with no domain writes; hidden tabs stop polling; private responses never enter shared caches; qualified hashed assets retain compression and correct caching |
| Real-client and fault behavior | Four simultaneous operator browser sessions, mobile reflow, login expiry, auth-key/tunnel outage, full disk, failed backup, and recovery produce bounded truthful states |
| Local regression | Local mode still works without Cloudflare, login, hosted secrets, or a network dependency; original loopback/Origin rules retain their checks |

Definition of done: all implementation slices and deployed acceptance pass; both ordinary HTTPS operator workflows are usable; new APIs/contracts and operator/admin documentation are current; applicable Ruff, frontend lint/format/type and focused test checks pass; current recovery and rollback evidence exists. Update the Google Cloud runbook with actual hosted commands only after they exist. No public-link completion can be inferred from DNS resolving, a tunnel being connected, or an HTML page loading.

## Resolved decisions

All design recommendations below were accepted by the product owner on October 23, 2026. They are implementation requirements, not further approval questions. No implementation or public deployment is claimed.

| Decision | Accepted choice |
| --- | --- |
| Scope | Two independent synthetic portfolios, one operator each, multiple devices, explicit hosted mode; local MVP and larger SAAS/SEC feature scope remain distinct |
| Domain and invitations | Reuse an administrator-controlled domain where possible; otherwise one ordinary domain; exact `demo-a`/`demo-b` hostnames and per-operator email policies |
| Identity ownership | `hosted_access` module and provider-neutral application ports; separate per-process protected administrative SQLite; root-owned pinned deployment config |
| Enrollment and sessions | Administrator-approved verified subject enrollment; 256-bit opaque sessions hashed server-side; SameSite=Lax host-only secure cookies; session-bound CSRF; eight-hour absolute maximum bounded by identity/demo expiry |
| Logout and disablement | Immediate local session/generation fences; explicit reauthentication and old-assertion bootstrap denial; accurately labeled broader Cloudflare logout; no automatic consequential retry |
| Drafts and permissions | Independent drafts plus explicit shared-draft claim/takeover and stale-editor rejection; ordinary operators cannot administer host paths, secrets, runtime or backups |
| Demo lifecycle | Fourteen days from enablement, administrator renewal/reset only, no nightly/silent reset; rotate session/runtime authority on reset/restore |
| Storage and quotas | Local live database/evidence; 250 MiB workspace budget, 50 MiB file ceiling, concurrent staging reservations and disk headroom |
| Backups | Manual daily verified encrypted archives to private R2 Standard, seven successful daily points per workspace, independent administrator passphrase custody; no assumed headless keyring |
| Operations owner | Product owner/current Google Cloud project administrator owns backup, recovery, retention and trial-cost review; supply a working contact before invitations |
| Runtime cost | Existing Oregon E2 medium and one named tunnel, eligible free Access, no extra platform services; USD 30/month infrastructure target with recorded actual estimate, expiry decision and measured resizing gate |
| Latency | Local JWT verification and one indexed session read, same-origin asset compression/cache, existing live Home reads and time-aware refresh, numeric p95 targets before extra caching/infrastructure |
| Tunnel credentials | Locally managed named tunnel; dedicated Unix identity, credential JSON/file paths, no runtime account-management certificate or command-line token |
| Rollback | Fence/stop the affected writer, validate a complete recovery point, switch only a tested compatible release/data pair; failed acceptance disables public routing rather than bypassing authorization |

## Required deployment inputs and evidence

Implementation can proceed against the accepted decisions. Deployment still needs actual values/evidence that cannot be chosen from this repository: domain/registrar control, A/B emails and verified subjects, Cloudflare team/audiences and tunnel credential, R2 account/bucket/upload credential, administrator contact and passphrase custody, enablement/expiry dates, regional price estimate/trial-expiry date, and measured acceptance/recovery results. Supply them through protected deployment configuration and the deployment record, not committed secrets or guessed identities. Their absence blocks invitation/public activation, not further design approval.

This document does not provision Cloudflare/R2, change DNS, alter the deployed services, or implement hosted behavior. Implement and qualify the accepted plan before replacing the current private installation.
