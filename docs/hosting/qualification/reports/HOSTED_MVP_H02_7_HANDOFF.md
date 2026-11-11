# H02.7 fresh hosted launch and unavailable UI handoff

H02.7 is delivered within its component/browser scope on November 12, 2026, from
base commit `7bc7b841`. The [launch runbook](../../deployment/protected-launch.md)
contains the protected binding contract, fixed launch modes, routes and focused
reproduction commands. No live host, retained VM, user workspace or external account
was changed. Work is saved in the current checkout.

## Delivered

- Separate fixed Admin/Operator candidate entry points now distinguish explicit
  protected-binding startup from health-only inspection. Neither falls back to
  local configuration, old hosted expiry/loop-image composition or a test authority.
- Root-owned, bounded, non-linked protected JSON supplies identity, exact HTTPS
  origin, generation and canonical separate mount paths. HTTP and environment
  workspace values cannot select these inputs. Actual host publication and current
  source authority remain later-owner gates, not an inference from this file.
- Validation uses the existing stable control-tree writer lock and releases it on
  every unavailable/failure path. Existing Operator schema/data and workspace ID
  are validated under it. Main-Admin is read-only validated against its owning
  schema and protected deployment ID. No store, lock or schema is initialized by
  launch. Missing owned access/recovery resources remain unavailable.
- The safe, self-contained unavailable page supports keyboard refresh, light/dark
  appearance and 320-pixel layouts. It preserves other open forms and explicitly
  declines to infer any earlier submission outcome. A refresh is one GET only;
  no script, polling, form, command replay or source-record read is attached.
- Liveness remains distinct from readiness. Exact Host is enforced for bound read
  requests; forwarding headers do not override it. Business routes stay unregistered,
  readiness stays false, and existing independent external ingress denial remains.
  Responses are uncached, include a retry hint and expose no paths, IDs, versions,
  raw exceptions or authority/proof details. Availability timestamps do not claim
  record freshness.
- Candidate inventories now require the new runtime modules. The installed-candidate
  probe understands the HTML unavailable page and safe JSON health/status contract;
  the replaced handler factory and JSON-only root assumption were removed.
  Production local launch and transport code were not changed.

## Focused validation matrix

| Area | Evidence and result |
| --- | --- |
| Happy paths | Real initialized workspace identity, structural Admin plus bound metadata, fixed launch dispatch, health-only isolation and actual HTTP responses pass. All normal startup paths remain unavailable without the later composition. |
| Invalid combinations | Missing/wrong component or Operator identity, old expiry keys, malformed origins, relative/overlapping/symlink paths, non-root/writable config and duplicate keys reject. Wrong workspace/deployment identity and absent store files reject without creation. |
| Retry/idempotency | One keyboard refresh issues one GET. No polling, mutating dispatch or command replay. Existing guarded-runtime original-effect tests remain passing. |
| Failure/rollback | Stable lock excludes a second opener and is released after failure. Private validation exceptions cannot enable business routes. No local parent lock is created; existing business-replacement lock tests pass. |
| Persistence/schema | Real owning structural validation and read-only deployment binding checks; unchanged store bytes after unavailable validation; absent recovery/access resources create no destination. No DDL/migration added. |
| Backup/restore | No backup format or restore operation changed. Existing stable-lock-across-business-replacement regression passes; H05 recovery qualification remains open. |
| Query budget | Status/refresh dispatches no source query or API command. Startup does explicit one-time owning validation, not a directory/per-record projection or repeated browser scan. |
| Ingress | Two existing gateway regressions prove new binding held closed and local flags/unknown eligibility unable to generate positive routes. |
| Browser/accessibility | Four Chromium tests: light/dark, 320/1280 widths, page title, semantic main/heading, visible UTC availability time, retained-input guidance, property deep-link interstitials without echoing query data, no horizontal overflow, native keyboard refresh and no API/replay requests. |

Commands run from `application/`:

```sh
.venv/bin/python -m pytest \
  apps/server/app/platform/tests/test_hosted_launch.py \
  apps/server/app/platform/tests/test_hosted_artifacts.py \
  apps/server/app/platform/tests/test_browser_transport.py \
  apps/server/app/modules/host_agent/tests/test_runtime_effects.py -q
# 104 passed

.venv/bin/python -m pytest \
  apps/server/app/modules/host_agent/tests/test_gateway.py::test_new_binding_is_held_and_config_is_exact_closed_projection \
  apps/server/app/modules/host_agent/tests/test_gateway.py::test_local_flags_or_unknown_eligibility_never_create_positive_routes -q
# 2 passed

npx playwright test --config playwright.hosted-status.config.ts
# 4 passed

npm run lint
npm run format:check
npm run typecheck
# All passed; type checking includes 194 source files and the new browser test/config.
```

After adding document deep-link handling, the 19 launch/probe cases and all four browser cases were rerun successfully.

Ruff check and format check passed for all nine changed Python files using
`application/pyproject.toml`. `git diff --check` passed. No full suite ran.
The socket tests required loopback access outside the restricted sandbox. Initial
local failures (sandbox bind denial and a new test helper's incorrect context-manager
usage) were corrected/re-run; they are not unresolved product failures. The gateway
README's existing table was formatted while adding its launch handoff link.

## Remaining owning gates

H03/H04 must supply real identity, access, eligibility and login/Admin/Operator
application composition; structural stores, protected IDs and liveness do not grant
admission. H05 must deliver recovery-owned resources and behavior. H02.8/H02.9 must
rebuild and requalify changed candidates, deliver protected host bindings and prove
native Docker/GCP behavior. This component/browser pass does not renew an older image
or native qualification, promote a release or authorize enabling ingress. No placeholder
Admin portal or permissive test adapter was shipped.
