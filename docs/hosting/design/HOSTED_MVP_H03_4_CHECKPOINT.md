# H03.4 Admin sign-in checkpoint

H03.4 Admin implementation and local validation are delivered. The Admin admission policy checks signed provider proof
against an enabled principal in the owning SQLite store using the protected realm alias
and exact subject. A recent Google proof can be used to check eligibility for the
factor flow. Session admission requires recent verified TOTP. Existing-session
checks enforce principal generation, revocation and expiry, with a separate
recent-MFA requirement for sensitive operations.

The offline bootstrap command now inspects, provisions, suspends and restores
explicit provider subjects using the protected setup and the owning Admin database.
It verifies private input files, takes the existing writer lock and validates the
schema. Principal changes and audit rows commit atomically. Suspend and restore
require the current revision and advance the session generation. A bootstrap retry
cannot restore a suspended principal. The database binds the protected realm alias
and exact subject after the provider verifier validates the HTTPS issuer.

The session component now exchanges a verified Google/TOTP proof for a provider
session cookie, then writes the managed and Admin records in one transaction.
It persists hashes, returns opaque Admin session and CSRF values to its caller,
and rechecks principal generation after the provider exchange. Expired provider
status refreshes outside the write transaction. Logout validates the session-bound
CSRF value and revokes both records atomically.

The explicit Admin ASGI factory now provides GET /auth/start, POST /auth/complete,
GET /api/admin/session and POST /auth/logout. It checks the exact HTTPS Admin
origin, duplicate sensitive headers, request size and duplicate JSON keys.
Secure host-only HttpOnly SameSite=Lax cookies carry the challenge and session.
Responses use no-store and restrictive framing/content policies. Logout requires
the exact Origin and session CSRF token.

Sign-in starts a durable Admin login attempt with a hashed browser challenge.
Completion checks the browser challenge and proof authentication time, then
reserves the attempt under the SQLite write lock before provider exchange.
Concurrent requests obtain one reservation. A provider failure leaves the attempt
reserved until expiry, so a new sign-in is required. Session persistence and the
attempt's completed state commit together. The factory is available for protected
composition; deployment routing is owned by H03.6.

The Admin UI now includes Google popup sign-in, authenticator setup key and code
entry, TOTP challenge, session expiry information, support contact and sign-out.
Enrollment eligibility is checked against the principal allowlist before generating
a factor. Enrollment finishes with a fresh sign-in to obtain signed MFA evidence.
Firebase 13.3.0 uses in-memory persistence and signs out after proof exchange.
Session status returns the session-bound CSRF token so reload retains sign-out.

The protected installed entry point is
`app.modules.hosted_access.infrastructure.admin_entry`. It validates the owning
schema and protected inputs, composes the provider and mail admission, takes the
stable Admin writer lock during service lifespan, and serves loopback TLS.
`npm run build:admin` builds the separate assets included by the Python wheel.
The [runbook](../operations/admin-account-recovery.md#build-and-start-the-admin-identity-candidate)
documents deployment inputs and startup.

## Current validation

The November 19 continuation verified the following cases.

| Boundary | Completed focused evidence |
| --- | --- |
| Admin admission and persistence | 50 Python tests across admission, bootstrap, session, HTTP, installed-entry composition and provider behavior. Cases include principal suspension, concurrent exchange, rollback and uncertain submission. |
| Browser flow | Seven Playwright tests using synthetic SDK responses cover enrollment, invalid-code retry, choosing among authenticators, expired-attempt restart, popup denial, SDK cleanup failure after commit, reload/sign-out and keyboard access. Narrow light and dark layouts fit a 375-pixel viewport. |
| Protected startup | Actual schema and provider loader, private input permissions, missing assets, configuration digest, credential rotation and bounded malformed-bearer rejection. The stable writer lock is held during the service lifespan and released on shutdown. |
| Local transport | A disposable TLS listener serves the registered Admin host and rejects an unregistered host. Method, forged-host/header and asset restrictions are also covered through the ASGI composition. |
| Packaging | Admin production build and wheel build pass. The wheel contents and installed entry point are verified outside the checkout. |
| Code checks | Frontend lint, repository-wide formatting and complete type checking pass. The previous README formatting issue was corrected. Ruff lint and formatting pass on the two Python files changed during this continuation. |
| Dependencies | The current npm audit reports zero findings after compatible dependency updates and a scoped grpc override. |

The browser tests substitute synthetic Firebase responses. Live qualification
requires deployed routing and the approved Google account.

## Dependency advisory resolution

Firebase stays at 13.3.0. Its Firestore dependency requires grpc-js ~1.9.0,
which prevented npm from selecting the fixed 1.x release. The root package
overrides only Firestore's grpc-js dependency to ^1.13.6. The lockfile resolves
1.14.7. The Admin source imports Firebase app/auth.

The lockfile also resolves zod 4.6.7, typescript-eslint 8.73.0 and its minimatch
11.0.9 dependency through compatible updates. The existing lint rules remain
enabled. Audit returned zero low, moderate, high and critical findings.

The reviewed advisories identify the affected ranges and fixes.

- [grpc-js certificate authorization](https://github.com/advisories/GHSA-m9gg-hp2v-232j)
  affects releases before 1.13.6 and 1.14.0–1.14.4.
- [Zod collection validation](https://github.com/advisories/GHSA-mrhx-c7xc-m3w5)
  affects releases before 4.6.6.
- [minimatch pattern amplification](https://github.com/advisories/GHSA-g3hv-75wg-m249)
  affects releases from 7.0.0 through versions before 11.0.1.

## Deployed qualification handoff

The [ordered implementation plan](HOSTED_MVP_H03_DESIGN.md#ordered-implementation-plan)
assigns the remaining deployed checks to the following slices.

| Owning slice | Required qualification |
| --- | --- |
| H03.6 | Shared gateway, actual Admin/login HTTPS origins, trusted peer forwarding rules and Firebase helper paths. |
| H03.11 | Installed Admin entry point and protected provider credential delivery in the deployed authentication candidate, using the qualified H03.6 routing. |
| H03.12 | Real Google popup, authenticator enrollment/challenge, provider outage and two independent browsers. Execute account/factor recovery with the approved real test account and deployed Admin sessions. Prove rejection of the old session after suspension/restoration and require fresh Google/TOTP sign-in. Publish consolidated live evidence. |

These checks remain open under their assigned slices. H03.4's local implementation,
validation and dependency remediation are complete. The evidence above records the
local tests already performed.
