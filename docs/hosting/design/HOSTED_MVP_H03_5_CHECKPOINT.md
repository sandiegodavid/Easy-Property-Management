# H03.5 central identity checkpoint

H03.5 central implementation and local validation are delivered. The deployed
source-side round trip and handoff depend on H03.6 and H03.7.

## Implemented

- The source-context port requires authenticated owning-source resolution and
  current binding, epoch, revision, registered origin and browser-attempt evidence.
  An optional invitation ID and capability hash come from that verified owner.
- Central attempts use the existing Admin schema, bounded lifetimes, a per-operator
  live-attempt limit and hashed browser challenges. Provider calls run outside writes.
- Google exchange reserves an attempt once. Email exchange reserves a realm-qualified
  action-code hash and fresh browser challenge before provider redemption. Concurrent
  completion performs one provider call. Unknown outcomes survive restart and backup.
- Email send reserves attempt delivery metadata before invoking durable rate admission.
  Unknown sends count toward cooldown. The provider link includes the public attempt
  ID in its fixed continuation URL.
- Managed proof persistence and original-attempt completion/supersession commit
  atomically. Cookie secrets remain outside retained results.
- Explicit recent-MFA Admin issuance/reissue stores invitation hashes and audit records.
  Issuance advances assignment revision, preventing a stale retry from replacing
  the new invitation. Initial capability output is returned once.
- Claims require exact invited email, subject, epoch, revision and central cookie.
  H04 readiness defaults unavailable and leaves the invitation unconsumed.
  The central claim and its command intent commit together. Source effects occur
  afterward through an owning port. Unknown replies reconcile by original operation,
  and successful immutable receipts retain the actual source receipt reference.
- The central HTTP factory implements start, email send, Google completion, email
  continuation and safe original-device status. It enforces exact host/origin,
  bounded JSON, duplicate-field rejection and Secure host-only cookies.
- Email continuation HTML scrubs the action capability before application resources.
  The central UI supports Google, existing TOTP factors, email re-entry, remembered
  choice, status checks and the verified destination link.
- The central UI has its own build target and wheel resource entries.
  Production source-channel and claim adapters must be supplied by their owners.

## Continuation pairing

The destination returns to central with a form POST to `/auth/email/continue`
containing exactly `continuationId` and `assertion`. Central checks the registered
workspace Origin and both central cookies before asking the source owner to verify
the signed assertion and inspect its retained destination attempt. Email-code
redemption still requires a JSON POST from the central Origin.

The central transaction checks the current assignment and access epoch, fresh
destination challenge, retained identity, remembered choice and expiry. It
creates one replacement attempt and marks the continuation paired with an
immutable receipt and an audit record. A matching retry returns the existing
receipt. A changed binding fails closed, and a receipt failure rolls back the
replacement and pairing. The form response shows the setup-only state.

## Later slice dependencies

| Slice | Owning work |
| --- | --- |
| H03.6 | Compose the protected runtime with the authenticated source channel and verify the gateway permits the fixed browser return route. |
| H03.7 | Create the fresh destination attempt and cookie, sign and verify the source assertion through the owning channel, and use the central pairing receipt for one-use handoff issuance and redemption. Qualify the real browser round trip, including separate devices and remembered choice. |
| H04 | Supply positive claim readiness and the Admin invitation delivery workflow. |
| H03.12 | Qualify the deployed flow with real Google and email-link provider evidence. |

## Focused validation

186 focused Python tests passed across central pairing, login, HTTP and identity
state contracts. After adding the atomic audit write, all 11 pairing and central
HTTP tests passed again. Pairing cases include a destination form return through
ASGI, wrong origin and cookies, mismatched assertion, stale epoch, remembered-choice
mismatch, expiry, concurrent retry, changed binding and rollback. The source
verifier was a synthetic test owner. Ruff lint and formatting passed on all four
changed Python files.


Persistence and HTTP cases cover browser mismatch, concurrent email redemption,
provider timeout, original-device supersession, wrong recipient, source epoch change,
readiness refusal, invitation reissue, immutable original claims, unknown source-result
reconciliation and SQLite backup/restore.

63 focused Python tests passed across central login, central HTTP, provider behavior
and durable mail admission. The final revoked-cookie regression was strengthened
to inspect an existing unknown claim, then rerun separately. Ruff lint and format
checks passed on all ten changed Python files.

Eleven focused Playwright tests passed across central and Admin identity. Central
cases use synthetic provider responses and cover Google completion, email send/status,
email re-entry and the missing-source-flow state. The central production build,
frontend lint, formatting and complete type checking have passed.

The source claim and readiness ports have unavailable defaults. No live mail,
operator activation or provider configuration changes were performed.

## Composition entry points

Central HTTP composition lives in `api/central_identity.py`. Supply a
`CentralPairing` instance with a trusted `ContinuationSourcePort` to enable the
source form return. The production private source adapter is a required
composition dependency. Build the central UI with `npm run build:central`
before building the wheel. The earlier wheel verification covered the central
HTML, CSS, JavaScript and login modules.
