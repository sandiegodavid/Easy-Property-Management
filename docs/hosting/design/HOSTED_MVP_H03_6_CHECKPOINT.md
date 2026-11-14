# H03.6 gateway and identity relay checkpoint

H03.6 gateway and relay foundations and focused local validation are delivered.
The deployed gateway remains on its closed projection.

## Implemented and verified locally

- Host inventory stores auth-route readiness and requires a current applied
  receipt for the same binding and access epoch. Ingress reservations clear
  readiness when changing deny state or access epoch.
- The host agent reserves a typed auth route effect with an expected revision
  and manifest pin. The driver resolves, loads and inspects the candidate, then
  commits readiness with the receipt. An uncertain retry inspects the original
  candidate. Failed inspection attempts the closed projection and containment.
- Held sources receive only the three fixed auth routes. Admin and login use
  separate exact host and method lists and bounded exact asset paths. Protected
  resolution checks the manifest pin and the Admin control owner's login origin.
- Caddy checks the raw host and request target, requires one HTTPS protocol
  header value, and rejects forged forwarding and rewrite headers. Upstream
  TLS checks the server name. Resolved addresses must be numeric private bridge
  addresses.
- The identity relay uses bounded Unix frames and kernel peer UID checks on
  both hops. A registry resolves the workspace and epoch to its source endpoint.
  The relay preserves original operation identity and receipts. A source
  dispatch adapter can share the public source process's owning mutation gate.
- A dedicated central identity egress policy admits Identity Toolkit and the
  Google certificate host.

## Qualification evidence

The focused gateway, inventory, and Unix relay run passed 166 tests. A disposable
network-disabled Docker Desktop container running Caddy 2.11.9 at image digest
sha256:4851e54a46b206517c574821bb5cc67f170d2156041e9fbc4c9193b45e84a75b
validated the generated proxy configuration. A second run used status markers
to exercise the real Caddy matchers. Login callback and Admin paths matched.
Wrong host, alternate port, HEAD, OPTIONS, encoded and normalized paths, forged
forwarding headers, and duplicate protocol headers denied. The initial probe
exposed Caddy's multi-value header behavior. The exact-value check corrected it
and the repeat probe passed.

Local tests use explicit synthetic owners. The Caddy probe did not establish
upstream TLS, host network isolation or an externally reachable callback.

## Protected runtime continuation

- The root service can load an optional owner-only registration file. The host
  refresh and verification paths regenerate held routes from current inventory
  through the same protected registration rather than trusting an old projection.
- Source lookup checks binding generation, workspace, epoch, readiness, registered
  artifact, live container and bridge, and firewall state. Relay lookup resolves only
  the registered Unix socket with the owning UID. The relay still checks kernel
  peer credentials at connect time.
- The host service's `relay` action opens `/run/epm-identity-relay/relay.sock`
  only with protected source registration and a separate configured central UID
  and GID. Protected setup supplies the owner-only-writable `0750` directory
  with the central group. The service grants that group access to the `0660`
  socket, checks the central UID before decoding calls, and preserves any
  pre-existing path. A clean stop removes the listener it created.
- Startup derives the Caddy and Tunnel candidates together. Both receive shared
  Admin/login hosts only when an endpoint owner returns the verified shared
  selection. The installed source registry currently returns no shared selection.
  The login matcher admits the exact GET paths for the Firebase handler, iframe,
  their scripts, the experiments script and Firebase initialization. Serving those
  resources requires the deployed shared identity component. [Firebase guidance](https://firebase.google.com/docs/auth/web/redirect-best-practices)
- 254 focused gateway, relay, host-service, identity-contract and schema tests
  passed. Changed-file Ruff lint and formatting passed. The pinned Caddy image
  validated the generated candidate and passed nine helper matcher checks using
  status markers in a network-disabled container. The checks covered all six
  helper paths and denial on the Admin host, an unregistered path and a forged
  forwarding header.

## Handoff to later slices

| Slice | Work |
| --- | --- |
| H03.7 — delivered locally | The signed handoff dispatch shares the Operator process and mutation gate. See the [H03.7 checkpoint](HOSTED_MVP_H03_7_CHECKPOINT.md) for evidence. |
| H03.8 — delivered locally | Authenticated dispatch applies owning source lifecycle commands and retains original results. See the [H03.8 checkpoint](HOSTED_MVP_H03_8_CHECKPOINT.md). |
| H03.11 | Install the auth candidates and register the Operator listener, relay, socket permissions and peer identities. Supply verified shared Admin/login endpoints, upstream TLS identity and exact assets. Connect the Firebase helper origin and configure central-only provider egress and trusted ingress. |
| H03.12 | On the disposable target, qualify socket ownership and peer isolation, dual-stack separation, direct-origin denial, trusted forwarding, scoped egress, stream containment, and reboot regeneration. Check wrong hosts, paths, methods and forged headers, held-host auth-only behavior, and Operator-to-Admin isolation. Verify the Admin/login HTTPS origins and exact external Firebase callback before interactive qualification. Select the new projection after all gates pass. |

On November 19, `epm-h02-host` matched retained instance ID
`6955052781247608210` and was `TERMINATED`. The external callback returned
HTTP 525 on a read-only check.
