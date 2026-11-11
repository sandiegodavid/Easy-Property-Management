# Admin identity, invitations and login handoffs

[Database schema catalog](../DATABASE_SCHEMA.md) · [Shared conventions](overview.md)

Part of the schema master. Proposed hosted tables are design contracts, not claims of implemented schema. Executable definitions belong exclusively under `application/database/`; see [resource ownership](overview.md#required-schema-definition-location).

H02 delivers these tables in the complete main-Admin structural baseline to satisfy
local FK closure. H03 retains all identity/session/invitation population and behavior;
schema creation itself grants no access and creates no principals or sessions.

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
Expired/redemption replay fails closed. Purge after expiry plus bounded diagnostic
retention (24 hours), not after each request.

