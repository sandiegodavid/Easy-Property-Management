# Admin identity, invitations and login handoffs

[Database schema catalog](README.md) · [Shared conventions](overview.md)

Part of the schema master. Proposed hosted tables are design contracts, not claims of implemented schema. Executable definitions belong exclusively under `application/database/`; see [resource ownership](overview.md#required-schema-definition-location).

H02 delivers these tables in the complete main-Admin structural baseline to satisfy
local FK closure. H03 retains all identity/session/invitation population and behavior;
schema creation itself grants no access and creates no principals or sessions.

The [H03 design](../hosting/design/HOSTED_MVP_H03_DESIGN.md) defines the accepted
[flow-state additions below](#h03-flow-state). D1–D16 were accepted November 13,
2026. Executable columns and the H02 baseline remain unchanged until implementation.

In this guide: [`invitations` — H03](#invitations--h03) · [`admin_principals` — H03](#admin_principals--h03) · [`admin_sessions` — H03](#admin_sessions--h03) · [`login_handoffs` — H03 central login](#login_handoffs--h03-central-login)

### `invitations` — H03

| Column | Type | Nullable | Default | Description / column rules |
| --- | --- | --- | --- | --- |
| `invitation_id` | `ID` | No | — | Single-use enrollment invitation identity. PK. |
| `operator_id` | `ID` | No | — | Operator identity; see table scope and relationship rules. FK operators. |
| `token_hash` | `HASH` | No | — | Hash of the invitation secret; plaintext is not retained. UNIQUE. |
| `email_key` | `TEXT` | No | — | Provider-qualified normalized email used for matching. |
| `assignment_revision` | `REV` | No | — | Assignment revision to which this capability is bound. |
| `access_epoch` | `REV` | No | — | Access authority fence; stale operations must not override it. |
| `state` | `TEXT` | No | — | Lifecycle state; see table-specific values and transition rules. (`pending_delivery`, `sent`, `claimed`, `revoked`, `expired`). |
| `expires_at` | `TIME` | No | — | Expiry of this temporary capability/session/lease, not of the operator account. |
| `claimed_at` | `TIME` | Yes | — | Time the invitation was claimed. |
| `claimed_issuer` | `REF` | Yes | — | Verified issuer of the identity that claimed the invitation. |
| `claimed_subject` | `TEXT` | Yes | — | Verified subject that claimed the invitation. |
| `delivery_attempts` | `COUNT` | No | `0` | Number of invitation delivery attempts. |
| `last_delivery_code` | `TEXT` | Yes | — | Safe status/error code from the latest delivery attempt. |
| `created_at` | `TIME` | No | — | Creation time. |
| `revision` | `REV` | No | — | Optimistic concurrency revision. |

Index `(operator_id, state, expires_at)`. At most one unclaimed live invitation per
operator via partial UNIQUE index on pending_delivery/sent states; reissue first
revokes the old row in the same transaction. Claim requires matching verified identity,
current assignment/epoch, unused hash and unexpired link. Record claim identity/time
together. Expiry is invitation expiry, never account expiry. Plaintext invite secret
is transient; after uncertain email delivery reconcile/reissue safely rather than
storing an unencrypted reusable link. H07 adds an encrypted delivery-outbox mechanism
if required for unattended delivery; it does not reuse an expired/claimed secret.

### `admin_principals` — H03

Records which verified identities are authorized to administer the hosted platform.
It grants platform administration, not operator business access or independent
authority to restore a damaged Admin database.

| Column | Type | Nullable | Default | Description / column rules |
| --- | --- | --- | --- | --- |
| `principal_id` | `ID` | No | — | Admin principal identity. PK. |
| `issuer` | `REF` | No | — | Verified identity provider issuer. |
| `subject` | `TEXT` | No | — | Provider subject bound to the identity. |
| `enabled` | `BOOLEAN` | No | `0` | Whether this Admin principal may authenticate. |
| `session_generation` | `REV` | No | — | Generation used to invalidate prior sessions. |
| `revision` | `REV` | No | — | Optimistic concurrency revision. |
| `created_at` | `TIME` | No | — | Creation time. |

UNIQUE `(issuer, subject)`. Initial Admin is inserted from a protected bootstrap input,
not first user to sign in. Recent verified MFA is required, with provider method proof.

### `admin_sessions` — H03

| Column | Type | Nullable | Default | Description / column rules |
| --- | --- | --- | --- | --- |
| `session_hash` | `HASH` | No | — | Hash of the session secret; no raw cookie is stored. PK. |
| `principal_id` | `ID` | No | — | Admin principal identity. FK admin_principals. |
| `csrf_hash` | `HASH` | No | — | Hash of the CSRF secret. |
| `generation` | `REV` | No | — | Session generation bound at issuance. |
| `authenticated_at` | `TIME` | No | — | Time identity authentication was verified. |
| `mfa_verified_at` | `TIME` | No | — | Time MFA proof was verified. |
| `expires_at` | `TIME` | No | — | Expiry of this temporary capability/session/lease, not of the operator account. |
| `last_seen_at` | `TIME` | No | — | Throttled last-observed session activity. |
| `revoked_at` | `TIME` | Yes | — | Explicit session revocation time. |

Indexes `(principal_id, revoked_at, expires_at)` and `(expires_at)`.
Hash-only host-only session cookies; validity checks enabled/generation and actual
expiry. Initial Admin session maximum eight hours, recent authentication within
15 minutes for sensitive confirmations; do not log cookies or MFA claims.

### `login_handoffs` — H03 central login

Bridges central sign-in to the intended operator subdomain using a short-lived,
browser-bound, single-use exchange. It lets the destination issue its own host-only
session without sharing cookies across subdomains.

| Column | Type | Nullable | Default | Description / column rules |
| --- | --- | --- | --- | --- |
| `handoff_id` | `ID` | No | — | Central-login handoff identity. PK. |
| `operator_id` | `ID` | No | — | Operator identity; see table scope and relationship rules. FK operators. |
| `browser_state_hash` | `HASH` | No | — | Hash binding the handoff to the initiating browser state. |
| `nonce_hash` | `HASH` | No | — | Hash of the single-use authentication nonce. UNIQUE. |
| `code_hash` | `HASH` | Yes | — | Hash of the one-time issued handoff code. UNIQUE. |
| `target_origin` | `TEXT` | No | — | Exact registered portal origin receiving the handoff. |
| `issuer` | `REF` | Yes | — | Verified identity provider issuer. |
| `subject` | `TEXT` | Yes | — | Provider subject bound to the identity. |
| `assignment_revision` | `REV` | No | — | Assignment revision to which this capability is bound. |
| `access_epoch` | `REV` | No | — | Access authority fence; stale operations must not override it. |
| `state` | `TEXT` | No | — | Lifecycle state; see table-specific values and transition rules. (`initiated`, `issued`, `redeemed`, `expired`). |
| `expires_at` | `TIME` | No | — | Expiry of this temporary capability/session/lease, not of the operator account. |
| `redeemed_at` | `TIME` | Yes | — | Time the handoff was consumed. |
| `created_at` | `TIME` | No | — | Creation time. |

Indexes `(expires_at)` and `(operator_id, state)`. Fixed registered target origin;
maximum five-minute lifetime. State/nonce bound to the initiating browser; code issued
only after provider verification; redemption records the intended verified subject.
No ID token in redirect URL. Single-use redemption plus source receipt coordinates
session creation: loss of response never releases a second session token from the
same handoff. If completion cannot be recovered safely, require a new login handoff.
Expired/redemption replay fails closed. Twenty-four hours after terminal expiry is
the earliest cleanup time, not an unconditional deletion deadline; apply the
[dependency-aware retention rules](#identity-retention-and-cleanup) below.

## H03 flow state

<a id="proposed-h03-flow-state"></a>

Status: accepted November 13, 2026 under H03 D1–D16; not implemented.
These definitions extend this owning master, not the runtime. Implement the
changes in `application/database/admin-migrations/` as the current greenfield baseline;
no deployed-data migration, runtime DDL or separate identity database. Existing
H02 qualification keeps its original schema/source pins.

All `issuer` columns use a protected verified realm alias under existing REF rules;
actual provider HTTPS issuer/audience/project/tenant validation occurs before mapping.
Never accept an alias from a browser. TIME values remain UTC epoch milliseconds.

### `login_attempts` — H03

Tracks a bounded pre-authentication flow across the destination browser and central
login. The public attempt ID is correlation only, with no authority by itself.

| Column | Type | Nullable | Default | Description / column rules |
| --- | --- | --- | --- | --- |
| `attempt_id` | `ID` | No | — | PK; public non-secret correlation identity. |
| `purpose` | `TEXT` | No | — | CHECK operator_login, admin_login, renewal or recent_auth. |
| `operator_id` | `ID` | Yes | — | FK operators; required for Operator/renewal purposes. |
| `parent_managed_session_id` | `ID` | Yes | — | FK managed_identity_sessions; required for renewal/recent-auth of an existing lineage. |
| `source_attempt_id` | `ID` | Yes | — | Logical source login_attempts identity; no cross-store FK. |
| `source_browser_hash` | `HASH` | Yes | — | Destination browser challenge binding for Operator flows. |
| `central_browser_hash` | `HASH` | No | — | Hash of the central browser challenge; never the raw cookie. |
| `method` | `TEXT` | No | — | CHECK google, email_link or google_totp. |
| `email_key` | `TEXT` | Yes | — | Bounded exact provider-qualified recipient for invitation/email-link checks; not a grant. |
| `target_origin` | `TEXT` | No | — | Exact registered completion origin, never a submitted arbitrary return URL. |
| `return_path` | `TEXT` | No | — | Validated relative UI route <=1,000 characters; no authority/query secrets or API/auth-loop route. |
| `confirmed_request_hash` | `HASH` | Yes | — | Required for a sensitive recent-auth challenge; exact purpose/consumer intent. |
| `delivery_attempts` | `COUNT` | No | `0` | Reserved email-link send attempts, including unknown outcomes. |
| `last_delivery_at` | `TIME` | Yes | — | Latest reserved send time; enforces cooldown across restart. |
| `last_delivery_code` | `TEXT` | Yes | — | Allowlisted sent/unknown/rejected delivery code; no provider payload or link. |
| `state` | `TEXT` | No | — | CHECK pending, verified, completed, failed, superseded or expired. |
| `created_at` | `TIME` | No | — | Attempt creation. |
| `expires_at` | `TIME` | No | — | >created_at, at most fifteen minutes later. |
| `revision` | `REV` | No | — | CAS for completion/expiry. |

Indexes `(state, expires_at, attempt_id)` and `(operator_id, created_at, attempt_id)`.
Operator flows require both source identity/hash; Admin flows cannot target an Operator.
Renewal must retain the prior subject/purpose and absolute remembered deadline. Store
only allowlisted flow metadata; provider tokens, email OOB codes and PKCE/client secrets
are transient/protected provider state, never JSON fields in this table. Expired or
superseded attempts become cleanup candidates after at least 24 hours, but remain
retained while any live lineage, continuation, handoff or command needs them. Use
[dependency-aware cleanup](#identity-retention-and-cleanup), not cascades or FK rewrites.

Rate limiting belongs to the central owning service and its protected ingress. Keep
per-destination resend counters in this record; configured per-network and deployment
send ceilings must remain effective across worker restart and cannot retain raw IPs
or bearer links. H03.1 pins the bounded rate-store adapter and retention/key-rotation
inputs; no H07 delivery outbox or refresh-token vault is implied.

### `email_continuations` — H03

Pairs a recognized email-link result on its completing central browser with a fresh
destination-browser attempt. The continuation ID is public correlation, never a bearer.

| Column | Type | Nullable | Default | Description / column rules |
| --- | --- | --- | --- | --- |
| `continuation_id` | `ID` | No | — | PK; non-secret correlation identity. |
| `original_attempt_id` | `ID` | No | — | UNIQUE FK login_attempts; at most one completing flow reserves an original attempt. |
| `code_hash` | `HASH` | No | — | UNIQUE hash of verified realm alias plus provider action code, reserved before the provider call; no raw code. |
| `central_browser_hash` | `HASH` | No | — | Exact completing browser challenge hash, not the initiating device's old binding. |
| `operator_id` | `ID` | No | — | FK operators; current assignment must still match the original attempt. |
| `target_origin` | `TEXT` | No | — | Exact registered destination pinned from the owning assignment. |
| `access_epoch` | `REV` | No | — | Assignment fence pinned before verification/pairing. |
| `managed_session_id` | `ID` | Yes | — | FK managed_identity_sessions; required after recognized provider verification. |
| `replacement_attempt_id` | `ID` | Yes | — | UNIQUE FK login_attempts; fresh paired central attempt. |
| `source_attempt_id` | `ID` | Yes | — | Logical new destination attempt; no cross-store FK. |
| `source_binding_hash` | `HASH` | Yes | — | Verified signed source-binding assertion hash; not a caller-selected browser hash. |
| `handoff_id` | `ID` | Yes | — | UNIQUE FK login_handoffs once issued for this pairing. |
| `state` | `TEXT` | No | — | CHECK verifying, unknown, verified, paired, completed, rejected or expired. |
| `created_at` | `TIME` | No | — | Reservation time, before provider code redemption. |
| `expires_at` | `TIME` | No | — | >created_at, <=created_at+five minutes and <=original attempt expiry; after verification also <=managed proof expiry. |
| `revision` | `REV` | No | — | CAS for one browser/pairing/result. |

Indexes `(state, expires_at, continuation_id)` and `(operator_id, created_at, continuation_id)`.
Verified/paired/completed require managed_session_id; paired/completed require all
three pairing fields. Completed additionally requires handoff_id; a paired row may
retain that ID while handoff completion is still pending. Pairing fields and verified
identity cannot be retargeted after pairing. Preserve a known pairing when outcome
is uncertain; uncertainty is not permission to replace the browser or scope.

Reserve original attempt/code hash/completing browser atomically, perform provider
work outside the transaction, then commit verified proof and original-attempt
supersession together. A failed/unknown provider result grants nothing and must not
be retried as a fresh code reservation on another device. Request a new link/attempt
when safe result recovery is impossible. Duplicate completion resumes only with the
same central cookie and valid managed proof, and returns no previously emitted bearer.
No raw code, provider cookie, source assertion or handoff token is stored in this row.

The central return POST must present a source-generated assertion bound to the new
destination cookie/attempt, this continuation and current target/fences. Verify its
signature and original source record via authenticated ports before CAS-pairing.
A public continuation/attempt ID or a body-supplied hash cannot establish that binding.

### `managed_identity_sessions` — H03

Retains provenance and revocation observations for a central managed sign-in without
storing its reusable provider cookie or refresh credential. Operator sessions reference
this authority through signed/scoped observations, never a cross-store database read.

| Column | Type | Nullable | Default | Description / column rules |
| --- | --- | --- | --- | --- |
| `managed_session_id` | `ID` | No | — | PK; internal proof/session identity, not a bearer. |
| `cookie_hash` | `HASH` | No | — | UNIQUE fingerprint of the central-only provider session cookie. |
| `purpose` | `TEXT` | No | — | CHECK operator or admin; one purpose cannot grant the other. |
| `operator_id` | `ID` | Yes | — | FK operators; non-null exactly for Operator-purpose sessions. |
| `issuer` | `REF` | No | — | Protected alias of the already verified provider realm. |
| `subject` | `TEXT` | No | — | Verified provider UID, bounded as existing subject columns. |
| `email_key` | `TEXT` | No | — | Verified email snapshot; never overrides bound subject. |
| `method` | `TEXT` | No | — | CHECK google, email_link or google_totp; derived from a recognized verified flow. |
| `authenticated_at` | `TIME` | No | — | Verified provider auth_time, not token iat. |
| `mfa_verified_at` | `TIME` | Yes | — | Required for Admin; completed signed second-factor evidence. |
| `provider_valid_until` | `TIME` | No | — | Actual managed cookie expiry, at most fourteen days from issue. |
| `remembered_until` | `TIME` | No | — | Original absolute EPM lineage deadline, at most thirty days; renewal cannot slide it. |
| `revocation_checked_at` | `TIME` | No | — | Successful provider revocation/status observation time. |
| `revocation_valid_until` | `TIME` | No | — | <=checked_at+five minutes and <=provider_valid_until; no timeout extension. |
| `issued_at` | `TIME` | No | — | Central issuance time. |
| `revoked_at` | `TIME` | Yes | — | Explicit revocation. |
| `revision` | `REV` | No | — | Observation/revocation fence. |

Indexes `(issuer, subject, purpose, revoked_at)` and `(provider_valid_until, managed_session_id)`.
The provider cookie exists only in a Secure/HttpOnly host-only central browser cookie;
no raw cookie/token/refresh credential is retained here or in receipts. Central batches
or deduplicates current status checks by verified realm/subject. Renewed proofs retain
the original remembered deadline; new sign-in after that deadline starts a new lineage.
Admin EPM sessions remain capped at eight hours regardless of provider cookie expiry.
After expiry/revocation retain only bounded diagnostic/audit evidence; do not archive
usable cookies in control manifests. H05 defines independent Admin recovery authority.

### `identity_commands` — H03

Owns original claim/handoff/renewal/revocation outcomes so cross-store interruptions
do not silently retry identity effects or misuse the infrastructure operations enum.

| Column | Type | Nullable | Default | Description / column rules |
| --- | --- | --- | --- | --- |
| `operation_id` | `ID` | No | — | PK; original identity operation. |
| `kind` | `TEXT` | No | — | Closed H03 action vocabulary: claim, pair_email_continuation, issue_handoff, redeem_handoff, renew_session, revoke_session, revoke_all or recent_auth. |
| `idempotency_key` | `TEXT` | No | — | Shared bounded key; UNIQUE(kind, idempotency_key). |
| `request_hash` | `HASH` | No | — | Immutable canonical consequential request hash. |
| `operator_id` | `ID` | Yes | — | FK operators for workspace actions; null for Admin-only identity work. |
| `managed_session_id` | `ID` | No | — | FK managed_identity_sessions; verified initiating identity. |
| `attempt_id` | `ID` | Yes | — | FK login_attempts for browser-bound actions. |
| `access_epoch` | `REV` | Yes | — | Required for Operator effects; no stale claim/renewal. |
| `state` | `TEXT` | No | — | CHECK pending, unknown, succeeded or rejected. |
| `result_json` | `TEXT` | Yes | — | Typed <=16 KiB original safe result/identity references; no bearer or provider credential. |
| `source_receipt_ref` | `REF` | Yes | — | Logical reference to source result, never a cross-store FK. |
| `created_at` | `TIME` | No | — | Original creation time. |
| `updated_at` | `TIME` | No | — | >=created_at. |
| `revision` | `REV` | No | — | CAS; terminal intent/result immutable. |

Indexes `(state, updated_at, operation_id)` and `(operator_id, created_at, operation_id)`.
Claim scope/epoch, originating identity, key and request hash are immutable. Require
typed result for succeeded; unknown retains identity/reservation but grants no new
authority. Audit uses an allowlisted identity-command reference in safe facts; do not
put this ID into `admin_audit.operation_id`, whose FK owns infrastructure operations.
Receipt retention must outlive referenced live sessions/capabilities and all unresolved
effects; TTL cleanup cannot delete the evidence needed for safe reconciliation.

### H03 additions to existing Admin identity tables

The existing table definitions above remain their column authority; these are accepted
additional fields, not a second copy of those definitions.

| Table / new column | Type | Nullable | Default | Description / column rules |
| --- | --- | --- | --- | --- |
| `admin_sessions.managed_session_id` | `ID` | No | — | FK managed_identity_sessions, purpose=admin checked by owning service. |
| `admin_sessions.managed_valid_until` | `TIME` | No | — | <=provider proof expiry; session expiry cannot exceed it. |
| `admin_sessions.revocation_valid_until` | `TIME` | No | — | Provider status freshness deadline; request admission cannot exceed it. |
| `login_handoffs.attempt_id` | `ID` | No | — | FK login_attempts; exact browser/destination binding. |
| `login_handoffs.managed_session_id` | `ID` | No | — | FK managed_identity_sessions; exact identity/method and proof deadlines. |
| `login_handoffs.identity_operation_id` | `ID` | No | — | FK identity_commands; original handoff issuance intent. |

Extend handoff lifecycle with `redeeming` and a bounded `source_receipt_ref: REF` nullable
column. `redeeming` reserves the single exchange before the external source call;
`redeemed` requires the matching source receipt. Retain the existing five-minute
capability lifetime; an expired reservation may be reconciled read-only, never issue
a new bearer. A matching retry reports the original safe result, not a second cookie.
H03.1 must finalize corresponding CHECKs/state invariants and update typed proof
contracts together before changing the executable baseline.

## Identity retention and cleanup

Use ON DELETE RESTRICT for local identity-flow FKs, including attempt, managed-session,
continuation, command and handoff references. No cascading deletion, SET NULL or
reference rewrite to make TTL cleanup succeed. Expiry removes authentication authority;
it does not remove the evidence needed to reconcile an original result.

- Twenty-four hours after terminal expiry/completion/supersession is a minimum
  diagnostic hold. Retain rows longer while referenced, while a linked session or
  remembered lineage may remain live (up to its original thirty-day deadline), or
  while any provider/source/claim result remains pending/unknown.
- Cross-store references are logical. Use owning bounded observations or the recorded
  maximum validity deadline to establish that a source result no longer needs a row;
  unavailable/unknown reconciliation cannot be treated as absence. Retain unresolved
  results until explicit reconciliation, even after thirty days; alert on aging holds.
- Minimize unnecessary personal metadata separately after expiry. Only redact mutable
  display/routing/recipient metadata proven unnecessary for remaining dependents.
  Keep IDs, hashes, immutable request/result facts, scope/fences and required identity
  evidence unchanged. Defer scrubbing when a live/unknown result still needs a field;
  never invalidate its semantic hash or fabricate a replacement reference.
- A bounded cleanup pass (at most 100 candidates) first removes eligible terminal
  email continuations, then eligible handoffs, then terminal identity commands with
  no retained handoff references, then unreferenced terminal login attempts, then
  managed identity sessions with no remaining attempts/commands/handoffs/Admin
  sessions. Admin-session cleanup follows its own expiry/retention first. Repeat
  passes as dependents disappear; FK rejection retains the row, not the whole worker.
- Recheck eligibility and NOT EXISTS dependencies in the same short deletion
  transaction. Index reverse references (`login_attempts.parent_managed_session_id`,
  identity_commands attempt/session, handoff attempt/session/identity operation,
  and continuation original/replacement attempt/session/handoff) to avoid N+1 or
  unbounded scans. Never perform provider/source RPC while holding that transaction.

Tests must run repeated cleanup passes with a live thirty-day lineage, unknown source
claim, expired continuation and terminal handoff. Required evidence survives; after
all holds/dependents retire, eligible rows are eventually reclaimed without cascades.

