# Build and validate the authentication candidates

The H02 health-only candidates retain their existing launch modes. H03 adds
explicit entry points for the shared Admin and login listener, the Operator
authentication listener, and the dedicated central CONNECT proxy. An installed
candidate can be tested using synthetic stores. Production configuration requires
provider evidence, protected credentials, and host-owner verification.

## Build for local qualification

Use the closed Linux/AMD64 dependency lock and wheelhouse prepared by the
[packaging runbook](packaging-and-installation.md). From `application/`, set
`EPM_LOCK`, `EPM_WHEELS` and `EPM_IDENTITY_BUILD` to the lock, wheelhouse and
fresh private artifact directory. Build the shared candidate with both identity
UIs, then prepare the independent Operator image and host-agent bundle.

```sh
export PYTHONPATH="apps/server:."
.venv/bin/python scripts/hosted_package.py --identity --component admin \
  --lock "$EPM_LOCK" --wheelhouse "$EPM_WHEELS" --output "$EPM_IDENTITY_BUILD/admin"
for role in operator host_agent; do
  .venv/bin/python scripts/hosted_package.py --component "$role" \
    --lock "$EPM_LOCK" --wheelhouse "$EPM_WHEELS" --output "$EPM_IDENTITY_BUILD/$role"
done
for role in admin operator; do
  docker buildx build --platform linux/amd64 --network none --load \
    --output "type=oci,dest=$EPM_IDENTITY_BUILD/$role.oci.tar" \
    --metadata-file "$EPM_IDENTITY_BUILD/$role-build.json" \
    --provenance=false --tag "epm-h03-${role}:qualification" "$EPM_IDENTITY_BUILD/$role"
done
.venv/bin/python deploy/hosted-mvp/archive_agent.py \
  "$EPM_IDENTITY_BUILD/host_agent" "$EPM_IDENTITY_BUILD/host-agent.tar.gz"
```

The shared file inventory includes the two compiled `dist/index.html` files
and their exact JS/CSS assets. It excludes source maps, test fixtures,
credentials, and application data. Use the corresponding packaged public paths
for the native shared endpoint record.

## Explicit protected launch

| Component | Installed module | Protected inputs |
| --- | --- | --- |
| Shared Admin and login | `app.modules.hosted_access.infrastructure.shared_identity_entry` | Admin deployment file, sealed setup, digest-matched provider configuration, rotating scoped bearer file, rate key, central signer, public source keys and bindings, separate relay directories, and exact private gateway, listener and proxy addresses. Admin store ID and the owning login origin are checked before startup. |
| Operator authentication | `app.modules.hosted_access.infrastructure.operator_entry` | Exact source binding, existing private access store, workspace mount, pre-created writer lock, source signing key, registered central origin and public key, and exact gateway, listener, and relay peers. The installed candidate validates the stores and owns its source socket. |
| Central egress | `app.modules.host_agent.infrastructure.identity_egress` | One dedicated unprivileged principal and private bridge address, exactly one central source address, numeric port, and the selected Firebase project. CONNECT permits Identity Toolkit, Google signing certificates, and the selected Firebase helper hostname. |

The identity listeners take `--configuration`, `--tls-certificate`,
`--tls-key`, and an optional `--port` (default 8000). TLS terminates at the
listener and ingress checks the direct gateway peer. The Host Agent routes the
central-to-source socket and the per-Operator return sockets with separate
kernel peer UIDs. Central returns to `<central_return_directory>/<operator-id>.sock`.
Each Operator is mounted only its own return socket at
`<source_return_directory>/<operator-id>/relay.sock`. Host Agent directories
must have the owning principal and expected modes before the service starts.

