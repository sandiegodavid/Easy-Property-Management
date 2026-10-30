# Add an isolated synthetic demo operator

Slice 5 supplies the repository workflow. This runbook does not claim live installation, three-operator qualification, automatic Cloudflare changes or onboarding activation. The ordinary ceiling remains the explicitly qualified ceiling. On the existing two-operator host, adding C stays blocked until the [qualification procedure](HOSTED_ADMIN_OPERATIONS.md) is completed and promoted. Saving a setup is permitted while blocked.

## Private installation prerequisites

Use the existing [private authority installation](HOSTED_ADMIN_AUTHORITY.md) and [console launcher](HOSTED_ADMIN_CONSOLE.md). Install the matching wheel in the Admin environment and selected release. The release's `admin` extra supplies the synthetic seed client and R2 adapter (`httpx2`, `boto3`); qualify these dependencies before selecting that release. Do not install a browser fixture on the host.

The Mac release bundle includes `admin-seed/seed.py` and `dataset.json` under its existing `SHA256SUMS`, and includes the Admin composition/observation tools. Verify the bundle before extraction and preserve root ownership. The template digest is SHA-256 of the canonical JSON array of those two files' SHA-256 digests, in that order. The release digest is SHA-256 of `SHA256SUMS`. No edited operator workspace is a template.

Provision these protected installation inputs privately; the browser cannot supply them:

| Input | Contract |
| --- | --- |
| `/var/lib/epm-admin/provisioning/` | Real root-private directory, mode 0700; operation ownership markers are retained here |
| `provisioning/config.json` | Root-owned configuration below, mode 0600 |
| `provisioning/cloudflare.token` | Root-private read-only Access API credential; never paste into the browser |
| Qualification verifier directory | Existing protected `qualification-reports`, pinned verifier digest and private signing key, fresh inventory-bound capacity snapshot and setup-readiness report |
| `/etc/epm/cloudflared-admin.json` | Protected JSON-formatted cloudflared configuration (valid YAML), using the existing tunnel identity/credentials and preserving unrelated routes; readable by its qualified service identity |
| `/etc/epm/recovery-<assigned-key>.json` | Existing private R2 recovery configuration pinned to the newly assigned workspace, with a root-private ledger/staging directory outside business storage |

The configuration shape is:

```json
{
  "deployment_kind": "synthetic_demo",
  "hostname_suffix": "your-approved-domain.example",
  "release": "release-YYYYMMDD-NN",
  "release_digest": "<64 lowercase hexadecimal characters>",
  "profile": "<qualified capacity profile>",
  "template_digest": "<64 lowercase hexadecimal characters>",
  "memory_bytes": 0,
  "disk_bytes": 0,
  "port_start": 8000,
  "issuer": "https://your-team.cloudflareaccess.com",
  "account": "<32 hexadecimal account ID>",
  "readiness_report": "<registered verifier-report UUID>"
}
```

Replace every placeholder and both zero budgets with measured, qualified values. Memory reserves the enforceable service limit; disk reserves the complete workspace/init/recovery budget, at least the 250 MiB image. `port_start` must leave room for 1,000 candidate ports. Paths, Unix identities and individual port assignments are server-owned.

The signed readiness report must bind `release`, `profile`, `release_digest`, `template_digest` and `configuration_hash` (SHA-256 of canonical configuration JSON), with `qualified: true`, a current `observed` time, future `expires` time and actual integer `remaining_seats`. It is a trusted qualification-collector artifact, not an administrator checkbox. Admission requires observations younger than five minutes, matching capacity applicability, at least 25% memory headroom and the disk/recovery reserve. Missing or stale collector evidence blocks creation. Registered commitments and unregistered reservations are counted once; retained resources are not released by cancellation.

The private ingress adapter expects the effective `epm-cloudflared.service` command to use the fixed JSON configuration path above. Transitioning an existing tunnel configuration is a disclosed, serialized private maintenance step: preserve every unrelated route and credential reference, validate the full candidate, publish atomically, reload only the tunnel as required, and verify existing operators before reconciliation. The console does not rewrite the shared tunnel, change its boot policy or assert that this transition has already occurred.

## Browser setup

