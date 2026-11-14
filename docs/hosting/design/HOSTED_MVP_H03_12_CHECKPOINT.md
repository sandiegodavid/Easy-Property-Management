# H03.12 qualification checkpoint

The [H03.11 handoff](HOSTED_MVP_H03_11_CHECKPOINT.md) holds the candidate
digests and native shared and Operator source registration evidence.
The project owner confirmed a 10-send daily allowance. H03.11 records the
9-send application ceiling and the completed private GCP registration.

## Component evidence

| Area | Result |
| --- | --- |
| Admin bootstrap and sessions | Focused tests exercised revision guards, rollback, protected CLI inputs and writer ownership, disabled-account handling, and rejection when a principal changes during provider exchange. |
| Mail admission | Focused tests exercised destination and network windows, retry identity, cooldown, rollback, and concurrent reservations using synthetic inputs. The H03.11 continuation verifies the 9-send application ceiling. |
| Browser components | Synthetic Admin, central login, and Operator Security tests exercised TOTP enrollment UI, popup behavior, continuation handling, renewal, device revocation, and lost-response recovery. |

The component runs passed 17 Python tests and 16 Playwright tests. The Python
run covered `test_admin_bootstrap.py`, `test_admin_sessions.py`, and
`test_mail_rate_store.py`. Playwright ran `admin-identity.spec.ts`,
`central-identity.spec.ts`, and `managed-security.spec.ts`.

## Native reboot and isolation evidence

The two-phase [native fixture](../../../application/deploy/hosted-mvp/gateway/qualify_identity_reboot.py)
passed on November 20, 2026, in the disposable `epm-h03-12` Lima guest using
synthetic identities. It verified an actual kernel reboot and confirmed that
the runtime projection directory was absent when the guest returned. The
test then restarted the retained synthetic container and invoked the
production ingress bootstrap against the retained protected registration.
Both generated projections matched their pre-reboot bytes. Changing the
registered login origin made the gateway omit the shared reverse proxies and
reduced the tunnel projection to its default 403 rule.

Before and after reboot, real Caddy and nftables admitted the expected Admin
and login routes and rejected unknown hosts, cross-origin paths, an invalid
callback method, forged forwarding headers, a non-HTTPS forwarded scheme, and
connections from an untrusted local UID. The actual Unix relay socket retained
root ownership, the assigned group, and mode `0660`. It admitted one request
from the expected peer. A wrong UID in the permitted group received a denial
before sending a request, a peer outside the group could not open the socket,
and the client rejected an unexpected server UID.

The existing native shared-registration regression also passed on this guest.
It rechecked bridge and firewall rules, TLS and asset pins, exact gateway
routes, and the private central egress proxy's rejection of an unregistered
destination and an unauthorized caller.

| Input or output | Pin |
| --- | --- |
| Host Agent source | `d9a2c27ea351d2e8419dcc90f5051509ce4e394e` |
| Linux and tooling | ARM64 Linux `6.8.0-149-generic`, Docker `29.1.3`, nftables `1.0.9`, Caddy `2.11.9` |
| Caddy binary SHA-256 | `762d7763ed8e303d50bf11fb0274627266907ea8c170720d7d9a6fd0b9bf5c65` |
| Synthetic peer image ID | `sha256:3fe1a0b6c2d6b2ebb572906cdabeca75aeb558c0c17db5ffefbcf8094871c32b` |
| Gateway projection SHA-256 | `94832d8da7a91b43a92929d1e85bef24352a8d44de09439431fdaa1910335a25` |
| Tunnel projection SHA-256 | `280a350845210bdb34d35930483f449401a3c5efe0191b7ddced83c10c7e5828` |

### Automatic startup after reboot

On November 20, 2026, the same disposable ARM64 guest booted with the
generated network policy, ingress projection, Caddy, and egress units and
a retained synthetic inventory. Systemd started all four units without a
manual start or refresh after the kernel boot ID changed. Tmpfiles recreated
the runtime directories under `/run`, and systemd regenerated all three
projections byte-for-byte. The held Operator origin returned HTTP 503 both
before and after reboot. The synthetic startup test generated the tunnel
projection and used no Cloudflare credentials or connection.

| Boot projection | SHA-256 |
| --- | --- |
| Gateway | `12c5ec0c06b42a1a9242b51091dddea92f1c4d611e97124479ac98eaff42ad21` |
| Tunnel | `677f48f324938b5085840d83d34a352cf12cfc61356b97bb64ed140e831d2fa1` |
| Egress | `f1ea27598b27913215fac597f9723d5ca587f0448b1e1e53c35fec4e79583251` |

