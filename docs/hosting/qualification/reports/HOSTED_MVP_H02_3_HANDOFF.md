# H02.3 — Restricted host-agent command boundary

H02.3 implements private typed dispatch, inventory reservations and original-effect
reconciliation on `hosted_mvp`. It starts at
`b3a8a452` (the H02.1/H02.2 implementation and schema-review fix).
This is component validation, not native Linux, Docker, gateway or GCP qualification.

## Delivered boundary

- `host_agent/application/dispatch.py` defines the versioned child-effect input,
  authenticated-admission port, pinned resource inputs, private allocation,
  verified observation and safe receipt. It reuses the H01 action vocabulary and
  H02.1 deterministic parent/child identity instead of accepting arbitrary child keys.
- `HostEffect.effect.parent` is an ORIGINAL parent reference, not a proposed parent
  operation ID. The restricted client must resolve the original through Admin first.
  The authenticated admission adapter must independently verify that reference and
  exact requested child. The agent derives the child ID/key; no proposed child ID
  can select a second identity. Replays of an identical request return its retained
  original child receipt; changed parameters under its derived key conflict.
- Resource effects pin the SHA-256 of typed resolved inputs. The receipt preserves
  both the canonical command and its resolved image/physical-limit/origin inputs.
  Recovery never reconstructs them from changed release/profile assignments. No
  shell, path, image tag, actor or OS UID is accepted in the private wire command.
- `host_agent/infrastructure/inventory.py` uses only the already initialized owning
  inventory. It pins the private file and host/deployment/filesystem metadata, rejects
  missing/replaced stores, and uses H02.2 structural validation and reflected tables.
  It contains no DDL, creator, fallback registry or cross-store connection.
- Preparation reserves a persisted collision-checked UID/GID, three unique projects,
  the registered binding, original pending receipt and held ingress authority in one
  short inventory transaction. Failure rolls all of these back. No filesystem/Docker/
  gateway effect occurs before its commit. Original child intent is immutable under
  the existing resource-owned triggers; no additional schema is introduced here.
- A protected cross-process flock serializes agent effects, including competing
  denies, without holding a SQLite writer across external work. A busy lock fails
  unavailable; callers check/retry their original identity. The configured identity
  collision probe runs outside the writer too; missing/failed probe never allocates.
  The production probe must include system AND other runtime/container identities.
  There is deliberately no empty-set or NSS-only production fallback.
- Verified initialization/repair observations record the actual container reference
  with the pinned image digest in the same receipt/result transaction.
- The effect driver receives only registered allocation identities and the immutable
  resolved inputs, including any gateway projection revision to apply and inspect.
  Timeout, provider error, wrong proof/target or crash cannot prove rejection or
  success. Reservations remain pending/unknown, and subsequent calls inspect the
  original effect rather than reapplying it. Failed result/receipt commit propagates;
  it does not release allocations or fabricate rollback of an external effect.
- New resource work is blocked behind unresolved effects. Stop and deny remain
  available for containment. Retirement requires a stopped runtime and current
  verified external denial; UID/project mappings remain retained. No automatic cleanup
  or allocation recycling was introduced.
- Each fresh request checks deployment, workspace, binding generation, expected
  revision and current inventory access fence, even with an unseen key. New held/
  blocked ingress intent and fence commit before gateway work. Old receipts cannot
  dispatch an obsolete effect or clear a newer deny. Historical terminal receipts
  remain original results, not new authority.
- Eligibility/enable, restore stage and binding switch remain unavailable before
  effects. Private progress/receipts are not a claim that source revocation, identity
  readiness or the complete Admin disable workflow has completed.

Inventory receipts are the host-side audit evidence. Their pending reservation and
verified result/projection commit atomically within that store. The authenticated
Admin parent adapter owns its separate operation/audit transaction in H04; no host
call opens Admin's database or claims atomic audit across those two stores.

## Unix transport and native primitive seam

`unix_transport.py` provides a version-1, length-prefixed, at-most-32-KiB private
Unix call. The only methods are `execute` and `original`, each carrying a typed
`HostEffect`. Kernel peer credentials are checked before parsing or admission:
Linux uses `SO_PEERCRED`; local macOS tests use the OS `getpeereid` API. The protected
configured UID identifies the restricted control client, which must be a separate
principal from the public Admin process. JSON cannot supply or override that identity.
The restricted `invoke` client also verifies the agent's kernel peer UID before
sending intent and checks the returned child ID/key/hash/binding. Lost replies
remain unavailable; the original request stays the recovery identity.
Malformed/duplicate-key/oversize/unknown-version/generic-command inputs fail closed.
Responses contain only safe receipt values or stable codes, never allocator UIDs,
paths, raw provider exceptions or credentials. Timeouts bound incomplete calls.

The listener requires a canonical agent-owned protected directory, the restricted
client group, no group writes/world access, and a 0660 socket. It never unlinks/takes
over an existing socket. No HTTP/FastAPI route, production daemon, CLI bootstrap,
background scheduler or startup composition was registered in this slice. H02.7 will
compose the trusted host process and enforce its deployment identity/permissions.