1. Launch the private console and sign in. Select **Add operator**.
2. Enter display name, exact sign-in email, support email and optional non-secret reference. **Save and continue** acknowledges a versioned server draft. The same stable administrator can reload it after reconnecting or signing in again.
3. Select the installed release, a fresh synthetic or empty portfolio, read/write or read-only access, and a window of at most fourteen days. The selected time zone is explicit. No existing edited portfolio is cloned.
4. Review the recipient, assigned URL, dates and reservations; confirm **Create isolated demo**. The reviewed assignment hash, draft revision, original operation key and all reservations are committed together before external effects. Changed assignments or stale revisions require another review. Duplicate active email assignments are rejected without stripping plus-addressing or provider-specific dots.
5. Keep the progress URL. Closing the browser does not cancel admitted work. A lost response is checked through **Check saved setup** or the saved-setup/operation list; signing in never resubmits creation. Input remains visible during failed background reads and revision conflicts.

The worker creates only operation-owned users, directories, allocated ext4 images, mounts, configurations and target units. It initializes a new reserved workspace identity, runs the installed seed as the service user, validates retained data, and reconciles effects before retries. It neither restarts A/B nor deletes failed resources. Private maintenance and provisioning share the host lock. A safe stop fences further steps, stops the target, disables existing source access through its owning receipt, and retains allocations for private reconciliation.

## Verified manual Cloudflare handoff

At **Administrator setup required**:

1. In the configured Cloudflare account, create one self-hosted Access application for the exact assigned hostname. Configure one Allow policy including only the intended exact email. Obtain the audience from the provider; do not type an audience into the browser or substitute a broad/bypass policy.
2. Verify Access protection before publishing DNS/ingress for that hostname. Add its exact `http://127.0.0.1:<assigned-port>` route through the private host-maintenance procedure. Preserve every existing route and the final `{"service":"http_status:404"}` catch-all. Do not place a wildcard or earlier catch-all ahead of the target.
3. The backend independently reads the application/policy, verifies the audience, checks the effective local ingress configuration and public unauthenticated Access challenge, and checks retained operators' runtime. Provider failures remain unknown or failed; a checkbox cannot satisfy the gate. The Cloudflare token stays private and is never sent to the public hostname.
4. Obtain a one-use resume credential using the installed `epm-admin operations` command with the exact JSON displayed on the progress page. Review the current operation before resuming. The credential is bound to that operation's current revision; stale grants cannot resume changed or stopped work.

## Pre-enrollment recovery verification

Once the target is registered and running with access blocked, progress changes to **Verify the pre-enrollment recovery point**. Install its recovery configuration using the assigned workspace identity and the existing R2 policy. Then run the exact server-assigned command shown on the page:

```bash
sudo /opt/epm/admin/venv/bin/python -I /opt/epm/admin/admin_console.py \
  verify-pre-enrollment --operation <original-operation-UUID>
```

The helper prompts privately for the backup passphrase. It stops only the new writer, invokes the existing offline encrypted backup command as the service user, validates/publishes a private copy through the existing R2 recovery service, then independently downloads, hashes, decrypts and runs complete current-schema/retained-data validation on the remote bytes. It compares the exact workspace and current configuration, rechecks authority/fences, and registers a signed report plus audit outcome. It restarts only the still-fenced pending service; a concurrent stop/revocation instead keeps it contained. Failure leaves retained artifacts and an audit outcome, never a successful proof. No archive path, provider locator, passphrase, token or decrypted data is returned to the browser.

After successful verification, explicitly resume the original operation with a fresh credential. The pre-enrollment proof is valid for at most 24 hours and only for that operation/workspace/configuration. This is not the approved-binding reference or onboarding restore drill required by Slice 6.

## Invitation and enrollment approval

Successful provisioning shows **Scheduled** before the start, **Waiting for sign-in** once open, or **Awaiting approval** after a verified enrollment arrives. Copy the complete invitation and send it manually. It contains exact email, URL, start/expiry, named zone and UTC offsets, pending-approval expectations, support contact and synthetic-only restriction. Copying does not mean delivered and does not grant access. Expired windows and failed/expired reads do not offer a new copy action.

Review the verified issuer, email, exact subject and received time. Obtain the displayed action-bound credential through the existing private `action-grant` procedure, authorize the reviewed action, then explicitly select **Approve identity — keep access blocked**. The source-owned revision/fence/enrollment checks and atomic audit/receipt remain authoritative. A lost approval response is looked up using the original operation; it is not blindly repeated.