### Production mount and systemd dependencies

On November 20, 2026, the disposable `epm-h03-12` guest ran the production
disk initializer on a new 50 GiB disk. The initializer mounted ext4 by UUID
at `/srv/epm/data` with `prjquota,nodev,nosuid,noexec` and verified the same
identity on retry. The test installed the production unit definitions with
synthetic inventory and credentials and the production Docker mount dependency.

| Focused case | Observed |
| --- | --- |
| Reboot with disk attached | The mount became active before Docker, network policy, ingress projection, Caddy, egress, tunnel probe, and guardian. All seven started automatically. The gateway, tunnel, and egress projections regenerated byte-for-byte, the synthetic tunnel credential was read-only, and the held Operator origin returned HTTP 503. |
| Boot with disk detached | The UUID device and mount were absent. The mount and all seven dependent service jobs failed without executing their service processes, including on explicit start retries. No projections were created and the underlying mountpoint stayed empty. A fixture-only timeout shortened the device wait. |
| Reattach the original disk and boot | With normal device timing restored, the UUID mount and all seven dependent services came back automatically. The three projection hashes still matched and the held origin still returned HTTP 503. |

Source was `d7b26beff2158d348b5b07c5c099467c317228cb`. Linux, Docker,
nftables, and Caddy pins are listed above. The fixture and sanitized evidence
are retained privately under `hosted-mvp-qualification/H03.12-production-mount`.
The disposable guest's tunnel unit used a credential-consumer probe in place
of Cloudflare.

### GCP disk and closed public tunnel

On November 20, 2026, the retained qualification VM `epm-h02-host`
(instance `6955052781247608210`, `us-west1-b`) booted from its existing disks.
GCP reported the 50 GiB balanced disk `epm-h02-host-data` attached read/write,
with auto-delete disabled. The guest resolved the attached device as
`/dev/sdb` and mounted ext4 at `/srv/epm/data` with the retained UUID
`8d2fd2e0-274b-4535-90d5-da78aa6bd9b6` and
`rw,prjquota,nodev,nosuid,noexec`. Filesystem features and the read-only
kernel project-quota query passed. The mount was active before Docker
and all six hosted service units. This GCP check retained the disk
attachment throughout. The detached-disk result above is from Lima.

The running Cloudflare connector registered four QUIC connections and loaded
a tunnel projection with a single catch-all 403 rule. Over verified TLS,
GETs to `https://h02-check.epmdemo.xyz/` and its `/__/auth/handler`
path both returned HTTP 403 after the connector registered. The reserved
Admin origin and exact login callback still returned HTTP 525. There were
zero running containers. No identity providers, routes, DNS records or email
settings were changed, and no sign-in or email send was attempted. The
installed Host Agent predates the current quota verification helper, so the
check used the filesystem tools and a direct read-only kernel quota query.
GCP reported the VM back in `TERMINATED` after the checks.

### Admin and login deny-only HTTPS verification

