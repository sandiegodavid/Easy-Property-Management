# Inventory and host commands

[Foundation guides](README.md) · [Schema catalog](../../database/README.md) · [Owning initializer usage](../../../application/database/README.md#h022-owning-runner-usage)

## Store ownership and initialization

The [Admin dictionary](../../database/admin-registry.md) and
[inventory dictionary](../../database/host-inventory.md) own column definitions.
All DDL is in owning `application/database/` resources, not runtime ORM creation,
a direct revision stamp, an alternate registry or a startup fallback.

| Store | Implemented boundary |
| --- | --- |
| Main Admin | Complete 13-table Pilot 0 structural closure, including local identity, operations, release-assignment and monitoring dependencies. Initialization seeds no operator, session or qualified release. |
| Host inventory | Host identity, retained principals, resource bindings, project assignments, ingress authority and host receipts; current generation, immutable intent/result and allocation constraints. |
| Hosted access and separate recovery stores | Owning baselines/initializers remain unavailable until identity and recovery delivery. Discovery or a scaffold is not readiness. |

Main Admin includes `control_meta`, `storage_policies`, `qualified_releases`,
`component_deployments`, `operators`, `invitations`, `admin_principals`,
`admin_sessions`, `login_handoffs`, `operations`, `operation_events`, `admin_audit`
and `workspace_recovery_status`. The nullable assignment-operation reference permits
insert-assignment → insert-operation → link-operation in one owning transaction;
it does not permit disabling foreign keys. Recovery tables belong in their separate store.

Resource discovery checks owning identity/namespace, canonical installed paths, sole
current baseline, declared inventory and shared definitions. A missing, broken or
empty-upgrade resource rejects before reserving a destination. The initializer
exclusively reserves a fresh 0600 regular file in a canonical caller-owned private
directory. Links, FIFOs, unsafe paths and existing empty/partial files reject.

DDL/version writes share a real SQLite transaction. Failure rolls back and retains
the reserved file for inspection, rather than silently adopting/deleting it. Matching
reinit is read-only: compare the complete `sqlite_schema`, checks, FKs, indexes and
triggers against the same baseline run in memory; run FK and quick checks without
mutation. A revision string alone is insufficient. Attached stores/temp objects reject.
Raw Alembic upgrade/stamp/offline commands are not alternate owning runners.

Helpers preserve caller-owned connection/transaction ownership. Separate protected
`DeploymentMetadata`/`HostMetadata` bindings initialize only their singleton, return
unchanged for exact retries and reject mismatches. Immutable intent/terminal receipt,
append-only audit/event and retained-allocation triggers also reject replacement
bypasses. Project release needs recorded retirement and verified cleanup.

## Authority and original-effect identity

The public Admin process has neither host files nor Docker access. A separate restricted
control client resolves the **original** parent intent through an authenticated
Admin-owned port. HostAgent independently checks that parent and exact requested child.
Production admission lookup remains an owning application prerequisite; a DTO,
configuration file or synthetic fixture is not authority.

Child UUID/key derivation includes original parent scope, effect kind, binding,
generation and declared slot. Fresh requests also check deployment/workspace,
expected revision, current access epoch and resolved-input hash. Private commands
accept registered identities, not arbitrary paths, shell commands, image tags, actor
claims or OS UIDs. Current fences remain outside historical receipt state, so an
unseen stale enable cannot evade a newer deny.

The receipt retains the canonical bounded non-secret request and resolved
image/limits/origin inputs. Matching retries return the original terminal result or
inspect an uncertain original effect; changed semantics conflict. Mutable assignments
cannot reconstruct an earlier request or allocate a second identity after a lost reply.

## Transaction and external-effect workflow

1. Authenticate and resolve current intent. Probe system **and runtime/container**
   identity collisions outside the SQLite writer; missing probes do not allocate.
2. In one short inventory transaction, reserve persisted UID/GID, three unique
   projects, binding, pending original receipt and held ingress. Commit before any
   filesystem, Docker or gateway effect.
3. Serialize effects with a protected cross-process flock, independently of SQLite.
   Busy means unavailable, with the same original identity retained for retry.
4. Perform the registered effect and inspect actual ownership/state.
5. Commit verified receipt/result/projection observations together in inventory.
   Admin owns its separate parent/audit transaction; no cross-store atomicity is implied.

Timeout, wrong proof/target or crash is unknown, not verified success/rejection.
Failed result commits retain allocations; new work stays behind unresolved effects.
Containment stop/deny remains available. Retirement requires stopped runtime plus
current verified external denial. Principals/projects are not automatically recycled.

Ingress apply targets the sealed next verification revision. Load **and inspect**
that exact state, generation, binding and revision before committing observation.
An uncertain retry inspects the same pending target; it does not create a new deny
removal. Historical terminal results cannot dispatch obsolete effects or grant access.
Positive eligibility and restore stage/switch remain unavailable until their owning
identity/provisioning/recovery composition is delivered.

## Protected transport

The Unix protocol is version 1, length-prefixed and bounded to 32 KiB. Only `execute`
and `original` accept a typed `HostEffect`. Kernel peer identity is checked before
parsing/admission: Linux uses `SO_PEERCRED`; Mac tests use `getpeereid`. The client
also verifies the agent UID before sending intent and checks returned child/key/hash/
binding. A JSON actor cannot override the separate restricted-client principal.

Malformed, duplicate-key, oversize, unknown-version and generic commands reject.
Safe responses omit paths, allocation UIDs, raw exceptions and credentials. The
listener requires a canonical agent-owned private directory, restricted client group
and 0660 socket; it never unlinks/takes over an existing socket. There is no public
HTTP initializer or general shell-control endpoint.

## Code and evidence

Code: [dispatch contracts](../../../application/apps/server/app/modules/host_agent/application/dispatch.py),
[effect identity](../../../application/apps/server/app/modules/host_agent/application/effect_contracts.py),
[service](../../../application/apps/server/app/modules/host_agent/application/service.py),
[inventory](../../../application/apps/server/app/modules/host_agent/infrastructure/inventory.py),
[Unix transport](../../../application/apps/server/app/modules/host_agent/infrastructure/unix_transport.py),
[owning schema runner](../../../application/apps/server/app/platform/hosted_schema.py).

The [structural evidence](../qualification/reports/HOSTED_MVP_H02_2_VALIDATION.json)
and [effect evidence](../qualification/reports/HOSTED_MVP_H02_3_VALIDATION.json)
retain original transactions, source pins and query bounds. Structural validation
used at most six target-connection statements in its tested case; original-result
lookup stayed unchanged after adding another operator. These are specific component
observations, not a general large-host or browser-directory budget. Current combined
regressions and remaining integration gates are in [qualification](qualification-and-handoff.md).