The result is **Identity approved · Recovery verification pending · Business access blocked**. Continue through the [Slice 6 lifecycle checklist](HOSTED_ADMIN_LIFECYCLE.md#complete-onboarding) for approved-binding recovery and explicit activation. Ready-to-use instructions remain unavailable until that completion is verified; do not replace it with an assertion or an emergency activation override.

## Focused verification matrix

| Area | Repository proof |
| --- | --- |
| Happy paths | Acknowledged three-step setup; immutable allocation; simulated manual gate/resume; invitation and identity-only approval; private encrypted remote verification |
| Invalid combinations | Unqualified capacity/release/template/quota, duplicate email, stale assignment/revision, unsafe paths/ownership, wrong provider policy/audience, forged/foreign recovery proof |
| Retry/idempotency | Original create key/result, lost browser response lookup, preserved input, cross-session draft read, owned-effect retries without reformatting; real installed-seed preparation preserves the reserved workspace UUID and journal across initialization interruptions, lost writes and completed retries |
| Transaction/rollback | Host reads outside control transaction; admission rechecks revision/authority; operation/draft/reservations roll back together; stop/revocation contains target-only access |
| Persistence/schema | Exact current setup/plan contracts, retained audit/canonical data, generated private schemas; no compatibility migration |
| Backup/restore | Actual encrypted remote bytes decrypted and validated; wrong workspace/hash denied; restored control operations stay fenced and credentials are excluded |
| Bounded reads | Fixed directory budget for 1/100/200 records; one bounded setup-name projection; no per-row business/provider reads; bounded drafts, operations, workers and frames |
| UI/accessibility | Narrow/both appearances, semantic steps, focused errors, explicit saving, failed-read/stale-edit preservation, hidden polling and original-operation recovery |

Run only the focused `hosted_admin`, source-command, offline-backup/publication and release-tool tests; `npm run test:admin`; changed-file Ruff; frontend lint/format/typecheck and reproducible contract checks. These tests use isolated roots and simulated Linux/provider effects. Actual Linux ownership/mount/systemd behavior, provider setup, load/isolation/reboot/recovery and a live third invitation still require the explicit installation and Slice 7 host qualification. No live acceptance is inferred from these tests.

Validation on October 29, 2026: **243 focused Python tests and 19 Admin Playwright tests passed**. The focused Python set was rerun after resuming the saved implementation (243 passed). Changed Python Ruff checks, frontend lint/format/typecheck, deterministic contract checks and release-script syntax validation passed in the implementation continuation. The final continuation changed documentation only. Linux/provider effects were simulated; no live installation, invitation, activation or capacity promotion was performed.

## Storage and broker regression qualification

New owned ext4 images use the deployment recipe's 10% root reserve with discard and deferred initialization disabled. Provisioning checks physical allocation after formatting and checks the mounted reserve with the same minimum-16-MiB rule as hosted startup. Workspace verification repeats these checks; retries retain the existing filesystem UUID and never reformat it. The private offline backup child receives the pinned `volume/tmp` as `TMPDIR` before Python starts.

The broker accepts at most 16 concurrent connections, with at most four ordinary external effects and two urgent disable/revoke/stop effects. Short status reads and administrator fences do not wait for ordinary effect slots. Saturation returns `admin_broker_busy` (503); check the original operation before retrying a write. SQLite serialization, per-operation worker locks, peer/session authorization and post-effect containment still apply.

The actual ext4/loop-mount regression is deliberately opt-in. On an approved disposable root Linux qualification host with loop-mount capability, e2fsprogs and the test environment installed, run from `application/`:

```bash
sudo env EPM_RUN_LINUX_VOLUME_QUALIFICATION=1 .venv/bin/python -m pytest \
  apps/server/app/modules/hosted_admin/tests/test_linux_volume_qualification.py -q
```

This allocates one disposable 250 MiB image under `/var/lib`, formats and mounts it with the qualified options, runs the complete hosted storage validator as an unprivileged UID, and unmounts/removes its resources. It does not touch inventory, systemd, fstab or providers. It is skipped on macOS and in ordinary runs without explicit opt-in; a skipped run is not Linux qualification evidence.

Review follow-up validation, October 29, 2026: **185 focused Python tests passed; one opt-in Linux qualification test skipped on macOS**. This includes real Unix RPC tests of status, authority revocation and urgent disable during blocked effects, plus a fresh-interpreter test of the offline backup helper environment. Changed Python Ruff check/format and diff whitespace validation passed. No frontend changes or live host operations occurred.
