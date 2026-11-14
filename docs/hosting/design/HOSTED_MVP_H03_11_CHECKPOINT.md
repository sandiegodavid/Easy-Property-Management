# H03.11 authentication candidates and deployment gates

H03.11 private infrastructure qualification is complete. The project owner confirmed
10 email-link sends per day, and the deployment cap is 9 per rolling 24
hours. The protected provider setup, scoped credential, and shared endpoint
registration passed on the GCP qualification host, along with the Operator
source registration and relay checks below. Deployed sign-in, email delivery,
and final sealing are tracked in [H03.12](HOSTED_MVP_H03_12_CHECKPOINT.md).

## Delivered and qualified locally

- The shared Admin image packages the exact Admin and login assets. The
  independent Operator image serves the managed authentication entry and owns
  the access-store listener under the protected workspace writer lock.
- Installed entry points validate the private setup, artifact and origin.
  Shared Admin and login flows use separate routes and cookies. Operator
  composition leaves business access closed in the absence of H04/H05.
- The Host Agent has a central-to-source relay and isolated per-Operator
  return relay support. The source binding and running registration govern
  dispatch. The central-only CONNECT listener accepts the exact central
  private peer and the selected Google provider hosts.
- The shared login listener proxies the fixed Firebase browser helpers.
  Its public Firebase initialization JSON comes from the selected browser
  configuration. The upstream project's `/__/firebase/init.json` returned 404.
- The Host Agent resolves shared endpoints from the protected registration and
  the current Admin login origin. It verifies the running OCI manifest and image
  config, exact internal Docker bridge, runtime principal, mount boundaries,
  nftables policy, TLS trust and asset hashes under the gateway UID. Missing or
  stale evidence closes shared projection. The protected `verify-shared` action
  checks readiness independently of publication.
- The Admin and Operator OCI archives and offline Host Agent bundle are
  retained in the private qualification directory. The [build and launch
  runbook](../deployment/identity-candidates.md) describes protected inputs
  and local candidate use.

## Local artifact pins

Private artifact directory: `hosted-mvp-qualification/H03.11-Wq3ZrC` under
`Property-Management-Data`.

| Artifact | Verified SHA-256 |
| --- | --- |
| Shared Admin OCI manifest | `sha256:49f2a9353624f3832a7a231ab662fb5cff051e33ca17af549dab3dd4f61d188f` |
| Operator OCI manifest | `sha256:b11d7be0ac4c8a397735d58774907abfa006d6bd59a8d1fc1301e777540dbb3d` |
| Offline Host Agent bundle | `sha256:6ab21b208e2558b74449ae74d549bdd3b76f8a418ff550aef0d414a67752f2e8` |

## Validation and provider evidence

| Area | Observed |
| --- | --- |
| Packaging | Offline Linux/AMD64 candidate builds used the pinned H02 dependency closure. Both installed entry points passed synthetic TLS probes outside the checkout with egress disabled. The offline Host Agent archive installed in a fresh container, validated its inventory schema, and exposed the new protected command. |
| Host and identity regressions | 166 focused Python tests passed in separate packaging/identity and handoff runs. The continuation passed another 98 focused host registration, gateway, firewall, relay and egress tests. Ruff lint and formatting passed. |
| Firebase helper origin | The installed central CONNECT proxy fetched all five fixed helper paths from the selected project. The shared-host test verified local initialization JSON, exact method and origin separation, and no-store responses. |
| Billing | Cloud Billing and the CLI reported billing enabled for the selected project `project-47b72bb7-ba90-42c9-910`. |
| Daily email-link allowance | Service Usage returned nine effective quota metrics and no email-link sending metric. The verification-code metric measures a different operation. The published billed-tier allowance does not establish this project's effective allowance. [Google Identity Platform quotas](https://docs.cloud.google.com/identity-platform/quotas) |
| Native registration | On the retained ARM64 Linux VM, real Docker and nftables verified the shared bridge and UID-specific rules. Caddy served the exact synthetic Admin/login routes over TLS with pinned assets. The probe denied cross-host assets, wrong methods, a non-tunnel UID, and the unregistered CONNECT target. Fixture resources were removed and the VM was stopped and retained. |
| Cloud state | `epm-h02-host` in `us-west1-b` was stopped. The project inspection changed no cloud resources, sent no email, and admitted no Operators. |

## Accepted allowance and application cap

Selection revision 3 records the owner-confirmed provider allowance of 10
sends per day and caps the deployment at 9 sends per rolling 24 hours. The
existing setup contract requires the application cap to be strictly below
the provider allowance. The destination, network, and resend limits also
apply independently.

