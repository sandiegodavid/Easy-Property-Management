# Managed identity contract baseline

[H03 design](../design/HOSTED_MVP_H03_DESIGN.md) · [Admin identity dictionary](../../database/admin-identity.md#h03-flow-state) · [Source access dictionary](../../database/operator-access.md#h03-authentication-state)

H03.1 delivers versioned inputs, private/public contracts, pure state checks and
negative proof fixtures. It does not install sign-in, change provider configuration,
create tables, enable a route or prove provider/browser/native acceptance. The next
schema and service slices implement these contracts under owning transactions.
Implementation baseline: `27c20059d1e81353c1e5c80345b0b31721b38016` on `hosted_mvp`.

## Selected provider and setup inputs

The user confirmed the existing project and exact hostnames for H03.1. The sanitized
[selection manifest](../../../application/deploy/hosted-mvp/identity/selection.json)
is executable input to `IdentitySetup`, with **selected_not_verified** status. It
contains no credential. It must not be passed off as a configured or qualified service.

| Input | Selected value / ownership |
| --- | --- |
| Project / audience | `project-47b72bb7-ba90-42c9-910` |
| Tenant | None; one project realm, not a tenant per Operator |
| Exact issuer | `https://securetoken.google.com/project-47b72bb7-ba90-42c9-910` |
| Retained realm alias | `identity-epmdemo-v1`; immutable. A different realm needs another alias and an audited fenced rebind. |
| Central / Admin origin | `https://login.epmdemo.xyz` / `https://admin.epmdemo.xyz` |
| Google callback | `https://login.epmdemo.xyz/__/auth/handler` |
| Email continuation | `https://login.epmdemo.xyz/auth/email/continue` |
| Operator methods | Google and recognized backend `accounts:signInWithEmailLink` completion; a browser password token is insufficient. |
| Admin method | Google plus completed managed TOTP, explicit protected principal bootstrap; no first-user enrollment. |
| Provider API | Identity Toolkit REST v1; provider endpoints are adapter constants, never a browser-chosen URL. |
| Signing | Ed25519, explicit key IDs; central key delivered only to central identity, each source key only to its source. The protected source registry supplies public verification keys. No private keys in gateway, relay, browser, images, Git or business exports. |
| Fixed grant audiences | `epm:central-identity:v1` for source pairing; `epm:owning-source:v1` for central handoff/status. Exact deployment/workspace/binding/generation/assignment/epoch/target and request hash still required. |
| Rate admission | Central durable atomic buckets, before send, shared across workers/restart. Hash recipient/network keys with the protected HMAC key. Rotate daily, retain the previous key through the full active hourly window, retain buckets 25 hours, clean in bounded batches. |
| Initial mail ceilings | Deployment ceiling of 9 sends per rolling 24 hours against the owner-confirmed project allowance of 10 sends per day. Destination 5/hour, network 20/hour, and resend cooldown of 60 seconds apply independently. Unknown sends count. |

`provider_config_sha256` remains null because provider configuration was not inspected.
`require_verified_setup()` rejects the selected manifest. Before enabling a provider
adapter, its owner must verify exact project/tenant, billing, Google/email-link/TOTP
settings, authorized domains/callbacks, mail configuration/quota, key custody and
protected file delivery, then retain the inspected configuration digest. Setting a
JSON flag is not that verification. No cloud resources or host services changed here.

### Dependency candidates

Artifact pins were obtained from the public package registries without installing them:

- [Firebase JavaScript 13.3.0](https://registry.npmjs.org/firebase/13.3.0): downloaded tarball SHA-256
  `66108d838941865240f697bc5ef4f1ae40f61fe7f47a53bdcaa50c58269bdbd2`;
  its exact `@firebase/auth` dependency is `1.13.10`.
- [Firebase Admin Python 7.8.0](https://pypi.org/pypi/firebase-admin/7.8.0/json): registry wheel SHA-256
  `1cb353371ad14c3233a2ddf86c85b665341123b6c5df73b3cb84e7def45397dc`.

These pin intended top-level inputs, not a resolved dependency closure or Python/browser
compatibility. H03.3/H03.11 must verify artifacts, resolve/hash transitive dependencies,
prove the methods on the actual project and build installed candidates before use.
No Firebase dependency was added to local Operator or installed in this slice.

## Contract ownership and enforcement

| Boundary | Contract and required enforcement |
| --- | --- |
| Setup | `identity_setup.py`: canonical HTTPS origins, exact issuer/audience, immutable realm aliases, separate signing custody, bounded rate inputs and fixed accepted policy. |
| Persisted state | `identity_states.py`: login/continuation/managed/handoff/source-attempt/access/Admin-session shapes. Pure checks also bind related snapshots and renewal admission. These are not DDL or database authorization. |
| Private evidence | `identity_evidence.py`: exact source binding, signed-claim payloads, managed status, safe source receipts and central identity-command states/results. No bearer or arbitrary provider payload is accepted in retained results. |
| Owning calls | `identity_ports.py`, `login_contracts.py`, `source_contracts.py`: central pairs/reserves/acknowledges; the source alone issues/replaces its session. Initialize-disabled receives an admitted Free policy, without seeding it. Apply-policy/rebind remain admitted Admin operations, not user entitlement edits. |
| Browser | `identity_api.py`: start/email/completion requests and safe session/device/Admin projections. No user-selected UID, workspace, issuer, policy or internal fence. Handoff is a redacted transient POST-body secret; challenge proof comes from the observed cookie. |
| Routing | `host_agent/application/auth_routes.py`: exact held GET `/auth/start`, POST `/auth/complete`, GET `/auth/status` only. No HEAD/OPTIONS/prefix/static fallback. Ready requires all five host-evidence fields, current epoch and a non-blocked binding. Closed clears them. |

`ApplyAuthRoutes` pins registered effect/binding/generation and manifest reference/hash;
its child effect identity is stable. Shared Admin/login use protected component manifests
and distinct origins rather than fake Operator rows. The shared route-policy version
seals central GET `/auth/start`, POST `/auth/email-link`, POST `/auth/complete`,
GET/POST `/auth/email/continue` and GET `/__/auth/handler`; Admin GET `/auth/start`,
POST `/auth/complete`, GET `/api/admin/session` and POST `/auth/logout`. H03.6 must
qualify these routes and resolve the separately pinned UI/provider-helper/static
artifact entries before exposing them. MFA proof completes through the Admin callback;
no public bootstrap or bypass route is introduced. Additional provider helper paths
require a reviewed manifest revision and actual qualification, not a prefix fallback. This slice does
not register the new effect in a driver or change the H02 gateway projection.

Cookie names/flags are sealed by `IdentityCookiePolicy`: distinct `__Host-` central,
Admin, Operator and challenge cookies, Secure/HttpOnly/Path=/, no Domain, SameSite=Lax.
Unsafe requests require exact Origin plus session CSRF. Only destination completion
POST has the exact-central-Origin/source-challenge exception. Malformed/duplicate
sensitive headers, CSP/no-store/referrer policy and body limits remain runtime gates.

Private claim models are **unsigned claims**, not authenticated JWTs or executable
grants. Consumers must verify the signature/key registry, exact audience/purpose,
current owning records and fences, fresh deadlines and one-use nonce before committing.
The relay only forwards bounded typed calls; it cannot resolve caller URLs, mint a
session or maintain a second operation ledger. Provider/host/RPC work stays outside
SQLite writers. A shape-valid model or safe projection never substitutes for authority.

### State and receipt vocabulary

Central identity commands retain the schema's closed `claim`, `pair_email_continuation`,
`issue_handoff`, `redeem_handoff`, `renew_session`, `revoke_session`, `revoke_all`,
`recent_auth` outcomes. Existing port verbs `consume_invitation`, `recent_authenticate`
and all-device `revoke_session` map to those owning receipt kinds; validation is a read,
not another infrastructure operation. Infrastructure `operations` remains separate.
Source issuance uses `issue_session`; replacement uses `refresh_session`; device revocation
uses `revoke_session`. Existing control revocation remains `revoke_sessions`.

Source sessions and their receipt/audit/attempt completion commit together, keyed by
UNIQUE handoff. Central redemption is reserved before the call, then acknowledged with
the source receipt. Unknown never returns a success payload. Lost cookie responses keep
the original session/slot/result and require fresh sign-in; receipts never replay tokens.
Revoke-one versus revoke-all selectors are mutually exclusive.

Renewal uses the **observed cookie's** prior row as correlation, fresh managed proof and
new source challenge/handoff. Live predecessors free their own slot atomically even at
32; expired-only predecessors require a free slot. Revoked/stale/disabled/absolute-expired
lineages reject. New cookie/CSRF/session ID, unchanged original remembered deadline,
UNIQUE predecessor and explicit edit-lease reacquisition are owning transaction gates.
A proof may outlive the original lineage; the replacement expiry uses their minimum.

## Focused validation and remaining qualification

Validation: **562 focused tests passed** (441 identity/state/port/proof tests and
121 host/effect-policy regressions). Four Unix-socket fixtures required a permitted
rerun outside the sandbox; all passed. Ruff lint and format checks pass on all
15 changed Python files. No frontend code changed.


| Area | H03.1 evidence / later enforcement |
| --- | --- |
| Happy paths | JSON input/state round trips, exact callbacks, Google/email/Admin proof shapes, source-owned issuance, paired continuation and bounded renewal snapshots. |
| Invalid combinations | Wrong realm/callback/audience/method, missing MFA, swapped scope/epoch/browser/identity, incomplete pairing/readiness, stale deadlines, unknown fields and secret-bearing receipts reject. |
| Retry/idempotency | Canonical request hashes retain the original operation; changed intent conflicts. Typed unknown receipts grant nothing. Durable unique/CAS and lost-response races remain H03.5/H03.7/H03.8 tests. |
| Rollback | No persistence/side effects in this slice. H03.2 tests structural/binding/cleanup rollback; actual identity effects remain owning service work. |
| Persistence/schema | Models match the accepted owning dictionaries. Executable resources, CHECKs/FKs/indexes/read-only reinit and actual cleanup are delivered in [H03.2](identity-persistence.md); no runtime DDL added. |
| Backup/restore | Auth fields never appear in browser/receipt schemas unless explicitly safe. Actual archive exclusion and restore fences remain H03.10/H05 proof, not claimed from DTO tests. |
| Query/bounds | Fixed 32-session cap, 50-row pages, 100-cleanup batch, 128 leases, five-second private calls and five-minute freshness are sealed. Actual indexed reads/deduplication/concurrency remain owning implementation tests. |
| Provider/browser/native | **Unavailable / not executed**. SDK artifact selection and component tests cannot establish delivery, MFA, revocation, cookie behavior, sandbox isolation or a release gate. |

The identity specification is revision 2; previous case IDs remain stable and explicit
renewal-cap/lineage, dependency cleanup and provider-outage cases are added.
`IdentityProofInputs` requires two assignments/four distinct contexts and separates
fixed-clock development evidence from actual-provider deployed evidence.
`IdentityAssertions` rejects a purported pass outside the accepted policy. The later
driver must run generic `validate_report` **and** `validate_identity_report`, pin canonical
input bytes and retain each observation. There is still no identity proof executor;
no test here converts an unavailable report into provider acceptance.
