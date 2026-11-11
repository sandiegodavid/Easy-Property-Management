# Protected hosted launch and unavailable status

[Tool source](../../../application/deploy/hosted-mvp/launch) · [Foundation guides](../foundation/README.md)

Hosted launch supplies fixed Admin and Operator entry points and a safe unavailable page.
It does not enable business routes, login, customer admission or the Admin portal.
H03/H04 own those workflows; H05 owns the missing recovery stores.
[Host setup](gcp-host-setup.md) covers protected infrastructure delivery. Local `python -m app serve` remains unchanged.

## Launch modes

The Operator image uses `app.hosted_candidates.operator`; Admin uses
`app.hosted_candidates.admin`. The component cannot be selected by an HTTP request.
Each invocation first verifies the installed component inventory and architecture.

- `--verify`: inspect the installed candidate and exit; no database or listener.
- `--health-only`: serve process liveness and the safe unavailable page without
  loading any workspace or source store. This remains the candidate images' default.
- `--binding /control/launch.json`: validate explicit protected launch inputs and
  existing owned data, then serve the unavailable page. There is no fallback when
  the binding is absent or invalid. It cannot be combined with `--health-only`.

These are arguments for the guarded runtime, not a way to bypass HostAgent,
network containment or the single supervised restart owner. Existing candidate
images need rebuilding to include this code; earlier image digests do not attest it.
No images were promoted or ingress enabled by this work.

## Protected binding

The host must deliver a bounded, root-owned, regular, single-link JSON file on a
read-only mount. It must not be group/world writable or reached through symlinks.
Configuration is never taken from browser query parameters, forwarded headers,
local configuration defaults, environment workspace locators or legacy expiry files.

Operator example (synthetic IDs):

```json
{
  "version": 1,
  "component": "operator",
  "deployment_id": "00000000-0000-4000-8000-000000000001",
  "operator_id": "00000000-0000-4000-8000-000000000002",
  "workspace_id": "00000000-0000-4000-8000-000000000003",
  "resource_generation": 1,
  "origin": "https://operator.example.com",
  "workspace_path": "/workspace",
  "control_path": "/control"
}
```

Admin uses `component: "admin"`, its exact registered HTTPS origin and protected
control mount. Omit the three Operator fields (`operator_id`, `workspace_id`,
`workspace_path`); Admin cannot select an Operator workspace. Duplicate/extra JSON
keys, noncanonical IDs, aliases and overlapping workspace/control trees reject.
The host must derive these values from its real owning records. This file is a
binding, not access authority or evidence that its generation is current.

Both components use the pre-created, private, runtime-UID-owned
`<control_path>/writer.lock`. Startup never creates, removes or substitutes the
lock, and never uses the local parent-directory lock. It releases the lock on
failed/unavailable validation. The unavailable listener does not retain a business
writer, run background jobs or initialize any store.

Operator validates the existing workspace schema/data and exact workspace ID under
the lock. Admin validates the existing main-Admin schema and `control_meta` deployment
ID. Hosted stores are existing private files at `<control_path>/data/<store>.sqlite`
and are validated through their owning resources using read-only SQLite transactions.
Missing resources/files are unavailable, never implicitly initialized or stamped.
Today hosted-access/recovery/Admin-recovery resources remain unavailable. Even
structural validation success cannot authorize a ready application: H03/H04 must
compose real source authority, and H05 must deliver recovery requirements.

## Safe status and retry behavior

- `/health/live`: process liveness only, HTTP 200. It is independent of workspace
  readiness and is intended for the private container health probe.
- `/health/ready`, `/api/*`, unknown routes and every mutating method: HTTP 503,
  `ready: false`. No business handler is registered or invoked.
- `/`, `/status` and HTML document navigations outside `/api/` and `/health/`:
  HTTP 503 unavailable page. `/status.css` serves its local style. Deep-link query
  values are not echoed or replayed.
- In binding mode, document/read requests require the exact registered Host;
  forwarded-host headers cannot supply or override it. H02.6's external gateway
  continues to deny all business ingress independently.

Responses are not cached. Unavailable responses advertise a 30-second retry hint;
there is no polling, timer, script, form or command replay. The keyboard-accessible
"Check availability again" link makes one GET to `/`, dropping query data. It does
not clear another tab's form or claim that an interrupted submission failed/succeeded.
The timestamp describes this availability response, never record freshness or a
verified access/recovery observation. Responses omit paths, IDs, exceptions, schema
versions, proofs and account state. The page adapts to light/dark appearance and
narrow widths; it is not a placeholder login or Admin application.

## Focused verification

From `application/`:

```sh
.venv/bin/python -m pytest \
  apps/server/app/platform/tests/test_hosted_launch.py \
  apps/server/app/platform/tests/test_hosted_artifacts.py \
  apps/server/app/platform/tests/test_browser_transport.py \
  apps/server/app/modules/host_agent/tests/test_runtime_effects.py -q
npx playwright test --config playwright.hosted-status.config.ts
```

The browser harness is loopback-only and uses the real status renderer. It cannot
start a hosted application. Native Docker/GCP qualification, protected binding
publication and current ingress authority remain the owning later gates.
