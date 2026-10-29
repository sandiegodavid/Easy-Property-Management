# Private Admin authority — Slice 2

Repository implementation, October 28, 2026. This runbook describes installation and qualification; it does not record a deployment. Keep the existing operator capacity ceiling and tunnel policy. The full design is [Hosted demo administration](../design/HOSTED_DEMO_ADMIN_DESIGN.md); inventory and maintenance setup remain in [registered instance tooling](HOSTED_INSTANCE_TOOLING.md).

## What is available

The separate private listener provides sign-in/sign-out, session checks, action authorization, exact command submission/result lookup and bounded source access status. Slice 4 adds the [read-only management console](HOSTED_ADMIN_CONSOLE.md); Slice 3 supplies the [durable engine and private qualification commands](HOSTED_ADMIN_OPERATIONS.md). Provisioning, ordinary onboarding activation, coordinated renewal and trusted recovery completion remain their named later slices.

The HTTP service has no business routes, source databases, provider credentials or authority-store access. It talks to the root broker through a protected Unix socket. The broker accepts its dedicated Unix peer, validates protected sessions and dispatches fixed source commands as the registered service user. A compromised HTTP process can exercise its admitted session authority; typed RPC does not prove independent human approval. Root remains trusted.

The browser uses a dedicated hostname, `epm-admin.localhost`, over a loopback-only IAP forward. Plain HTTP is the accepted initial profile: cookies are HttpOnly, host-only and SameSite=Strict, **not Secure**. Cookies are not port-isolated. Do not use this hostname for other local services, bind to a LAN address, publish it through Cloudflare, or infer that an IAP logout closes an existing tunnel. Processes controlling the administrator's computer are inside this profile's threat boundary.

## Private installation prerequisites

Perform installation only through the deployment owner's existing authorized IAP/SSH/root path. Review the exact wheel/tool digests first; do not run these steps from the operator UI.

1. Adopt the intended instances through Slice 1 and reconcile discrepancies. Their allocations, service users, configuration paths, ports and releases must already be registered. Do not register a fabricated capacity qualification or a copied workspace identity.
2. Select an explicit unused nonprivileged Admin port. Pin it in the HTTP unit and use the same port in the launcher; there is no implicit production port. Qualify that `epm-admin.localhost` resolves only to loopback in the administrator's browser. Stop if the chosen local port is occupied.
3. Provision the non-login system account/group `epm-admin-http`, with no operator group membership, sudo privileges, secrets or writable application code. Create `/var/lib/epm-admin/authority` as root:root mode 0700. Keep the Slice 1 control directory root-private. systemd creates `/run/epm-admin` root:`epm-admin-http` mode 0750; the broker socket is root:`epm-admin-http` mode 0660.
4. Install the reviewed wheel (including the separate private Admin build) into a root-owned `/opt/epm/admin/venv`. Install `admin_console.py` and `admin_observations.py` beside the protected Slice 1 `host_admin.py` and `host_inventory.py` in `/opt/epm/admin`, root-owned and not writable by group/others. The directory is traversable/readable, not writable, by the HTTP UID. All ancestor directories must be protected. Source releases must include the current `command_cli` and current source access schema.
5. This is a greenfield schema. Preserve existing recovery material and follow the approved source rollout procedure before selecting a current-format access store. There is no compatibility migration or automatic rewrite of a live access database. An old/invalid source schema fails closed. Never discard a live store to make a test pass.
6. Initialize the single stable administrator identity once, privately:

   ```bash
   sudo /opt/epm/admin/venv/bin/python -I /opt/epm/admin/admin_console.py initialize --identity DEPLOYMENT_OWNER_REFERENCE
   ```

   The reference is the pre-provisioned identity label, not an operator email header or browser claim. Initialization refuses an existing file.
7. Install the reviewed `epm-admin-broker.service` and `epm-admin-http.service` templates. Replace `ADMIN_PORT` in the HTTP template. Add an HTTP-unit sandbox drop-in listing each registered operator root in `InaccessiblePaths`, alongside the template's hidden authority/configuration/backup paths. HTTP must have no readable business data even though the source runner, under the target UID, validates it for grant actions. Qualify effective units/drop-ins and Unix permissions, not just the template text.
8. Start the broker and listener explicitly after checking those inputs. There is no public ingress or operator-menu entry. Do not install `admin_browser_server.py`: its synthetic control endpoints belong only to disposable tests.

