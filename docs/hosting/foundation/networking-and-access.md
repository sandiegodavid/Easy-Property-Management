# Networking and access enforcement

[Foundation guides](README.md) · [Gateway/service runbook](../operations/network-and-host-services.md) · [Accepted design](../design/HOSTED_MVP_H02_DESIGN.md#network-iam-and-external-access-enforcement)

## Network and component boundaries

Each operator gets a dedicated internal dual-stack bridge, fixed exclusive addresses
from registered project assignments and unpublished application ports. Verify actual
bridge/address/container policy, not labels alone. nftables covers host input/output
and Docker forwarding for both IP families; host INPUT/UFW alone is insufficient.

| Path | Allowed peer / restriction |
| --- | --- |
| Application port | Only the gateway UID through the registered operator bridge/address |
| Loopback gateway | Only the Tunnel UID |
| HTTPS outbound proxy | Only registered operator bridge/address pairs |
| Sibling, metadata/link-local, host control and Docker API | Denied, including alternate names/addresses and forced-route controls |

The gateway has neither business mounts nor Docker/agent authority. Public Admin is
also unprivileged and uses the separate restricted client for host effects. The public
operator slug grants no private-network access.

## Exact-host gateway and durable denial

Caddy runs under its own unprivileged identity. Its permissioned Unix admin socket
replaces a TCP administration listener. cloudflared reaches the private loopback
listener using only its Tunnel credential; wildcard DNS/TLS does not replace exact
registered-origin validation. Unknown/reserved/forged hosts reject. Preserve original
origin and validate forwarded headers at the trusted boundary.

Inventory owns held/eligible/blocked ingress, binding generation and monotonic access
fence. A new binding is held closed. Source-local enable flags, image labels and
historical receipts cannot remove that denial. [Original-effect processing](inventory-and-host-commands.md)
reserves the new fence before effects, then loads **and inspects** the exact sealed
projection revision. A failed Caddy reload may leave old configuration active; it is
not verified denial. Independently contain/stop the affected runtime if deny or stream
termination cannot be confirmed.

Disable commits the newer deny, applies it to new/existing connections, verifies
containment, then reconciles source revocation. Containment alone does not complete
disable when source authority is unavailable. Enable requires current admitted intent,
resource readiness and verified identity/source proof. Positive ingress remains
unavailable until those owning workflows exist.

On restart regenerate from protected inventory, not Caddy autosave, mutable labels or
an independently editable configuration. Missing/corrupt authority stays closed. A
temporary Admin outage neither grants new access nor discards a valid deny/projection.
Ingress is not login: managed identity owns host-only sessions, CSRF and one-use handoff;
no shared parent-domain cookies, token caches or authenticated-response caching.

## Controlled outbound traffic

Endpoint registration is protected and defaults empty. A connected runtime uses the
HTTPS proxy; no wildcard endpoint or arbitrary direct public route is accepted.
Fresh bounded DNS resolution pins numeric destinations. Bounded TLS ClientHello/SNI
inspection rejects private/rebound destinations, redirects outside policy, hidden or
mismatched SNI and non-TLS traffic. Header/connect/relay work is bounded; resolver
subprocesses are reaped and client shutdown tracked.

The proxy does not decrypt HTTP or replace the application's TLS certificate and
authorization checks. Managed identity and recovery own their actual endpoint
registration and client semantics. IPv4/IPv6, metadata, sibling/private endpoints,
TLS/DNS rebinding and long-lived-stream behavior have distinct proof cases.

## Host services, credentials and IAM

Root-only service setup applies network policy, regenerates projections and inspects
or contains registered effects. Systemd uses distinct non-login service principals,
restricted namespaces/capabilities/resources and stop-only cleanup independent of an
unreadable inventory/config. Caddy readiness is notify-based. Ordered gateway → egress
→ Tunnel refresh avoids competing exclusive inventory refreshes at setup/boot.
The guardian is containment-only until owning start authority exists.

The host service account has repository-local reader and accessor on only the
dedicated Tunnel secret, with no project-wide role. Operators cannot obtain its
metadata/service identity or read Tunnel, sibling, agent or platform administration
credentials. `LoadCredential` supplies a read-only Tunnel credential; secret bytes
never enter unit environments, images, reports or exports.

Validate credentials in private staging before non-overwriting publication. Normalize
only the provider's empty `Endpoint` field; alternate endpoints and unknown fields
reject. Exact runtime three-field validation remains. Invalid staging leaves no final
credential; successful setup retries preserve credential and inventory identity.
Per-workspace backup object/key authorization remains a separate recovery prerequisite;
a broad shared R2 credential plus a configurable prefix is insufficient isolation.

## Evidence and code

[Native GCP evidence](../qualification/reports/HOSTED_MVP_H02_9_VALIDATION.json)
records scoped IAM/Tunnel delivery, real public closed response, direct-origin denial,
full network/stream/egress tests and rebooted service verification. [Current consolidated
evidence](../qualification/reports/HOSTED_MVP_H02_11_VALIDATION.json) repeats the connected
sandbox and verifies restoration of the real closed projection. Earlier ARM64 TLS/DNS
and credential controls used local synthetic endpoints/material in isolated namespaces;
they are not actual Cloudflare authentication or a deployed login pass.

Code: [gateway](../../../application/apps/server/app/modules/host_agent/infrastructure/gateway.py),
[bridge policy](../../../application/apps/server/app/modules/host_agent/infrastructure/network_policy.py),
[firewall](../../../application/apps/server/app/modules/host_agent/infrastructure/network_firewall.py),
[egress proxy](../../../application/apps/server/app/modules/host_agent/infrastructure/egress_proxy.py),
[service runner](../../../application/apps/server/app/modules/host_agent/infrastructure/service_runtime.py),
[Tunnel credentials](../../../application/apps/server/app/modules/host_agent/infrastructure/tunnel_credentials.py).
