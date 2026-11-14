# Managed identity and handoff proof — H03

Case authority: [identity_handoff.json](identity_handoff.json); use the
[common runner/report rules](README.md). Component proof and actual managed-provider/
deployed-browser proof remain different reports.

## Setup and invocation

Use two isolated synthetic operator assignments, one separately bootstrapped Admin,
two browser contexts/devices per operator, a fixed test clock for component tests and
actual provider clock for deployed tests. Pin issuer/audience, registered callbacks/
origins, MFA/step-up methods, token lifetime and sanitized cookie/CSRF policy. Dedicated
provider test identities only; private credentials never enter fixture/report JSON.
H03 must qualify Google and email-link managed proof, delivery quotas and private
source-channel authentication; old Cloudflare Access assertions are not substitutes.

```bash
.venv/bin/python -m app.platform.hosted_proofs execute --spec ../docs/hosting/qualification/specifications/identity_handoff.json --inputs /private/proof/inputs.json --output /private/proof/report.json --phase run
```

Currently exits 3. H03's driver must pin real provider/browser launch and cleanup
commands after its detailed design; no identity calls are performed by H01.

## Workload / controls

| Case | Required observation |
| --- | --- |
| `google_email_identity` | Exercise both qualified managed methods; wrong issuer/audience/unverified email/subject, expired/future proof, unavailable discovery and delivery failure deny access. |
| `exact_invitation_claim` | Claim only the invited assignment/issuer/subject; pending readiness gives no business authority. Eligible claim enables without a second manual approval; wrong identity cannot take the assignment. |
| `browser_origin_state_binding` | Swap browser/state/origin/callback and cross-subdomain proofs between the four contexts. Cross-device email completion requires the central-browser-bound continuation, destination round trip and signed new source binding. Race two devices on one email link, inject public continuation/attempt IDs and replace pairing assertions; reject before source session creation. |
| `single_use_handoff` | Redeem one handoff twice, concurrently and after lost response; exactly one bound original result, no second token/session grant. Expired/replayed link is inert. |
| `cross_workspace_role_denial` | Try Operator/Admin/customer roles and foreign workspace IDs/cookies against every private/public boundary. Deny without existence/content disclosure. |
| `host_only_cookie_csrf` | Inspect actual cookie flags/domain and origin/CSRF enforcement; copied cookie to another host, unsafe missing origin and duplicate headers cannot mutate. |
| `mfa_step_up` | Verify protected Admin bootstrap and recent MFA; restore step-up must bind exact current identity/action/point/workspace. Weak/stale/stolen ordinary cookie and restored Admin principal row cannot authorize recovery. |
| `disable_rebind_logout` | Disable during delayed claim/enable, revoke one/all sessions, rebind exact identity and replay old grants across restart. Current source epoch wins; unknown response stays explicit. |
| `no_secret_url_log` | Inspect sanitized URL/history/referrer/log/artifact inventories. No ID/session token or EPM handoff code in URLs; no raw credentials/assertions/action codes in logs, referrers or retained traces. H03 D10 permits only unavoidable initial invitation/provider email-action links, immediately scrubbed with query/referrer/edge capture protected; use fragment invitation capabilities and body-only EPM handoffs. Test with synthetic marker capabilities only. |
| `multi_device_draft_fences` | Two independent devices edit same/different forms. Renew live/expired sessions at the 32-session cap and concurrently with issuance/logout; rotate cookie/CSRF, deny revoked/generation-stale revival and require explicit lease reacquisition. Lost renewal response never reissues its bearer. Preserve input/focus/scroll; no command replay. |
| `local_mode_independent` | Launch supported local Operator without cloud identity/Admin resources; reject production-local hosted roles and development identity adapters. |

## Evidence / cleanup

Retain safe policy/source/tool/image/schema pins, provider method references, browser
traces with capabilities removed, original-operation counts and denial matrices.
Record unavailable MFA/provider as unavailable, never a component pass promoted to
production. Revoke dedicated test grants, retire invitations and owned test resources
only after retaining failures; keep authority/receipt evidence and no real tokens in git.

The [accepted H03 decisions](../../design/HOSTED_MVP_H03_DESIGN.md#resolved-design-decisions)
govern these cases: real Google/email-link provenance, completed Google/TOTP Admin MFA,
explicit renewal under the original thirty-day ceiling, bounded five-minute provider
revocation freshness and source-local/current external fences. A two-week managed
cookie is not a thirty-day proof; a fresh token iat is not recent authentication.
H03.1 updates executable input/report assertions with these rules before execution;
case identifiers remain stable and a Markdown update is not a passing report.

Identity persistence qualification must also exercise dependency-aware cleanup: an
expired attempt referenced by a live remembered lineage or unknown source claim
remains intact under FK RESTRICT; bounded child-first passes reclaim it only after
holds/dependents retire. Unnecessary metadata scrubbing cannot change immutable
identity/request evidence or grant authority. These review refinements do not change
accepted D1–D16 or provide a provider/browser execution result.