Retain the installed wheel/tool/unit digests and effective port/Unix identities with acceptance evidence. The root broker's source runner accepts only the existing adopted resource profile; later qualified profiles need their registered qualification integration. Fixed `runuser -u USER -- argv` dispatch avoids a shell; the upstream [util-linux implementation](https://github.com/util-linux/util-linux/blob/master/login-utils/su-common.c) keeps this form in the caller’s session. The adapter starts a dedicated process group and kills/waits for it on timeout before releasing authority and maintenance locks; systemd also stops the broker’s whole control group. Qualify the installed util-linux/PAM behavior. It checks effective service identity, registered release/configuration/port/profile, active state and installed release evidence before grant actions. Source workspace validation runs as the service user. Disable/revoke and read-only status do not depend on a healthy business workspace.

## Connect and sign out

From the Mac, with existing Google authentication and approved IAP/SSH access:

```bash
application/scripts/epm-admin-mac.sh PROJECT ZONE VM INSTALLED_ADMIN_PORT
```

The launcher binds `127.0.0.1` only, refuses forward collisions, waits for the protected origin, opens the browser and prints a one-use sign-in credential through SSH. Paste just that credential into the labeled form. Do not put it in a URL, shell argument, environment variable, browser storage, screenshot, transcript or support log. The launcher terminal must remain open. Exclude credential-issuer stdout from terminal recording and sudo I/O capture; keep the root audit metadata, never the printed grant. The credential expires after five minutes and cannot be reused. A failed connection requires a fresh launcher credential, not an operator cookie.

After sign-in, session cookies stay host-only and HttpOnly; the browser receives CSRF only through its protected session response/form. Native POSTs redirect to the signed-in page so refresh does not resubmit a credential. The same-origin referrer policy preserves the exact Origin header on native form posts while withholding cross-site referrers; no credential is carried in a URL. Unsafe requests require exact Host/Origin and CSRF. Cross-site Fetch Metadata, forwarded headers, CORS and query-string credentials are rejected. Responses are not cached; access logging is disabled.

Sessions expire after thirty minutes idle or eight hours absolute. Sign out revokes the browser session and clears its cookies. Disconnecting IAP, expiry or sign-out does **not** cancel an admitted command. Reconnect and retrieve its original operation; do not silently resubmit or change its target. A private administrator-identity revocation fences old-generation work, including after identity restoration.

## Typed command contract and recovery

The protected JSON endpoints are `POST /reauthenticate`, `/commands`, `/lookup` and `/source-status`, with the session cookie, exact Origin and `X-Epm-Admin-Csrf`. `GET /session` provides the current identity. These are a private application boundary for later Admin UI composition, not operator APIs or a browser shell.

- `/source-status` accepts only a registered `instance` key. It returns administrative/binding revisions, fence, generation, active state, whether the pinned configuration matches, and at most sixteen exact pending enrollment references. It returns no business records, session secrets or private paths.
- A command contains a canonical `operation_id`, registered `instance`, fixed `action`, `expected_revision`, `expected_binding_revision`, `fence`, bounded reason and `confirmed: true`. Approve/rebind also require the exact pending `subject` and `enrollment_received_at`. No user, database path, unit, executable, environment or administrator identity is accepted from the browser.
- Disable/revoke require the valid session, CSRF, reason and confirmation. They need no new SSH grant. Approve/rebind/enable require a fresh one-use action grant; the private `action-grant` command reads the **exact reviewed command JSON from stdin**, and prints only the grant. It cannot submit the command. The console exchanges it at `/reauthenticate`; an explicit `/commands` confirmation is still required. The authorization expires after five minutes, is session/request-bound, and is consumed atomically with admission.
- Approve/rebind remain identity-only and leave access blocked. Source enable has no installed recovery/acceptance checker in Slice 2 and returns `hosted_recovery_required`; there is no browser switch to bypass it. Ordinary onboarding completion/renewal belong to Slice 6. Existing private emergency activation is a separately audited recovery seam, not a console capability.
- The root admission pins the original allocation, source revision and deployment/local configuration digests. A repeated command key with changed content conflicts. Fixed source commands atomically apply the access mutation, record safe audit and retain the original receipt. Duplicate disable/revoke cannot advance generation twice. Changed binding configuration blocks new grants/sessions until explicitly reconciled, while containment remains available. Restoring business history advances the binding/fence and clears old access.
- `/lookup` accepts the original `operation_id`. A pending result does not mean nothing happened. Explicitly retry the original unchanged command with the same key after reconnecting: if the source committed before the control result was recorded, its exact receipt is read before another mutation. Lookup can reconcile through a later source revision only when the original allocation/operator/workspace/store identity remains unchanged; it cannot follow another allocation. Reconciliation itself grants no access.
- Shared private maintenance locking and unreconciled Slice 1 operations block conflicting source mutation. Root intervention still uses Slice 1's recorded reconciliation path. Do not change allocation or invent a new key to escape an unknown result.

