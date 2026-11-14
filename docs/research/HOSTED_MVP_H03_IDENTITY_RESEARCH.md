# H03 managed identity research

Checked November 13, 2026. This note supports H03 design; it does not establish configured provider settings, live acceptance or authorization to deploy. Recommendations below are EPM design inferences from the primary sources, rather than provider guarantees.

## Recommended provider boundary

Retain Google Identity Platform/Firebase Authentication. Use Google sign-in and email links for invited operators; use Google sign-in plus provider-managed TOTP for explicitly bootstrapped Admin identities. Keep EPM role/workspace assignment, host-only sessions, external access fences and application authorization separate from provider authentication. Provider sign-up alone never creates or grants an EPM workspace.

Start with one production identity project and separate development credentials/project. Do not create a provider tenant per property manager: EPM already owns operator/workspace isolation. If separate Admin and Operator identity realms are chosen, pin the tenant in each verifier and issuer alias. Identity Platform tenants have independent user/provider settings; Python supports tenant-aware ID-token verification. Project-level revocation checks do not correctly substitute for tenant-aware user revocation checks. [Identity Platform tenant management](https://docs.cloud.google.com/identity-platform/docs/multi-tenancy-managing-tenants)

## Token verification and identity representation

Firebase ID-token validation checks the signature, project audience, exact issuer, subject and time claims. The issuer is `https://securetoken.google.com/<projectId>`, and the subject is the Firebase UID. Public signing keys have cache lifetimes supplied by their response headers. [Verify ID tokens](https://firebase.google.com/docs/auth/admin/verify-id-tokens)

EPM's existing bounded opaque `REF` character rules exclude `/`. Therefore storing the real issuer URL in an `issuer: REF` column would fail. Recommended resolution: after validating the exact configured JWT issuer/audience and optional tenant, map that verified realm to a protected opaque alias such as `identity-prod-operator-v1`. Store alias plus verified UID; never accept a browser-selected alias or treat matching email text as identity linking. The alias-to-provider mapping is protected configuration, not an editable user preference.

Operator containers should not receive project-wide user-management credentials. Keep provider administrative/revocation operations at the central identity boundary and expose only authenticated, scoped proof/status ports. Public verification keys confer no provider administration authority.

## Admin MFA and recent authentication

Provider-managed TOTP requires Firebase Authentication upgraded to Identity Platform and verified email. Its current supported-first-factor exclusions are phone, anonymous, custom-token and Game Center authentication; Google sign-in is supported. The modular web SDK supports TOTP from version 9.19.1. TOTP enrollment, challenge and recovery must be qualified with the pinned SDK/provider project. [Firebase TOTP](https://firebase.google.com/docs/auth/web/totp-mfa), [Identity Platform TOTP configuration](https://docs.cloud.google.com/identity-platform/docs/admin/enabling-totp-mfa)

The provider's signed ID token exposes `firebase.sign_in_second_factor`; its value identifies the factor used in that authentication. Firebase SDK source also distinguishes `auth_time` from `iat`: refreshing a token updates issuance time while preserving the original authentication time. A factor merely being enrolled, a UI flag or a fresh `iat` does not prove a recent completed MFA authentication. [Parsed token reference](https://firebase.google.com/docs/reference/js/auth.parsedtoken), [Firebase Admin token-verifier source](https://github.com/firebase/firebase-admin-node/blob/main/src/auth/token-verifier.ts)

Recommended Admin gate: explicitly authorized Admin principal, verified Google primary method, completed TOTP claim, valid managed proof and a recent `auth_time` for sensitive operations. Verify the real project's `totp` factor claim during qualification; do not infer MFA from an upstream Google account's undocumented settings. Do not advertise email-link MFA incompatibility: the current official sources do not establish such a restriction.

## Email links need a recognized server-side flow

Web email-link setup requires enabling the Email/Password provider as well as email-link sign-in. Completion requires the recipient email; on another device, ask the user to enter it again. Do not copy that address from redirect parameters. Use production HTTPS and exact authorized domains. `dynamicLinkDomain` is deprecated; the Dynamic Links shutdown primarily affects mobile/Cordova integrations, not a reason to build EPM's web flow on the retired service. [Web email-link authentication](https://firebase.google.com/docs/auth/web/email-link-auth)

The SDK's `EmailAuthCredential` represents both password and email-link methods under `ProviderId.PASSWORD`. Consequently, accepting an ID token because `firebase.sign_in_provider == "password"` does not prove that an email-link flow occurred. Client-side `signInMethod` is also not a trustworthy server assertion. [Firebase email credential source](https://github.com/firebase/firebase-js-sdk/blob/main/packages/auth/src/core/credentials/email.ts)

The official `accounts:signInWithEmailLink` REST endpoint accepts an email/out-of-band code and optional tenant. A successful response returns provider identity credentials; an MFA challenge can instead be represented by a pending credential. Supplying an existing ID token links the method, which is a separate action. [Email-link REST contract](https://docs.cloud.google.com/identity-platform/docs/reference/rest/v1/accounts/signInWithEmailLink)

Recommended EPM flow: bind the pending login to an EPM browser attempt, redeem the email code through the central backend's recognized email-link operation, verify the returned provider identity and then issue an EPM handoff. Do not accept arbitrary browser ID-token submissions as proof of an email-link method. Redact codes and provider credentials from request logging. Do not implicitly perform method linking during login. If the SDK performs completion instead, H03 must qualify a provider-authenticated method attestation mechanism before relying on it; hiding password buttons alone is insufficient.

An Identity Platform blocking function can reject sign-ins before credentials are returned, but adds a required remote function with a seven-second response deadline. The documented event distinguishes sign-in providers; it does not establish that a password event alone distinguishes email links. This should not be introduced as an assumed free solution to the method distinction. [Blocking functions](https://firebase.google.com/docs/auth/extend-with-blocking-functions)

## Remembered sessions, renewal and revocation

Firebase ID tokens last one hour. Refresh credentials support replacement ID tokens and are invalidated by relevant account changes or explicit revocation. Checking provider revocation requires an additional backend request; signature validation alone does not prove that a token remains unrevoked. [Managed user sessions](https://firebase.google.com/docs/auth/admin/manage-sessions)

Firebase server session cookies support five minutes through two weeks. They inherit identity claims and support revocation checks. They are not a thirty-day provider cookie, and Firebase recommends clearing browser authentication state when using its server-cookie pattern. [Server session cookies](https://firebase.google.com/docs/auth/admin/manage-cookies)

Firebase browser persistence has LOCAL, SESSION and in-memory choices. Persistent state is scoped to a single host origin; it does not automatically refresh independent EPM sessions on operator subdomains. [Authentication persistence](https://firebase.google.com/docs/auth/web/auth-state-persistence)

Recommended H03 decision: preserve thirty days as the absolute EPM remembered-session ceiling, while every effective managed proof retains its actual shorter expiry. Qualify an explicit central-login renewal path before claiming the thirty-day experience. A new signed ID token's `iat` cannot satisfy recent-authentication checks. At proof expiry, preserve unfinished input and request authentication/renewal without replaying a business mutation.

Two feasible implementations require a deliberate choice:

| Option | Benefit | Required design and tradeoff |
| --- | --- | --- |
| Central-only provider browser persistence and renewal handoff | Avoids a server refresh-token vault; provider SDK handles browser refresh. | Protect the central origin from script injection; qualify redirect/popup behavior and explicit email-link method provenance. Refresh tokens remain browser-accessible at that origin. Operator portals still receive only scoped EPM cookies. |
| Encrypted central refresh-token custody | Can renew managed credentials without repeated cross-origin browser navigation. | Adds a protected credential store, key custody, deletion, binding and recovery design. It cannot be placed into the current hash-only session tables or portable business data as an incidental implementation detail. |

For Pilot 0, the simpler central-browser/shorter-proof path is preferable if its browser UX and email-link provenance qualify. Otherwise require explicit reauthentication when the provider proof expires rather than silently extending it. A bounded central revocation-status check, for example at most five minutes old, can support local source checks without provider calls on every read. The precise outage/revocation window is an EPM security/availability decision, not an existing Firebase guarantee. EPM source generation and external Admin disable fences still apply immediately through their owning boundaries.

Firebase redirect flows have specific requirements in browsers blocking third-party storage. Choose and qualify the documented same-origin helper/custom-domain or alternative redirect pattern; do not assume an iframe renewal works everywhere. [Redirect best practices](https://firebase.google.com/docs/auth/web/redirect-best-practices)

## Provider setup and qualification gates

The current published email-link sending limits are five per day without billing and 25,000 per day on Blaze, subject to provider abuse controls and change. Link generation and email sending have separate limits. A billing-enabled project, actual configured quotas, sender delivery and representative multi-device flows are launch prerequisites, not inferred from the number of invited operators. [Authentication limits](https://firebase.google.com/docs/auth/limits)

Before H03 activation, retain source-pinned evidence for:

- Exact issuer/project/optional tenant and Google callback/central domain; wrong realm, unverified email, unassigned UID and browser-supplied identity fields reject.
- Google plus TOTP Admin authentication, fresh sensitive-action challenges, recovery after a lost factor, and denied email-link-only Admin sessions.
- Email-link completion on the same device and a different device, expired/replayed codes, unsupported-method attempts and generic browser ID-token injection.
- Source-local and central session revocation, provider revocation propagation, bounded outage behavior and renewal without business-write replay.
- Host-only cookie separation, exact-origin CSRF, browser/storage restrictions, popup blocking, draft preservation and safe support/error text.

These are design inputs. No production provider configuration, cloud mutation or executable application change was made for this note.
