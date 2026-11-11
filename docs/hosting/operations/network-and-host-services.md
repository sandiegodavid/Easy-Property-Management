# Gateway, networking and host services

[Tool source](../../../application/deploy/hosted-mvp/gateway) · [Foundation guides](../foundation/README.md)

This is a network/service integration and isolated qualification runbook, **not**
permission to enable operators. The original component/native ARM64 results are dated
evidence; the [foundation guide](../foundation/networking-and-access.md) indexes later
native GCP checks and the remaining identity boundaries.
See the [handoff and validation matrix](../qualification/reports/HOSTED_MVP_H02_6_HANDOFF.md)
and [final source/result manifest](../qualification/reports/HOSTED_MVP_H02_6_FINAL_VALIDATION.json).
[Protected launch](../deployment/protected-launch.md) and [GCP setup](../deployment/gcp-host-setup.md)
cover their separate composition and installation procedures.

## Protected setup and commands

Setup supplies root-owned private `ServiceInputs` JSON, matching initialized owning
inventory/metadata, reserved UID/GID/project ranges, network pools, registered Tunnel
ID and private layout. `service_config.py` is the exact input contract. Paths are
canonical absolute Linux paths; the config is root-owned 0600 in a root-private 0700
directory. The inventory is separately initialized through its owning database runner.
These service commands never initialize/adopt inventory, allocate operators, grant
admission, start application containers or contact an Admin database.

Run the installed host-agent Python with:

```sh
/opt/epm/host-agent/bin/python -B \
  -m app.modules.host_agent.infrastructure.service_runtime network \
  --config /etc/epm/host-services.json
```

Actions are `network`, `refresh`, `verify` and `contain`. They apply/inspect host policy,
regenerate protected projections, verify current denial, or stop exact registered
runtimes. On uncertainty the runner contains and exits unavailable. The independent
stop-only command used by units does not require readable inventory/config:

```sh
/opt/epm/host-agent/bin/python -B \
  -m app.modules.host_agent.infrastructure.supervisor \
  --registry /var/lib/epm/stops --contain-all
```

`host_services.service_unit()` generates `network`/`projection` prerequisite units and
separate `gateway`, `tunnel`, `egress` services. Install them only through protected host
setup with their matching resolved layout and named OS identities. The network unit
loads `br_netfilter`; both bridge-nf sysctls must verify as 1. Projection runs after
network setup to avoid singleton contention. Every daemon start refreshes from owning
inventory; Caddy uses notify readiness. No independently edited config or autosave is
a fallback. Privileged pre/post commands are fixed root-trusted agent commands, not
browser-controlled arguments. Daemons have no capabilities and cannot read data,
inventory, stop authority, Docker socket or another service's credential.

Prepare root-owned 0750 projection directories with each service's read-only group,
and 0700 service-owned runtime directories. `ProjectionPublisher` atomically writes
root-owned 0640 derived files and fsyncs them. The proxy's root-generated policy
contains only hosts, port and expected UID; it is not a credential or authority ledger.
`outbound_hosts` defaults empty and has no wildcard support. H03/H05 own actual endpoint
registrations. Connected containers use a numeric gateway HTTPS proxy, with no direct
public route or general HTTP proxy grant.

Supply exactly one root-private 0600 Tunnel JSON credential whose `TunnelID` matches
protected setup. Validation rejects malformed, unsafe, wrong-Tunnel and extra-field
input without printing its bytes. Systemd `LoadCredential` gives only the Tunnel unit
a read-only credential at `/run/credentials/epm-tunnel.service/tunnel.json`. Do not put
secret material in unit environments, reports or source. Actual provider retrieval and
resource-local IAM application remain the H02.9 setup boundary. `scoped_iam.py` emits
only repository reader and one Tunnel-secret accessor policy for the host service
account, never project-wide editor/owner or an Operator service account.

## Retained disposable qualification environment

Use only clone `epm-h02-runtime` (Ubuntu 24.04 ARM64, kernel `6.8.0-147-generic`).
Preserve the original `epm-quota-test` VM unchanged. Clone Python tools are at
`/var/lib/epm-h02-runtime-tools/`; installed candidate/runtime Python versions and
source pins are recorded with the evidence. Temporary service tests use an explicit
protected source copy; production uses the installed agent bundle.

From `application/` on the Mac:

```sh
COPYFILE_DISABLE=1 tar --no-xattrs --exclude='__pycache__' --exclude='*.pyc' \
  -cf /tmp/epm-h02-6-source.tar apps/server/app database \
  deploy/hosted-mvp/gateway deploy/hosted-mvp/sandbox
limactl copy /tmp/epm-h02-6-source.tar epm-h02-runtime:/tmp/epm-h02-6-source.tar
limactl shell --workdir=/tmp epm-h02-runtime sh -c '
  mkdir -p /tmp/epm-h02-6-source &&
  tar -xf /tmp/epm-h02-6-source.tar -C /tmp/epm-h02-6-source'
```

