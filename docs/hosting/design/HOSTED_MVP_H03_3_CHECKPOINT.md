# H03.3 continuation checkpoint

H03.3 provider adapters are delivered. The remaining setup, composition and live
proof are assigned to later slices in the [ordered implementation plan](HOSTED_MVP_H03_DESIGN.md#ordered-implementation-plan).

## Implemented and verified components

Paths below are within `application/apps/server/app/modules/hosted_access/`.

- `application/managed_provider.py`: safe errors, verified proof projection and
  conservative realm-qualified email matching, preserving local case/dots/plus tags.
- `infrastructure/firebase_tokens.py`: strict RS256 certificate-backed proof checks,
  exact issuer/project/tenant/subject/method/verified email/time, completed TOTP claim,
  separate session-cookie issuer and bounded certificate cache/unknown-key refresh.
- `infrastructure/firebase_rest.py` and `firebase_http_worker.py`: closed endpoints,
  response bounds, redirect refusal, no retries and a parent-enforced five-second
  subprocess deadline including DNS/connect/TLS. Credentials use transient pipes, not
  argv/files. Parent timeout kills/reaps the worker; concurrency is capped at sixteen.
- REST Google/email-code completion, refresh-token discard, source UID checking,
  revocation lookup and verified central server-cookie creation. No arbitrary browser
  password-token login. Email sends require the durable owner and server-derived
  network input; the helper calls `reserve_email`, not browser-selectable hash aliases.
- `infrastructure/provider_configuration.py`: central-only private file loader with
  owner/mode/link/digest/realm/origin/quota checks and a central adapter factory joining
  protected configuration, separate certificate caches, deployment-supplied bearer
  credentials and durable mail admission. Missing credential supplier/rate owner and
  Operator composition reject; composition itself sends no mail.
- `infrastructure/provider_status.py`: bounded per-realm/UID account observations,
  shared across device proofs, no slid freshness on outage. Each proof is independently
  compared with the cached account revocation fence. Concurrent refresh is deduplicated.
- `infrastructure/mail_rate_store.py`: immediate durable admission, rolling destination,
  network and deployment limits, resend cooldown, current/previous protected HMAC keys,
  restart-safe unknown outcomes and original-intent conflicts. Matching replay returns
  unknown, never a second send permit. Cleanup redacts at most 100 expired bucket
  digests after 25 hours; immutable replay tombstones remain because the original
  operation-reference contract has no replay expiry.
- `database/admin-migrations/versions/admin_0001_initial.py` owns the added
  `identity_mail_reservations` table; no runtime DDL. `MAIN_ADMIN_TABLES`, the owning
  dictionary and `RateAdmissionPort.reserve_email` are aligned.

These components are not wired into a public auth composition. No business routes,
workspace admission, Admin principal, operator invitation or source session was enabled.
No new dependency was installed; SDK candidate selections are unchanged.

## Cloud state actually observed

User approved Identity Platform configuration in `project-47b72bb7-ba90-42c9-910`.
The API was enabled and initializeAuth previously returned 200. Do not blindly repeat
initialization. Authentication requests using CLI credentials must send
`X-Goog-User-Project: project-47b72bb7-ba90-42c9-910`; do not mutate global ADC defaults.

The approved configuration PATCH returned 200 and read back:

- authorized domains retain the two default project Firebase hosts and include
  `login.epmdemo.xyz` and `admin.epmdemo.xyz`;
- email enabled; `passwordRequired` omitted/default false (email-link mode);
- MFA ENABLED, TOTP provider ENABLED, adjacentIntervals 5 (not mandatory enrollment).

The user supplied the OAuth Web client JSON. Its project, JavaScript origin and
redirect URI matched the selected setup. Google provider setup returned HTTP 200,
and an independent readback confirmed the provider is enabled with that client.
The JSON contents were kept out of the repository and tool output.

The configured callback `https://login.epmdemo.xyz/__/auth/handler` returned HTTP 525
on November 19. The authorization flow cannot complete at that callback. The
project lists a Firebase browser API key. A real sign-in, email delivery and quota
measurement remain unverified.

The November 19 read-only continuation independently confirmed Google is enabled
with the supplied client, the exact authorized domains, email-link mode and enabled
TOTP. Service Usage returned nine quota metrics; none identifies email-link sends.
The `send_verification_code` metric must not be treated as the email-link allowance.
The billing-status request returned HTTP 429; billing was not reverified this run.
Google's [published email limits](https://docs.cloud.google.com/identity-platform/quotas)
list 25,000 email-link sends/day with billing and 5 without. Those published limits
do not establish this project's effective allowance. H03.11 owns the
application ceiling and project-specific allowance decision.

The [sanitized readback](../qualification/reports/HOSTED_MVP_H03_3_PROVIDER_READBACK.json)
records actual quota values and the billing limitation. The temporary helper
`/tmp/epm-h03-quota-readback.py` obtains CLI credentials internally and emits only
allowlisted summaries. No raw provider configuration/hashConfig/token output is
permitted. Temporary helpers are not installed tooling; inspect before reuse.

## Validation completed

- **146 focused tests passed** in this continuation: `test_provider_boundaries.py`,
  `test_provider_transport.py`, `test_provider_status.py`, `test_firebase_provider.py`,
  `test_mail_rate_store.py` and `test_identity_contracts.py`.
- New transport cases cover redirects/no retries, slow/oversized/malformed responses,
  endpoint rejection before worker launch, malformed worker results, released request
  admission and pipe-only credential delivery.
- New status cases cover 100 same-account device observations sharing one lookup,
  100 distinct accounts, the 128-entry bound, realm isolation, expired device proofs,
  failed refresh without extended freshness and subsequent disabled-account denial.
- Ruff lint and format checks passed on all **four changed Python files**. No lint
  policy changes. `git diff --check` passed.
- Earlier **319 affected schema/private-port/effect tests passed**; these were not
  rerun because this continuation changed no persistence boundary. The focused mail
  tests rerun here include admission concurrency, rollback, schema and restore cases.
- Real bounded HTTPS worker reached Google's public ID and session certificate
  endpoints: 2 and 5 certificates respectively, with nonzero cache lifetimes. This
  establishes connectivity/worker operation only, not token/provider acceptance.
- No full suite, browser auth proof, native host qualification or release promotion.

## Handoff

| Slice | Work transferred |
| --- | --- |
| H03.5 | Central Google and email-link composition, durable mail admission, and attempt and code reservation. |
| H03.6 | Exact HTTPS callback and Firebase helper through the qualified shared-host gateway. H02's closed projection remains authoritative until the replacement passes its gates. |
| H03.11 | Current billing and effective email-link quota evidence, plus protected configuration preparation. |
| H03.12 | Live Google, email delivery and completion, revocation and disabled-account checks, mail and device behavior, and final configuration sealing. |

The callback returned HTTP 525 during the November 19 check and the replacement
`epm-h02-host` was stopped. These observations remain the baseline for H03.6.
Live qualification and configuration sealing remain pending under their assigned slices.

Private qualification inputs:
`/Users/dcai/Desktop/Property-Management-Data/hosted-mvp-qualification/h03/test-inputs.json`.
