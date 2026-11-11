# H02.6 ingress, network and secret-boundary handoff

H02.6 is delivered within its component/native ARM64 qualification scope. It does
not enable customer access or deploy to GCP/Cloudflare. The
[H02 design](../../design/HOSTED_MVP_H02_DESIGN.md) defines the acceptance boundary;
[the gateway runbook](../../operations/network-and-host-services.md)
contains reproduction steps and protected setup requirements.

## Delivered behavior

- Complete inventory-owned, exact-host Caddy denial; permissioned Unix admin API,
  verified apply/inspect, retained original-effect retries and independent exact-ID
  stream/runtime containment. Positive ingress remains unavailable until H03/H04.
- Dedicated internal dual-stack bridges, fixed exclusive addresses from existing
  project assignments, unpublished application ports and a verified nftables policy
  covering input/output/Docker forwarding. Only the gateway UID reaches application
  ports; only the Tunnel UID reaches the loopback gateway; only registered operator
  bridge/address pairs reach the outbound proxy. Sibling, metadata, host-control and
  direct public routes are denied, including forced routes in the native negative test.
- Connected-runtime HTTPS proxy setting, default-empty endpoint registration, fresh
  bounded DNS, numeric destination pinning, bounded TLS ClientHello/SNI validation,
  rejection of hidden/different SNI and non-TLS traffic, overall header/connect/relay
  bounds, tracked-client shutdown and reaped resolver subprocesses. The proxy does not
  decrypt HTTP or replace the application's certificate/authorization checks.
- Root-only service runner for protected network policy, derived projections, inspection
  and containment. Startup regenerates from the real owning inventory without an Admin
  RPC or Caddy autosave. Systemd units use separate service principals, explicit ordering,
  Caddy notify readiness, restrictive namespaces/capabilities/resources and independent
  stop-only cleanup even when inventory/config cannot be read.
- Tunnel-scoped protected credential validation and systemd `LoadCredential` delivery,
  read-only and unavailable to gateway/Operator identities. Credential bytes are absent
  from unit environments, reports and exported evidence. IAM output grants only exact
  repository reader and one Tunnel-secret accessor permissions to the host service account;
  applying those resource policies belongs to H02.9.

## Evidence and practical limits

[Final validation/source manifest](HOSTED_MVP_H02_6_FINAL_VALIDATION.json) records
focused tests, changed-file lint, actual native outcomes and source pins. Prior
partial manifests remain historical observations, not newer acceptance claims.

| Area | Focused/native evidence |
| --- | --- |
| Happy paths | Owning snapshots and receipts; real Caddy host denial; connected bridge addresses; actual hardened service graph; approved synthetic TLS through the production proxy. |
| Invalid combinations | Unknown/forged hosts, stale fences, duplicate slots, route overlap, unexpected peers, malformed CONNECT/TLS, SNI mismatch, private DNS, wrong Tunnel ID and unsafe credential files reject. |
| Retry/idempotency | Original unknown ingress only inspects; verified receipts repeat without another effect; bridges are inspected rather than recreated; repeated containment is safe. |
| Failure/rollback | Durable denial before external effects; both failures retained; supervisor stops on firewall loss; missing/corrupt inventory blocks service start; SIGKILL restart stays held; stale projection is regenerated. |
| Persistence/schema | Uses the current owning baseline and immutable assignments; no new DDL or migration path. Root projection files are derived inputs, not a second authority. |
| Backup/restore | No business backup format/path changed. H05 restore and key/object scopes remain unavailable. |
| Query budget | Bounded owning set-based projections and existing ingress budget checks; capacity/large-host policy measurements remain H02.10. |
| Native combined sandbox | Two synthetic owners, current quota/AppArmor/seccomp/mount/cgroup limits, connected bridges, byte/inode/deleted-open/WAL failures, cross-UID denial, new connected qualification hash and stop after firewall loss. |

Native tests ran in retained clone `epm-h02-runtime`, Ubuntu 24.04 ARM64. The original
`epm-quota-test` baseline was unchanged. TLS/DNS tests ran in private network/mount
namespaces with no external interface; their globally classified endpoint IP was a
local synthetic address. Credential tests used synthetic material and an explicit
consumer probe in the real hardened Tunnel unit; no Cloudflare authentication ran.

## Later owners

- **H02.7:** fresh hosted application composition, real admitted source/qualification
  adapters, health/unavailable presentation and integration with these private service
  components. No synthetic adapter is supplied by the production service runner.
- **H02.8–H02.11:** broader reproducible/native-platform/reboot qualification, actual
  GCP/Cloudflare setup and resource-scoped IAM application, capacity measurement and
  aggregate acceptance. ARM64 clone results do not qualify native AMD64/GCP.
- **H03/H04:** identity, source eligibility, enable/revoke and Admin workflows. Local
  flags or image labels cannot remove the protected deny.
- **H03/H05:** actual managed endpoint registration, client TLS/certificate semantics
  and per-workspace credentials/object/key authorization. Configure no wildcard endpoint
  or shared broad backup credential. The default protected endpoint policy is empty.
