# H03.12 exit review

Reviewed November 21, 2026. **Acceptance remains open.** This review records
sanitized observations for the shared qualification deployment and the disposable
Operator runs. The [checkpoint](../../design/HOSTED_MVP_H03_12_CHECKPOINT.md)
holds the detailed run results. The
[H03.12 design](../../design/HOSTED_MVP_H03_DESIGN.md#validation-matrix) and
[revision-2 proof cases](../specifications/identity_handoff.md) define the
remaining coverage.

## Deployed and native observations

| Gate | Evidence and scope |
| --- | --- |
| Admin and login routes | The installed Host Agent reverified the live shared registration. Public HTTPS returned 200 for Admin and the exact Firebase callback, 401 for the anonymous Admin session request, and 403 for the former fixture entry. The live tunnel listed only Admin and login as named hosts. |
| Approved email allowance | The owner confirmed 10 provider sends per day. The tracked application limit is 9 per rolling 24 hours. The current gateway omits the send route and the public POST without a recipient returned 403. |
| Real Google and TOTP | Deployed Admin enrollment, subsequent TOTP challenge, two concurrent browser sessions, provider revocation after the status deadline, and recovery with fresh Google/TOTP passed. |
| Real email-link proof | A disposable auth-only Operator completed identity verification. The provider verified the mailbox. The run recorded one exchange and one managed session. Repeat submissions produced no additional exchange or session. The fixture held zero workspace sessions and was removed. |
| Native startup and isolation | The Lima runs recorded projection regeneration after reboot, automatic startup, absent-disk denial, Unix socket ownership and UID checks, forwarding checks, route and method denials, and scoped egress. The GCP private registration runs confirmed both relay directions used their owning listeners. |

## Exit gaps

| Proof cases or design gate | Evidence still required |
| --- | --- |
| `google_email_identity`, `exact_invitation_claim`, `browser_origin_state_binding`, `single_use_handoff` | Real provider proof and central email code reuse are recorded. H04/H05 own the deployed eligible claim, cross-device pairing, and workspace handoff redemption, including lost-response behavior. |
| `cross_workspace_role_denial`, `host_only_cookie_csrf`, `mfa_step_up`, `disable_rebind_logout` | H03 retains Admin recovery, held route and identity-only browser checks. H04/H05 own the deployed workspace-session, cross-workspace, Operator-to-Admin, and recovery step-up cases. |
| `no_secret_url_log` | A sanitized check across the complete browser, referrer, gateway and app boundaries using synthetic markers. The browser screenshots show the email callback query was scrubbed and the focused adapter test verifies refresh-token discard. |
| `multi_device_draft_fences`, `renewal_cap_and_lineage` | Focused lifecycle and draft tests cover component behavior. H04/H05 own deployed device, renewal, cap and draft validation with separate workspace sessions. |
| `local_mode_independent`, `identity_dependency_cleanup` | Record local launch, hosted-role denial and dependency cleanup with their exact candidate and input pins in the identity proof report. |
| `provider_outage_deadlines` | Deployed provider outage after the freshness deadline. Live account revocation and focused simulated outage tests cover different failure paths. |
| Native and provider exit checks | Attach exact-candidate evidence for dual-stack isolation and stream containment at the identity boundary, Google OAuth Testing status and the approved test-user allowlist, and the cooldown observed through the deployed mail flow. |
| Proof report and design validation matrix | The revision-2 CLI describes and validates report structure. Its execution path still returns unavailable. The exit review has no report with all required case observations and both generic and identity-specific validation. Attach the validation matrix coverage spanning rollback, schema and backup boundaries, and read budgets, with evidence tied to the corresponding candidate. |

The [H04/H05 handoff](../../design/mvp/delivery-plan.md#deployed-operator-handoff-and-session-qualification)
owns deployed cases requiring eligible workspace access or recovery protection.
Record them as unavailable in H03 evidence and retain the original proof cases.

## Operator continuation

The pinned GCP candidates repeated the held Operator preflight with a
disposable synthetic binding, isolated stores, and no mail send. The held
authentication entry redirected through the expected source flow, the email
callback loaded, and the Operator business API returned HTTP 403. Cleanup
removed the fixture and restored the prior projection. Admin returned HTTP
200, and both the former Operator entry and the public send POST returned
HTTP 403.

The installed shared entry uses
[`AwaitingWorkspaceReadiness`](../../../../application/apps/server/app/modules/hosted_access/infrastructure/shared_identity_entry.py)
and leaves invitation processing unconfigured. The
[central handoff](../../../../application/apps/server/app/modules/hosted_access/infrastructure/central_handoffs.py)
returns before issuing a grant when that readiness check fails. The
[installed Operator entry](../../../../application/apps/server/app/modules/hosted_access/infrastructure/operator_entry.py)
provides the identity listener and leaves managed business inputs unset.
The earlier live email run therefore proves managed identity and one code
exchange under the held boundary. Positive workspace handoff, redemption,
and deployed workspace-session evidence require the owning readiness and
business composition.

| Continuation check | Observed |
| --- | --- |
| Component handoff, session, persistence and relays | 95 focused tests passed across handoff, central login, identity persistence, Firebase provider, relay, and shared registration. The tests exercised the owning stores with test readiness, session renewal and replacement, acknowledgement recovery, outage timing, read budgets, and cleanup. |
| Launch, rollback, backup and query-budget subset | 25 focused checks passed with loopback sockets enabled. The Operator launch test now expects the same `FileNotFoundError` as the Admin launch test for an absent store, and verifies that no store is created and the writer lock is released. Ruff lint and format checks passed for the changed test. |
| Provider configuration readback | Google and TOTP are enabled, email-link mode is configured, and both expected Admin and login domains are authorized. The API response covers provider configuration. OAuth consent publishing status and the test-user allowlist still require independent evidence. |

## Exact pins

The following digests identify reviewed artifacts and observations. The
running projection digests identify the observed qualification configuration.

| Item | SHA-256 |
| --- | --- |
| Revision-2 identity specification | `c1fd8ba2fe519e26f03173f3111335ee8b79de31dc409be0c50c6d53596f1cd8` |
| Tracked provider selection | `3cc4989f771be17ff498fbc013a69d7c307b0281781b6dfd23c471d5e55c6111` |
| Admin OCI manifest | `49f2a9353624f3832a7a231ab662fb5cff051e33ca17af549dab3dd4f61d188f` |
| Operator OCI manifest | `b11d7be0ac4c8a397735d58774907abfa006d6bd59a8d1fc1301e777540dbb3d` |
| Offline Host Agent bundle | `6ab21b208e2558b74449ae74d549bdd3b76f8a418ff550aef0d414a67752f2e8` |
| GCP Caddy binary | `a563843e11cbce39c557bd429ebb787d56f49d51d9bbb3292cd9b36b37a60cdf` |
| GCP cloudflared binary | `1f99fb518b83dec2ba8d870a7cc991d82a77e6196295a3d2754ba17ab9f91872` |
| GCP shared runtime launcher | `839091cc507748674257883773ef6ec65ca5a7a9997c447390d735ff78ef7d39` |
| GCP live gateway, canonical JSON | `2171e47c323f578412328f1a1366d112b9cde5807d5c8adaab7da0ebcf62a4ee` |
| GCP live tunnel config, file bytes | `fe9c578e75733ad9f19ea0c61b9b799b6bb8c7ecf9077dfe3f91ddf826a50f18` |
| Disposable Operator email qualification launcher, private input | `193cedbae394704f34657ece78c62b316e3a4efc68a866275d7c9f56613adbb1` |
| Lima mount evidence, private input | `62c0c7160e7ec34d1b10735e04dd719f8b50abe4c0ccd263a9072f18b30c072e` |

GCP ran x86-64 Linux `7.0.0-1017-gcp`, Docker `29.9.3` build `5457199`,
nftables `1.0.9`, Caddy `2.11.9`, and cloudflared `2026.10.7`. The
[checkpoint](../../design/HOSTED_MVP_H03_12_CHECKPOINT.md#native-reboot-and-isolation-evidence)
records the separate ARM64 guest and projection pins.

The repository review used commit `11ee479aea1ef300fb67d6cc88a44221c5b2d365`
with the checkpoint working edits. The focused proof, identity contract and
gateway suites passed 163 tests. The tracked selection remains
`selected_not_verified`. Projection selection and protected configuration
sealing are pending the H03 identity-only checks above. Business projection selection follows H04/H05 qualification.