Use the selected project’s effective daily **email-link sign-in sends** to
set the application ceiling. The project owner confirmed 10 sends per day,
and the application ceiling is 9 sends per rolling 24 hours. The
verification-code metric measures a different operation. [Google Identity Platform quotas](https://docs.cloud.google.com/identity-platform/quotas)

On the qualification VM, use the attached VM identity to mint a 600-second
Identity Toolkit–scoped access token for `epm-h03-central`. The VM has
`iam.serviceAccounts.getAccessToken` on that account, and the account's
project role grants `firebaseauth.users.get` and
`firebaseauth.users.createSession`. Maintain the bearer as a central-owned
mode-0600 file in the protected control directory. Replace it atomically
before expiry and mount the containing directory so the reader sees the new
file. Keep token issuance and rotation on the host. The central container
uses the scoped CONNECT proxy for provider requests. [IAM Credentials API](https://docs.cloud.google.com/iam/docs/reference/credentials/rest/v1/projects.serviceAccounts/generateAccessToken)

The central listener forwards the fixed Firebase helper paths through the
protected proxy. It serves Firebase initialization JSON from the protected
public web settings because the provider hostname returns 404 for that path. The gateway preserves the configured login hostname and derives the
email rate-limiting network from the trusted tunnel ingress. Native
registration must verify the running digest, bridge, upstream TLS identity,
exact assets, firewall isolation, and trusted forwarding before publishing a
public route. Keep business ingress closed until the H04/H05 owners supply
their readiness evidence. [Firebase custom authentication domain guidance](https://firebase.google.com/docs/auth/web/redirect-best-practices)

Use the [H03.11 checkpoint](../design/HOSTED_MVP_H03_11_CHECKPOINT.md) for
executed local checks and the deployment work still open.

## Native shared registration

The host owner supplies `network.shared_identity` in the protected
`ServiceInputs` and a matching `shared` record in the root-owned
`auth_registration` JSON. Neither file is a credential store.

- Set `endpoint_id` to the shared manifest’s `private_endpoint_id`. Choose a
  dedicated IPv4 /30 and IPv6 /64 outside the Operator address pools and
  unrelated host routes. The first usable address is the host gateway and
  the second is the shared container. Set a dedicated `proxy_uid` outside
  the Operator range and a distinct `proxy_port`.
- Fill `shared.manifest` with the fixed Admin/login origins and the installed
  OCI manifest digest. Compute `manifest_sha256` with `semantic_hash()` over
  that typed manifest. Set the exact running `container_id` and
  `image_config_sha256` from Docker and use the manifest digest reference
  to start the container. The UID and GID must match the central side of
  `identity_relay`.
- Set `admin_database` to the private host path to the current Admin store.
  Register the provider project as `firebase_project`, the SNI hostname as
  `tls_name`, and one PEM trust anchor as `trust_pem`. Pin the SHA-256 of
  the Admin HTML shell and each public JS/CSS asset from the matching
  packaged inventories. Asset entries have a public `path` and a
  `sha256` digest.
- Run the host service's `network` action before starting the shared
  listener. Use only the dedicated internal bridge, a read-only root,
  dropped capabilities, and no-new-privileges. Deliver protected bind
  mounts under `/control`, `/run/epm-identity-relay`, or
  `/run/epm-central-identity`. Use `/tmp` for transient writable
  storage. The shared listener binds its fixed IPv4 address on port 8000
  without a published Docker port. Use the TLS readiness probe for this
  listener instead of the H02 health-only container's HTTP health check.
- Start the separate central proxy on the bridge gateway address with its
  dedicated UID. Configure the shared listener to use that numeric CONNECT
  peer. Start the central and Operator identity sockets before starting
  the Host Agent's `relay` action. Match the private socket owners and
  mount only the registered socket paths into each runtime.

Run `service_runtime verify-shared --config /etc/epm/host-services.json`
via the installed Host Agent Python. This reads the current Admin login
origin, verifies the running container and bridge, checks the installed
nftables rules, and probes TLS and exact asset bytes under the gateway UID.
It leaves routes unpublished. With the same configuration, the host's
normal projection refresh admits only those verified Admin and login
routes. Missing or stale shared evidence yields a closed shared
projection. Re-run verification and refresh when replacing the candidate,
and let the protected gateway lifecycle apply the new projection.

The native synthetic probe can run on the retained Linux qualification
guest with the known ARM64 Python fixture image, pinned Caddy binary,
`br_netfilter`, and the candidate Python environment. It refuses to
replace an existing EPM firewall or shared network and removes its own
fixture resources when it exits.

```sh
sudo env PYTHONPATH=/path/to/application/apps/server \
  /path/to/native/python -B /path/to/application/deploy/hosted-mvp/gateway/qualify_shared_identity.py \
  "$SYNTHETIC_BASE_IMAGE_SHA256" "$PINNED_CADDY_PATH"
```