Root recovery commands, through the same allowlisted private SSH path:

```bash
sudo /opt/epm/admin/venv/bin/python -I /opt/epm/admin/admin_console.py revoke-identity
sudo /opt/epm/admin/venv/bin/python -I /opt/epm/admin/admin_console.py restore-identity
```

Revocation disables the identity, revokes sessions/grants and fences admitted work. Restoration is explicit root recovery: it advances generation again and never revives old sessions/grants/work. New work requires new sign-in and authorization. Resuming fenced orchestration with a newly reviewed authority is the later durable-engine slice, not an automatic consequence of restoration. Restrict sudo to exact reviewed helper actions for the pre-approved SSH administrator; do not grant the HTTP or operator account sudo or arbitrary helper arguments.

## Focused validation matrix

| Area | Repository proof / remaining deployment gate |
| --- | --- |
| Happy path | Native keyboard sign-in, reload, sign-out; bounded status; identity-only approval; fixed target-UID command dispatch |
| Invalid combinations | Wrong Host/Origin/CSRF/peer, operator cookie, unknown method/path/environment, invalid/used/expired grant, changed enrollment or source configuration, inactive/mismatched runtime |
| HTTP problem contract | Typed bounds return 413; malformed typed fields return 422. JSON errors use `detail.code` and `detail.message` with fixed safe prose, never private input or exception text; invalid requests do not reach the broker. Native sign-in authentication errors remain human-readable HTML |
| Idempotency/retry | Exact one-use authorization/admission; unchanged original receipts; changed intent conflict; lost control-result recovery without a second generation change or allocation switch |
| Transaction rollback | Source audit failure rolls back mutation/receipt; admission failure cannot consume authorization; control commit failure leaves the original source receipt recoverable |
| Persistence/schema | Exact greenfield schemas; immutable source audit/receipts and admission intent/result; malformed source history rejected; separate binding revision/fence/session generation |
| Backup/restore | Restore marker advances source binding/fence and invalidates old access; no Admin/source sessions or grants are added to portable business archives. Host-control recovery artifact remains Slice 3 |
| Query bounds | Status uses fixed set-based queries and at most sixteen enrollment references; no business/provider reads in HTTP or per-item remote calls |
| Continuity | Expiry/logout retain admitted work; new login can look up its result; identity revocation/restoration never revives old-generation dispatch |
| Installation/isolation | Unit seams cover fixed argv and peer denial. Actual Linux UID separation/runuser, effective sandbox, real IAP/hostname/cookie profile, restart/socket cleanup and live A/B acceptance must be qualified on the installed release |

Run only this boundary's tests from `application/`:

```bash
PYTHONPATH=apps/server:. .venv/bin/pytest \
  apps/server/app/modules/hosted_admin/tests \
  apps/server/app/modules/hosted_access/tests \
  scripts/tests/test_admin_launcher.py \
  scripts/tests/test_host_admin.py scripts/tests/test_host_inventory.py \
  scripts/tests/test_release_wizards.py scripts/tests/test_release_cleanup.py \
  scripts/tests/test_release_demo.py -q -rs
npm run test:admin
```

The browser server creates a disposable authority store and uses synthetic adapter results. It proves the real HTTP/form/cookie behavior, not Linux privilege separation or live source admission. Playwright traces are disabled to avoid recording even test credentials. On unsupported peer-credential platforms the production broker fails closed; macOS unit tests are not Linux qualification. The existing Linux quota-volume test also requires explicitly provisioned disposable infrastructure. No live acceptance is implied by skipped infrastructure checks.

Repository validation on October 28, 2026: **386 focused Python tests passed, 1 infrastructure test skipped; all 3 private Admin Playwright tests passed**. The skip requires an explicitly provisioned disposable Linux quota volume. Changed-file Ruff check/format, Python 3.12 syntax checks, launcher shell syntax, frontend lint/format/typecheck and diff whitespace checks passed. No full application suite or live installation/qualification was run.

The Slice 2 HTTP problem-contract follow-up on October 28, 2026 passed **55 focused Admin Python tests**, including endpoint validation and safe error-envelope regressions, plus changed-file Ruff check/format. It did not change browser assets or deployment configuration.

## Durable operation continuation

Slice 3 routes admitted source commands through the checkpointed operation engine.
See [Durable private Admin operations](HOSTED_ADMIN_OPERATIONS.md) for current
status/resume/cancel contracts, private qualification commands, fresh authorization,
worker claims, exact receipt reconciliation and credential-free restore fencing.
These repository changes do not install or qualify the live authority or host.