Read-only Google Identity Platform checks confirmed Google sign-in,
email-link mode, TOTP, and the authorized Admin and login domains. The
digest-matched setup and provider configuration passed the protected loader
and are staged in `hosted-mvp-qualification/H03.11-selection-r3`.
The tracked selection stays `selected_not_verified` until deployed
qualification and final sealing. No image rebuild was needed for the cap.
All 89 focused identity tests passed, including the startup wiring,
tenth-send rejection, and admission after the window clears. Ruff passed.

## GCP artifact staging

The pinned Admin and Operator images were imported on the actual AMD64
qualification VM. Both installed entry points passed synthetic TLS smoke
tests in network-disabled containers. The pinned Host Agent bundle was
installed offline in the private `/var/tmp/epm-h0311-r3/agent-runtime`
directory and exposes `verify-shared`. This staging install leaves the
running Host Agent service and its configuration in place. The guest had
zero running containers after the probes, and the tunnel projection still
contained only its catch-all 403 rule. No sign-in or email send was attempted.

## Scoped runtime credential

The dedicated `epm-h03-central` service account has a project custom role
with only `firebaseauth.users.get` and `firebaseauth.users.createSession`.
A second custom role grants the existing qualification VM service account
only `iam.serviceAccounts.getAccessToken` on the dedicated account. IAM
readback confirmed the role definitions and account-level binding. The
dedicated account has no user-managed service-account keys.

From the GCP guest, the credential delivery probe used its attached VM
identity to mint two separate 10-minute Identity Toolkit–scoped access
tokens. It verified atomic replacement of the central-owned mode-0600
bearer in a private runtime directory. No token value was retained in the
report. [Google IAM Credentials API](https://docs.cloud.google.com/iam/docs/reference/credentials/rest/v1/projects.serviceAccounts/generateAccessToken)

## Private shared endpoint registration

In the initial shared run, the pinned image ran on its dedicated internal Docker bridge on the
AMD64 GCP qualification host, with an empty Admin store and no real Operator
registration. The staged Host Agent's `verify-shared` path accepted the
protected registration after checking the running image, bridge and
firewall, owning Admin origin, TLS trust and name, pinned Admin and login
assets, and exact Firebase handler and initialization paths through the
dedicated central proxy.

Both relay directions passed on the same guest using real Unix sockets,
distinct caller UIDs, and synthetic owning handlers. The focused suite also
passed 74 relay, shared registration, gateway, handoff, and identity tests.

The private run was temporary. Its listener, internal bridge, token and
sockets were removed after validation. The staging directory and dedicated
IAM resources remain available for H03.12. While the connector was running,
the Admin origin, login origin, and exact public Firebase callback each
returned HTTP 403 over verified TLS. Live sign-in and email sends remained
disabled. GCP confirmed the VM returned to `TERMINATED`. H03.12 owns public
activation and interactive qualification.

## Private Operator source registration

The pinned Operator and shared images ran on the GCP qualification host
with disposable stores and the current host inventory schema. The Host
Agent loaded a root-owned source registration for the disabled qualification
identity and resolved its held endpoint against the running pinned image,
dedicated dual-stack internal bridge, firewall, resource generation, and
access epoch. The Operator listener had no published Docker ports.

| Check | Observed result |
| --- | --- |
| Owning listener sockets | Operator and central sockets had mode `0600` and the expected UID/GID pairs, `118311:118311` and `65532:65532`. |
| Host Agent relay sockets | Both had mode `0660`. The central-facing socket belonged to `0:65532` and the per-Operator return socket belonged to `0:118311`. |
| Central to Operator | The authorized central UID received the installed Operator listener's empty original-receipt result for a fresh lookup. The relay denied a foreign UID with directory access and the caller rejected a mismatched server UID. |
| Operator to central | The installed central listener denied an unknown continuation. With its socket temporarily unavailable, the same authorized request returned unavailable, confirming that the first result came from the owning listener. The return relay denied a foreign UID with directory access. |
| Service and cleanup | The public gateway and tunnel configurations matched before and after the probe and omitted the mail-send route. The temporary containers, bridge, inventory, and sockets were removed. The original shared identity, gateway, and tunnel services remained active. |

The focused relay, shared-registration, and handoff suites passed 37 tests.
The private qualification script is retained in
`hosted-mvp-qualification/H03.11-source/qualify_source.py` under
`Property-Management-Data`, with SHA-256
`4282e6812877505652be813c16c93090c194699c3fc49d7cf65329150deb7ef8`.
The running public projection serves the shared Admin and login routes.
Deployed browser handoff and any email delivery require H03.12 qualification.