Before the DNS change, the Admin and login hostnames fell through to the
proxied `*.epmdemo.xyz` CNAME pointing to `pixie.porkbun.com`. The wildcard
origin returned Cloudflare 525, which indicates a failed edge-to-origin TLS
handshake.
[Cloudflare error 525](https://developers.cloudflare.com/support/troubleshooting/http-status-codes/cloudflare-5xx-errors/error-525/)

Twelve focused gateway, helper, and exact-origin tests passed. They covered
the candidate's shared projection, separation of the Admin shell and login
helper paths, and closure when setup evidence is missing.

On November 20, 2026, exact proxied CNAME records were added for
`admin.epmdemo.xyz` and `login.epmdemo.xyz` to the existing
`epm-h02-qualification` tunnel (`d87e220e-e2a9-48c5-a67b-318255777bce`).
The wildcard and preexisting records were retained. Before the change, the
running connector's projection contained only the catch-all 403 rule and
the host had zero running containers. After the change, the following
public GETs returned HTTP 403 with successful certificate verification:

| Host and path | HTTP response |
| --- | --- |
| `admin.epmdemo.xyz/` | 403 |
| `login.epmdemo.xyz/` | 403 |
| `login.epmdemo.xyz/__/auth/handler` | 403 |

Live sign-in and email sends remained disabled. Successful Admin and
Firebase callback responses still require the verified shared endpoint.
The exact records remain in place. The GCP VM was returned to its prior
`TERMINATED` state, so the 403 proof applies while the connector is running.

### Protected runtime restored

On November 20, 2026, `epm-h03-identity.service` started the pinned shared
listener, central proxy, and relay on `epm-h02-host`. The service holds its
Admin store on the quota-enabled data mount. It mints a 600-second scoped
credential using the attached VM identity, atomically replaces the private
bearer, and refreshes it every 240 seconds after the initial rotation check.
Automatic replacement and the pinned Host Agent's private registration
passed. Five focused gateway and helper tests passed.

The shared-only candidate requires an empty Operator inventory because the
retained H02 inventory predates the Operator authentication columns. The
candidate explicitly excludes the email-link POST route. No live sign-in
or mail send was attempted.

With the shared candidate loaded, a request from the tunnel UID reached the
private Admin listener and returned HTTP 200. Public GETs on the Admin
origin, login entry, and Firebase callback all returned HTTP 403. A
credential-free loopback probe confirmed Cloudflare adds
`X-Forwarded-For` to ordinary requests. The existing gateway rules reject
that header. Automatic approval review rejected changing the live gateway
trust rule without specific approval. The protected runtime is configured
for private operation and enabled at boot. The VM remains running. A final
public check confirmed 403 for the Admin origin, login entry, Firebase
callback, and an empty POST to the email-send route over verified TLS.

### Public activation with email held

On November 20, 2026, the owner approved the Cloudflare-specific forwarding
rule. On the tunnel UID's loopback listener and for the two exact identity
hosts, the gateway requires a single `X-Forwarded-For` value matching
`CF-Connecting-IP`. It strips both headers before proxying. Focused probes
accepted a single match and rejected a mismatch, repeated header fields,
comma-separated lists, and a missing `CF-Connecting-IP`.

The protected runtime is active and enabled at boot. Public HTTPS with
certificate verification returned 200 for Admin `/`, login `/auth/start`,
the exact Firebase `/__/auth/handler` callback, and `/__/auth/handler.js`.
An empty POST to `/auth/email-link` returned 403. The send route remains
excluded, and no email address or sign-in proof was submitted. The VM
remains running to serve the approved routes.

## Deployed Google sign-in and Admin TOTP

The deployed Admin sign-in page loaded on November 21, 2026. A read-only
Identity Platform lookup found one verified, Google-linked record for the
approved qualification account, with zero enrolled factors. With owner
approval, the offline bootstrap command enabled that account's verified
provider subject in the deployed Admin store. The shared identity service
restarted and verified its protected registration. After restart, HTTPS
returned 200 for the Admin page and Firebase callback, and 403 for an empty
email-link POST. The Admin page displayed **Continue with Google**.

The account owner completed Google sign-in and first-time TOTP enrollment
and reported that the Admin dashboard opened. A read-only Identity Platform
lookup confirmed one enrolled TOTP factor. At 6:29 a.m. Pacific on
November 21, 2026, the deployed Admin store recorded a `google_totp`
session for the exact approved provider subject. The session matched the
enabled principal's current generation, was unrevoked and unexpired, and
had fresh provider status at verification. A repeat empty email-link POST
returned HTTP 403.

The account owner signed in again with Google and the enrolled authenticator
and reported that the Admin dashboard opened. The deployed store recorded a
distinct `google_totp` session at 6:32 a.m. Pacific on November 21, 2026.
The new session matched the approved subject and current principal generation,
was unrevoked and unexpired, and had fresh provider status at verification.
Identity Platform still showed one enrolled TOTP factor. An empty email-link
POST again returned HTTP 403.

### Deployed session and candidate baseline

The next qualification check found one current Admin session. The earlier
enrollment session was no longer current, so the two session records alone
did not establish concurrent use. The two-browser check requires sign-in in
an independent browser or profile and a successful refresh in each browser.

The installed Host Agent reverified the protected shared registration on GCP.
The Admin page and exact Firebase callback returned HTTP 200. An anonymous
request to the Admin session endpoint returned HTTP 401, and the empty mail
POST returned HTTP 403.

| GCP qualification input | Verified pin |
| --- | --- |
| Linux, Docker, nftables, Caddy | x86-64 Linux `7.0.0-1017-gcp`, Docker `29.9.3` (build `5457199`), nftables `1.0.9`, Caddy `2.11.9` |
| Caddy binary SHA-256 | `a563843e11cbce39c557bd429ebb787d56f49d51d9bbb3292cd9b36b37a60cdf` |
| Operator and shared Admin images | Both installed digests matched the [H03.11 artifact pins](HOSTED_MVP_H03_11_CHECKPOINT.md#local-artifact-pins). |

Eighteen focused tests passed for Admin sessions, offline principal management,
and mail rate storage. Eight additional Firebase adapter tests passed for
outages, timeouts, revocation, refresh-token discard, and denial without
durable mail admission.

### Two independent Admin browsers

On November 21, 2026, the account owner signed in from two independent
browsers and reported that both Admin dashboards stayed signed in after
refresh. The deployed store confirmed two distinct current Admin sessions
with separate managed provider sessions for the same approved principal.
Their Google/TOTP verification times were 6:32 a.m. and 6:54 a.m. Pacific.
Both matched the current principal generation, were unrevoked and unexpired,
and had fresh provider status at verification. An empty email-link POST
returned HTTP 403.

### Provider revocation and Admin recovery

On November 21, 2026, Identity Platform advanced the approved test
account's token validity cutoff to 6:58:19 a.m. Pacific after confirming both
current Admin sessions predated it. The latest stored provider-status deadline
was 6:59:54 a.m. Pacific. The approved provider subject and its single
enrolled TOTP factor were confirmed again after the update.

After the status window closed, the installed provider adapter denied both
session proofs using the live Identity Platform account status. The account
owner reported that both dashboards returned to sign-in after refresh.

The offline Admin recovery command suspended the approved principal and then
restored the same principal using the inspected revisions. The owning Admin
writer was stopped during both changes. The store recorded both audit events
and advanced the session generation from 1 to 2 at suspension and to 3 at
restoration. Both earlier browser sessions retained generation 1, which
remained ineligible for admission after restoration. The enrolled factor
was retained for the recovery sign-in. Nine focused tests passed for
principal recovery, Admin sessions, and provider revocation.

After restoration at 7:00:48 a.m. Pacific, the account owner completed
Google sign-in with the existing authenticator and reported that one
dashboard opened while the other browser stayed signed out. The deployed
store recorded two distinct generation-3 Google/TOTP sessions for the
approved principal, at 7:03:26 and 7:04:14 a.m. Pacific. Both were unrevoked
and unexpired, with fresh provider status at verification. The store
cannot associate those records with a particular browser. The two original
sessions remained barred by their generation, and an empty email-link POST
returned HTTP 403. The deployed
[Admin account and factor recovery drill](../operations/admin-account-recovery.md)
is complete.

### Email-link qualification prerequisite

The deployed qualification candidate has zero Operator assignments and zero
registered Operator sources in both the Host Agent and central registry.
The send handler first resolves an Operator browser attempt through the
registered source relay and checks the recipient against that assignment.
The approved account's Admin principal cannot supply that Operator context.
The earlier private source registration fixture was removed after its relay
check.

Live delivery and single-use completion need a disposable Operator
assignment bound to the approved address, a registered authentication-only
source, and a mail-send window scoped to that assignment. Business access
must stay closed. The preflight found zero email-link attempts, and the
public send endpoint returned HTTP 403. No link was sent in this run.
Twenty-seven focused central login, handoff, Firebase adapter, and mail rate
tests passed, including one provider call for concurrent code redemption and
no cookie replay after completion.

### Disposable email-link run

The disposable Operator assignment used the approved test address and
separate Admin, access, workspace, and host-inventory fixture stores. The
Host Agent resolved the pinned Operator listener and protected relay. The
public Operator authentication route returned the expected redirect and
its business API returned HTTP 403. The normal Admin deployment stayed
active. The public email-send endpoint returned HTTP 403 throughout the
preflight. The temporary runtime requested one rate-admitted send through
the private listener, and Identity Platform accepted it.

The account owner opened the delivered email and submitted the link. The
browser reported that sign-in could not be completed. The fixture recorded
one sent delivery and one continuation that moved from `verifying` to
`unknown`, with zero managed email sessions and zero Operator sessions.
Operator business access remained disabled. The live result verifies
delivery and receipt of the submission. It leaves successful completion
and single-use replay unverified. The sanitized evidence did not identify
whether the failure was a provider response or subsequent proof validation.

The run ended and removed the disposable runtime, bridge, stores, and
temporary routes. The original gateway and tunnel configurations were
restored. Protected shared registration passed again. Admin returned
HTTP 200, and the disposable Operator entry and public send endpoint
both returned HTTP 403. Three focused central login tests passed for
one-use reservation, concurrent submission, and no cookie replay.

### Live email verification diagnosis

On November 21, 2026, a second disposable run repeated delivery and
captured allowlisted diagnostics from the Identity Platform
`signInWithEmailLink` response. The response included a subject,
`mfaPendingCredential`, and MFA options, with no ID token. Identity Platform
accepted the email link as a first factor and required completion of the
approved Admin test account's enrolled second factor. The Operator email
flow requires a completed ID token from this exchange and has no
second-factor continuation for email sign-in. It denied completion.
[Identity Platform email-link response contract](https://docs.cloud.google.com/identity-platform/docs/reference/rest/v1/accounts/signInWithEmailLink#response-body)

The browser reported that sign-in could not be completed. The fixture
recorded one delivery, one continuation in `unknown`, and zero managed
email sessions or Operator sessions. Business access stayed disabled.
Diagnostics retained only fixed stage labels and field-presence booleans.
Cleanup removed the fixture and restored the original gateway and tunnel
projections. Protected shared registration passed again, Admin returned
HTTP 200, and both the temporary Operator entry and the public email-send
route returned HTTP 403.

### Separate Operator mailbox attempt

With owner approval, the run created a disposable Identity Platform
account for the separate Operator mailbox. It started without a password,
verified email, or enrolled MFA. The held Operator entry and completion
route passed preflight, and the Operator business API returned HTTP 403.
Identity Platform accepted the one approved email send. The public send
endpoint stayed blocked throughout.

The fixture timed out before a browser submission reached it. The
pre-cleanup evidence showed one send attempt, zero continuations, and zero
managed email sessions. The provider mailbox was still unverified. The
runtime removed the Operator fixture and restored the original gateway and
tunnel projections, and the disposable provider account was deleted.
Protected shared registration passed afterward. Admin returned HTTP 200,
and the Operator entry and public email-send route returned HTTP 403.

### Live email-link completion and single use

With the mailbox owner ready, the fresh disposable run requested one
approved email for the separate Operator test account. The browser
submission produced one code reservation, one Identity Platform exchange,
one verified email proof, and one managed email session. The provider
confirmed the mailbox was verified. Repeat submissions returned the
retained outcome or were denied before a second provider exchange. The
store still held one managed email session, and the temporary Operator
held zero workspace sessions with business access disabled.

The mailbox owner's browser screenshots showed the identity-checked screen
and a failed sign-in on reuse. Both address bars showed only the callback
path, with the email-link query absent. The browser evidence is consistent
with the recorded completion and rejection of a repeat submission.

Cleanup deleted the disposable Operator runtime, stores, routes, and
Identity Platform account. Protected shared registration passed after the
original projections were restored. Admin returned HTTP 200. The temporary
Operator entry and the public email-send endpoint returned HTTP 403.

## Remaining qualification

The [November 21 exit review](../qualification/reports/HOSTED_MVP_H03_12_EXIT_REVIEW_2026-11-21.md)
attaches sanitized observations, exact pins, and the remaining case
matrix. The shared deployment passed its current health and route
checks. Acceptance remains open for provider outage and the remaining
native and provider checks. The revision-2 report must identify the
deferred workspace cases as unavailable until their owning slices qualify them.

The tracked selection remains `selected_not_verified`. Selection and
sealing for the H03 identity-only projection follow the remaining H03
gates. Business projection selection follows H04/H05 qualification.

The [Operator continuation](../qualification/reports/HOSTED_MVP_H03_12_EXIT_REVIEW_2026-11-21.md#operator-continuation)
repeated the disposable held-route preflight on GCP with mail disabled.
Business access returned HTTP 403 and the fixture was removed. Positive
deployed workspace handoff and session qualification moves to the
[H04/H05 handoff](mvp/delivery-plan.md#deployed-operator-handoff-and-session-qualification).
Ninety-five focused identity and relay tests passed. A separate focused
launch/schema run passed 25 checks after correcting the test expectation
for an absent access-store file. The report records the provider readback
and the remaining gates.

### Provider outage continuation

A disposable process in the pinned GCP Admin image warmed its own cache
with a live Identity Platform account lookup, then pointed only its own
provider client at an unavailable local proxy. The process confirmed
that the outage preserved the existing five-minute freshness window.
It is waiting for the actual deadline before checking denial, unchanged
expiry, and recovery with a fresh live lookup. Record those results before
closing the provider-outage gate. The probe uses read-only Admin metadata
and a fixture proof, so it measures provider status admission separately
from deployed browser session behavior.

The private probe is `hosted-mvp-qualification/H03.12-email/provider_outage.py`
under `Property-Management-Data`, SHA-256
`030ee8bbb493855d1e885425f5eb89d30f9ad7d708928d40dde16d65285d5bb3`.
Nine focused outage and network tests passed. The identity proof executor
still returns exit 3 with `proof_executor_unavailable`. The weekly
usage threshold was reached before the wall-clock probe completed.

The focused local tests and public deny-only checks are separate evidence.
Email sends remain disabled.