`quota_targets.py` maps an inventory allocation and protected roots to the selectively
imported `ProjectBinding` primitive. Roots cannot overlap/escape; filesystem identity
must match. It performs no mkdir/chown/quota/ioctl/native invocation and grants no
readiness. H02.5 must use the imported `ProjectQuota` verification/mutation primitives
under the qualified sandbox before granting the UID write access. The imported
primitive sources and historical evidence remain unchanged.

## Gateway revision handoff

Ingress intent is first reserved at its next inventory revision. Verification is a
second revisioned inventory update, so the driver receives the sealed NEXT projection
revision for that verification commit. It must load AND inspect that exact revision,
state, binding and generation. Merely returning an evidence-shaped reference is not
proof. The returned `ingress_revision` must match the sealed value; otherwise the
receipt remains unknown. A crash before result commit retains the original pending
intent and the same next projection target for inspection, never a new deny-removal
request. The privileged serialization lock covers this interval.

H02.6 must implement and qualify this projection protocol, including config-load
failure, existing-connection containment and restart reconstruction. No gateway
operation executed here; component tests use an explicitly synthetic driver.

## Validation matrix

| Area | Evidence |
| --- | --- |
| Happy paths | Real owning SQLite resources; distinct operators/principals/projects; preparation, stopped runtime initialization, stop, limits, deny, retirement and safe original receipt. Explicit synthetic admission/effects only. |
| Invalid combinations | Unknown/changed/expired admission, expiration during reservation, wrong scope/generation/epoch, unavailable enable/restore, bad proof/target, unpinned inputs, unsafe quota roots, wrong/missing/replaced host store, unsupported wire method/version and forged JSON actor reject without unauthorized effects. |
| Idempotency/retry | Same child/key returns original; changed semantics conflict; crash/lost response leaves original pending/unknown and retries inspect only. Newer denial blocks unseen starts and stale historical mutations. |
| Transactions/rollback | Failed receipt insert or reservation commit leaves no UID/project/binding/ingress allocation; result/projection failure rolls back together; driver and collision-probe tests acquire an independent SQLite writer, proving no writer is held during their calls. |
| Persistence/schema | H02.2 exact schema/metadata checks; existing immutable/terminal receipt and uniqueness constraints; serialized allocation, collision skipping, project exhaustion and retained identities. No additional DDL. |
| Backup/restore handoff | Synthetic SQLite snapshot retains original receipts and allocations. No encrypted, off-host or authenticated restore proof; H05 stage/switch remains unavailable. |
| Query/N+1 | Indexed kind/key lookup and single-binding project/ingress queries. Original-result statement count is unchanged after adding another operator; no provider scan or whole-host filesystem walk on reads. Allocation inspects occupied IDs only when needed. |
| Transport | Real local Unix peer identity in both directions, wrong peer before admission/disclosure, bounded framing, duplicate-key rejection, lost reply, safe response and existing-socket preservation. Local macOS results do not establish Linux/root isolation. |

The [validation record](HOSTED_MVP_H02_3_VALIDATION.json) lists exact commands,
source hashes, platform and results. **573 focused tests passed**, including 53
new host-agent cases and 23 reused quota-primitive cases. Ruff check and format
check passed for all six new Python files (also checked the complete 13-file host-agent
module). Focused checks include H02.2 resources and H01
owning ports, proof validators and UI contracts. No frontend files changed; frontend
lint/typechecking and browser tests are not applicable. No full server suite ran.

## Repeat focused validation

From `application/`:

```bash
.venv/bin/ruff check apps/server/app/modules/host_agent
.venv/bin/ruff format --check apps/server/app/modules/host_agent
.venv/bin/python -m pytest apps/server/app/modules/host_agent/tests/test_agent.py apps/server/app/modules/hosted_admin/tests/test_project_quota.py apps/server/app/platform/tests/test_hosted_schema.py apps/server/app/platform/tests/test_schema_resources.py apps/server/app/platform/tests/test_hosted_effect_contracts.py apps/server/app/platform/tests/test_hosted_ports.py apps/server/app/platform/tests/test_hosted_proofs.py apps/server/app/platform/tests/test_hosted_ui_contracts.py -q --tb=short
```

The sandbox blocks filesystem Unix-socket binds; the focused run used approved local
execution permission for disposable private sockets. It did not run native quota
mutation, a Docker runtime or cloud effects. One wrong-peer fixture race was corrected:
an immediately rejected peer now waits for the denial without sending a body. Final
validation was 573 passed, 0 failed, 0 skipped in 28.08 seconds.

## Remaining owning gates

- H02.4 builds/stages installed artifacts and resolves the full Linux dependency lock.
- H02.5 implements qualified physical roots/quota, guarded runtime lifecycle and
  collision probing against the actual system/container namespace. H02.6 implements
  exact-host gateway effects and containment. The shipped `UnavailableEffects` port
  fails closed; no production Docker/gateway executor is silently substituted.
- H02.7 composes authenticated service dependencies and protected socket ownership;
  no default production adapter trusts caller DTOs. H04 supplies the live authenticated
  Admin-owned admission lookup. Synthetic admission implementations live only in tests.
- H02.8/H02.9 qualify root Linux peer/namespace behavior, current native sources,
  actual Docker/GCP effects and reboot. This slice did not inspect/reset a VM or
  change cloud resources. H03/H04 source/enable and H05 restore remain closed.
