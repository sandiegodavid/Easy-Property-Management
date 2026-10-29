# Read-only Admin console — Slice 4

Repository delivery, October 28, 2026. This is not a live deployment, A/B
re-acceptance, third-operator qualification or permission to change tunnel policy.
Use the existing [private installation and launcher](HOSTED_ADMIN_AUTHORITY.md).

## Pages and scope

- `/operators` (also `/`): registered operator directory, capacity and tunnel
  observations, recovery availability and recorded qualification ceiling.
- `/operators/{registered-key}`: intended email/hostname, access window and
  capability profile, runtime/mount checks, separate recovery checks and recent
  operations. Access enabled does not claim onboarding acceptance or online presence.
- `/operations` and `/operations/{operation-id}`: bounded recent operations,
  original correlation reference, actor/reason, status, checked steps and audit times.
  Reload and reconnect only read the original operation; they never dispatch it.
- `/qualification`: recorded ceiling, up to 20 recent plans and 200 evidence
  records with observed/expiry times. The complete evidence history remains in
  the private tooling. A registered A/B allocation is not qualification evidence.
- `/discrepancies`: registered versus discovered instance keys. Unregistered C
  remains unregistered/unqualified. Exact runtime/configuration checks appear in
  the corresponding registered detail. No automatic adoption, deletion or repair.

Add operator is visibly disabled with an explanation. There are no browser
approval, activation, invitation, renew, cancel/resume or resource-mutation
controls in this slice. Use the source-owned private operation procedure where
already supported. Provisioning and lifecycle/recovery completion remain Slices 5–6.

## Observations and limits

The HTTP process reads only typed broker projections. It never opens host inventory,
access stores or business databases. The broker composes the existing protected
inventory and source runner through a small read port. Directory pages select
50 of at most 1,000 registered records using one inventory read and never run
source/provider checks per row. Access/service/recovery states already observed
in details can appear in the directory; unobserved or stale values stay explicit.
Directory filters apply to the displayed page, as their label states.
RPC requests remain bounded to 16 KiB; typed read responses are capped at 256 KiB
so a full bounded directory/evidence page fits without widening the request boundary.

Host and selected-instance sections collect independently on two bounded background
workers, with at most eight queued/in-flight observations. Duplicate reads coalesce;
collection retries no sooner than 30 seconds. No database transaction spans a source
or systemd check. Configuration dates and source access state share the private
maintenance lock. All returned facts use closed schemas; paths, session/subject
material, private report payloads and raw exception text are excluded.

The browser checks normal read pages every 30 seconds, observation sections every
five seconds and active operations every two seconds. Completed operations slow to
30 seconds; failures back off to at most 60 seconds. Hidden pages stop polling.
Every observed section identifies its state and exact last verification/check time,
shown in browser-local time with the zone. After failure, the last verified data
and its original time remain visible as stale. The cache is disposable: restarting
the broker starts unknown and never manufactures fresh evidence from old prose.

Capacity comes from the signed, current-inventory verifier report described in
[the engine runbook](HOSTED_ADMIN_OPERATIONS.md). Uncommitted memory is explicitly
reservation headroom, not measured free RAM. Missing measured memory or Access-seat
readings remain unknown. Tunnel process and boot enablement are separate observations
of `epm-cloudflared.service`; neither proves public Access enforcement or reboot
acceptance. Local archive, off-host read-back, restore drill and approved-binding
verification are distinct contracts. Until Slice 6 installs their trusted registry,
they remain unverified; no file timestamp is promoted into recovery proof.

## Build and installation

`npm run build:admin` builds the independent React entry into `apps/web/dist-admin`.
`npm run package:web` builds both frontends and includes the private pair only at
`app/admin_build/admin.js` and `admin.css` in the wheel. The business SPA has no Admin
entry, imports or routes. The private listener authenticates its fixed asset routes;
unknown assets are rejected. `build_wheel.sh` checks that both builds are present.

Install the reviewed wheel and the new root-protected `admin_observations.py`
alongside `admin_console.py`, `host_admin.py` and `host_inventory.py`. Keep the HTTP
service's existing filesystem isolation. Do not install the disposable browser
fixture. There is no Admin SQL schema change for this slice and no compatibility
migration or automatic rewrite of an existing host.

Native sign-in preserves only an allowlisted canonical return path. Credentials
remain POST-only and out of URL/storage/traces. Session expiry offers sign-in at
the same detail/operation route; signing in never repeats a command. The existing
host/origin/Fetch-Metadata, HttpOnly cookies and CSRF checks remain; CSP permits only
same-origin external scripts/styles/connections, with no inline scripts or unsafe eval.

## Focused verification matrix

| Area | Proof |
| --- | --- |
| Happy path | Overview, A/B details, qualification/discrepancy views, original operation steps/history after reload |
| Invalid combinations | Unregistered selector, invalid section/page, unknown asset, external return path and wrong origin fail closed |
| Retry/idempotency | Observation coalescing/backoff; operation polling performs no POST or admission; expired session returns to the same detail |
| Concurrency/rollback | Independent section failure, hard worker/queue bounds, stale retained values and original timestamps; no business mutation/rollback introduced |
| Persistence/schema | Existing engine history and ceiling are read without schema change; absent facts never become zero/healthy; cache restart is unknown |
| Backup/restore | No observation cache, session or credential is added to a recovery artifact; existing control-store restore fencing is covered by focused engine tests |
| Query budget | One inventory read with no source/provider fan-out; fixed authentication-query budget for 1/100/200 registered records; 50-row page bound |
| Privacy/isolation | Closed projections, private authenticated assets, public route rejection, no browser token storage or credential-bearing URL |
| Browser/accessibility | Native sign-in and canonical return, narrow keyboard navigation, both appearances, retained stale data, hidden-tab polling, session expiry and read-only operation progression |

Run from `application/`: focused `hosted_admin` tests, the host inventory/maintenance
and launcher tests, source-command tests and `platform/tests/test_web_delivery.py`;
`npm run test:admin`; changed-file Ruff check/format; frontend lint/format/typecheck;
and `npm run package:web`. These tests use disposable fixtures, not the live host.

Validation on October 28, 2026: **272 focused Python tests and 10 Admin Playwright
tests passed**. Changed Python files passed Ruff check and format validation;
frontend lint, formatting and type checking passed. Both frontend builds and
wheel packaging passed; desktop/light and narrow/dark screenshots were inspected.
The public build retains its existing large-chunk warning; this slice adds a
separate private bundle. No live installation, provider call or qualification run
was performed.
