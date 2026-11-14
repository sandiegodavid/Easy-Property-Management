# H03.8 source session lifecycle

H03.8 implements source authorization, renewal, signed provider status,
recent-authentication challenges and fenced lifecycle commands. Public and
private identity composition share the Operator writer. Authorization reads
the current local session and access fence in one indexed query.

- Google and email renewal retain the exact predecessor chosen by the source
  cookie and its absolute lineage deadline. A live predecessor frees its own
  slot. An expiry-only predecessor needs a free slot. Replacement, original
  receipt and audit commit together.
- The central owner deduplicates account status checks and signs scoped results
  over the bounded provider observation window. The source accepts only
  current, monotonic observations. An outage preserves the previous deadline.
- Recent authentication uses an exact-request challenge, the verified central
  browser and fresh Google proof, with TOTP where the consumer requires it.
  The source consumes the challenge inside the
  sensitive action's transaction. Restore readiness and strong step-up remain
  separate H05 gates.
- Protected claim, enable, disable, rebind and revocation use source revision
  and epoch checks. Claim, enable and rebind need verified evidence from their
  owning proof port. Logout commits locally and reconciles central managed
  sessions against the original source receipt. Unconfirmed central revocation
  remains distinguishable from local revocation. Admin-role sessions are
  independent.
- Authenticated lifecycle control uses the protected source socket even when
  the external route is held or denied and the source is still running.
  External containment status and source receipts are independently observed.

## Local validation

396 focused Python tests passed. Changed-file Ruff lint and formatting and Git
whitespace checks passed.

| Area | Evidence |
| --- | --- |
| Session fences and capacity | Active replacement at cap, expiry-only replacement with a free slot, concurrent issuance, exact predecessor selection, and generation fencing after logout or disable. |
| Provider status and recent auth | Outage after a freshness deadline, monotonic refresh, provider disable, request-hash substitution, one-use consumption and rollback of the consumer action. |
| Receipts and runtime | Lifecycle idempotency, stale epoch rejection, original results after epoch advance, relay dispatch, and local sign-out reconciliation through the owning source. |
| Persistence | Fresh greenfield schema, bounded challenge retention and predecessor dependencies. |

[H03.9](HOSTED_MVP_H03_9_CHECKPOINT.md) delivers the browser security and device workflows. H03.10 owns business
request and draft-lease admission. H03.11 supplies protected deployment
registrations and H03.12 qualifies the deployed network and provider path.
H04/H05 own activation and restore protection evidence.