In that clone's `/tmp/epm-h02-6-source`, use the tools Python, `-B`,
`PYTHONPATH=/tmp/epm-h02-6-source/apps/server`, root and
`EPM_RUN_GATEWAY_QUALIFICATION=1` for the following focused harnesses:

| Harness                  | Inputs and proof                                                                                                                                                                                                                                         |
| ------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `qualify_gateway.py`     | `--caddy /tmp/epm-caddy-input/caddy`; dedicated UID/private socket, unknown/forged-host denial and reload failure.                                                                                                                                       |
| `qualify_containment.py` | `--image` exact installed image hash below; exact stop projection, uncommitted runtime and unchanged sibling.                                                                                                                                            |
| `qualify_network.py`     | `--image` hash and optional `--caddy`; dual-stack bridges, source/UID checks, real proxy, forced metadata/public routes with drop counters, and synthetic prior-open stream closure.                                                                     |
| `qualify_services.py`    | `--caddy`; fresh synthetic real inventory, hardened systemd graph, read-only scoped synthetic credential, cross-UID/socket denial, process-death restart, stale-file regeneration, missing/corrupt authority. No Cloudflare connection.                  |
| `qualify_tunnel.py`      | `--cloudflared /tmp/epm-cloudflared-input/cloudflared`; offline exact routing and deny catch-all in an empty network namespace.                                                                                                                          |
| `qualify_egress.py`      | No extra args; private mount/network namespace with only loopback and a synthetic globally classified IP. Verified TLS, SNI mismatch denial, redirect rejection, fresh rebinding rejection and a deliberately stalled DNS deadline. No external traffic. |

`qualify_connected.py --run` instead requires
`EPM_RUN_PROJECT_QUOTA_QUALIFICATION=1`. It reuses the current disposable H02.5 ext4
quota/AppArmor fixture with connected bridges, all three tree ceilings, deleted-open/
inode/WAL faults, cross-UID isolation and start/supervisor stop behavior under the new
connected qualification hash. It cannot qualify production Admin admission.

Each harness prints a private lab/result path. Failed diagnostics remain with successful
observations; a failed process is not a pass even if an older partial harness wrote a
premature status. Preserve results, actual source/tool pins and commands before stopping
the clone; `/tmp` clears across boots. Export no credential files or TLS private keys.
Remove test services/containers/bridges and stop, retain and reuse the VM after testing.

Network proof pools are `10.249.0.0/16` and `fd47:6570:6e00::/48`; service/combined
fixtures use separate pools and reject collisions. The network harness uses synthetic
UIDs 42011/42012/42013 and proxy port 21080; these are not production allocations.
The component proxy default is 1080. Only its registered operator address/bridge pairs
may reach that listener; other host/external peers are dropped. Host daemon UIDs cannot
fetch VM metadata/private-control credentials. Host DNS should use its protected local
resolver; do not grant direct metadata HTTP access to make DNS work.

## Exact retained tools and limits

Test container image (already present in the clone):
`5dec05dc4c2653fa17e45761e59d61a93964fdcd67b3194d840fd8a43d565024`.
Caddy official `v2.11.9` Linux ARM64 binary SHA-256:
`762d7763ed8e303d50bf11fb0274627266907ea8c170720d7d9a6fd0b9bf5c65`.
Its archive was verified against the official SHA-512 release checksum. Cloudflared
`2026.10.7` ARM64 SHA-256:
`3df43aedc9ff291d1735b5cb576cb97e0b157488796db2e32b28aecabb445775`.
Verified input archives and private labs are retained under
`~/Desktop/Property-Management-Data/hosted-mvp-qualification/H02.6/` on the Mac; restore
their `/tmp` inputs into the clone after a reboot. None of these ARM64 proofs qualifies
native AMD64, GCP, provider authorization, capacity or complete hosted-release acceptance.

The proxy admits conventional clear-SNI TLS ClientHello only and rejects ECH/hidden or
mismatched names. It does not decrypt HTTP, inspect encrypted HTTP Host, or replace client
certificate verification or provider authorization. Endpoint SDKs and H03/H05 retain
those responsibilities; no TLS interception CA is installed.

Primary references: [Caddy admin API](https://caddyserver.com/docs/api),
[pinned matcher implementation](https://github.com/caddyserver/caddy/blob/v2.11.9/modules/caddyhttp/celmatcher.go),
[Caddy notify unit](https://github.com/caddyserver/dist/blob/master/init/caddy.service),
[systemd credential delivery](https://www.freedesktop.org/software/systemd/man/latest/systemd.exec.html#Credentials),
[Docker forwarding policy](https://docs.docker.com/engine/network/firewall-iptables/),
[Artifact Registry IAM](https://docs.cloud.google.com/artifact-registry/docs/access-control)
and [Secret Manager least privilege](https://docs.cloud.google.com/secret-manager/docs/access-control).

Fresh candidate launch and safe unavailable-page behavior are documented in the
[launch runbook](../deployment/protected-launch.md). This launch path does not enable positive
ingress; gateway denial remains independent of process liveness.
