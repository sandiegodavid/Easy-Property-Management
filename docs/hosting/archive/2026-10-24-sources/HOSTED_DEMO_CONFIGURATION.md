# Hosted demo configuration and route contract

Slice 1 implementation, October 23, 2026. This contract does not make the local server public. Hosted request handling is qualified by later slices; the local `serve` command retains its loopback-only transport.

## Protected deployment configuration

The current A/B hosted services use `/var/lib/epm-<instance>/hosted-local.json`.
Their old `config.json` files still select the previous private portfolios and
are retained for fallback. CLI examples below select the hosted candidates.

Create one root-owned JSON file per instance under `/etc/epm/`, readable by its service group and not writable by that group or others. Its parent directories must also be root-owned and not group/world writable; symlinks are rejected. Do not put it in a business workspace. Values below are examples, not enrollment or usable credentials:

```json
{
  "deployment_mode": "hosted_demo",
  "public_origin": "https://demo-a.example.com",
  "identity_issuer": "https://example.cloudflareaccess.com",
  "identity_audience": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "workspace_id": "0efb09a0-5af2-4e6f-904f-154a50ab9445",
  "operator_id": "00000000-0000-4000-8000-000000000001",
  "allowed_email": "operator-a@example.invalid",
  "administrator_contact": "administrator@example.invalid",
  "administration_database": "/var/lib/epm-a/access/hosted-access.sqlite",
  "storage_volume": "/var/lib/epm-a/volume",
  "storage_image": "/var/lib/epm-volumes/epm-a.ext4",
  "enabled_at": "2026-10-23T00:00:00Z",
  "expires_at": "2026-11-06T00:00:00Z",
  "capabilities": ["records.read", "records.write", "files.read", "files.write"]
}
```

Replace all example deployment/identity values and dates before use. Unknown fields/capabilities, non-exact origins, ports, URL credentials, invalid email/UUID identities, naive times, and windows longer than fourteen days are rejected. The administrative database must be outside both the portable workspace and source checkout. Hosted demo file storage must be local. These checks do not initialize administrative/business data or enroll a subject.

The implemented validation command, run as the appropriate service user, is:

```bash
sudo -u epm-a /opt/epm/releases/RELEASE/venv/bin/python -m app \
  --config /var/lib/epm-a/hosted-local.json \
  validate-hosted-config /etc/epm/hosted-a.json
```

It requires a valid existing workspace with the exact expected identity and an unexpired deployment. This command validates configuration and workspace identity, not the physical quota. The explicit `serve-hosted` launcher additionally requires the dedicated Linux quota volume and private `TMPDIR` described in the [operations runbook](../../operations/HOSTED_DEMO_OPERATIONS.md); it fails closed on unsupported or unqualified storage. Never upload real configuration or credentials to source control. Dates/contact/domain values are deployment inputs; absence does not permit accepting requests with defaults.

## Route inventory to enforce in Slice 3

The owning application routes and generated OpenAPI snapshot remain the source inventory. Classification below is independent of whether a control is visible in the UI. New route families require explicit admission; unknown routes fail closed.

| Class | Routes and enforcement |
| --- | --- |
| Public non-business shell | Exact sign-in page, approved fingerprinted assets and necessary auth error pages; no workspace bootstrap, records, arbitrary SPA fallback or private configuration |
| Session establishment | Explicit hosted sign-in/bootstrap/enrollment state routes; verified assertion, exact configured host/origin and replay/enrollment fences; no business records before activation |
| Session control | Current-session read, CSRF acquisition, current/all-device logout; valid session and exact-origin CSRF for unsafe operations |
| Authenticated business reads | Explicit registered domain reads, `/api/operator/bootstrap`, directories/Home/search/recovery, `/api/audit`, original-operation results and File metadata/content; check workspace/session before dispatch or receipt replay |
| Authenticated business writes | Registered source mutations and unfinished-form recovery; require records.write, owning revision/idempotency contracts, exact Origin and session CSRF |
| File operations | `/api/files`, `/api/file-links` and domain-owned upload routes; additionally require files.read/files.write as applicable, authorized links, integrity and quotas |
| Forbidden host administration | All `/api/workspace` routes, workspace path/initialization/recovery operations, storage reconciliation/verification administration, credentials, provider connections/configuration tests, and external AI dispatch |
| Forbidden diagnostics | Public `/health`, `/docs`, `/redoc`, `/openapi.json`, host paths and process/backup administration; use private administrator diagnostics instead |

Existing `/api/ai` capabilities require explicit feature qualification; the demo has no provider credentials or generation dispatch. Host settings do not become operator actions because a route exists. CLI backup/restore/configuration commands remain administrator workflows outside public HTTP.

Local mode retains its current no-login behavior, exact loopback origin rules and explicit CLI intent header. Hosted mode must not convert a local-client header into identity, silently fall back to local transport, or trust forwarded metadata from arbitrary callers.

## Administrative sessions and enrollment (Slice 2)

The current source supplies an administrator-only CLI; build and qualify its release before using these commands on the VM. The existing `demo-001` installation is not upgraded by these source changes. Use the owning service account and root-owned deployment configuration. Initialization is explicit and refuses to replace an existing administrative database:

```bash
sudo -u epm-a /opt/epm/releases/RELEASE/venv/bin/python -m app \
  --config /var/lib/epm-a/hosted-local.json \
  hosted-admin /etc/epm/hosted-a.json initialize
```

After an actual verified subject requests enrollment through the later hosted session boundary, list pending subjects and explicitly approve the intended one:

```bash
sudo -u epm-a /opt/epm/releases/RELEASE/venv/bin/python -m app \
  --config /var/lib/epm-a/hosted-local.json \
  hosted-admin /etc/epm/hosted-a.json enrollments

sudo -u epm-a /opt/epm/releases/RELEASE/venv/bin/python -m app \
  --config /var/lib/epm-a/hosted-local.json \
  hosted-admin /etc/epm/hosted-a.json activate --subject VERIFIED_SUBJECT
```

The same CLI accepts `disable` or `revoke` to fence existing sessions immediately, including when the demo has expired or its business workspace cannot open. Rebinding requires `disable`, a verified pending enrollment for the replacement identity, `rebind --subject VERIFIED_SUBJECT`, explicit activation, and a fresh identity proof issued after the revocation cutoff. Copying a business workspace does not copy authorization; the administrative database is outside its portable archive. Do not back up usable session/token-hash/lease rows into an authorization recovery bundle.

## Shared edit authority and changes (Slice 6)

`POST /api/hosted/drafts/{record_id}/lease` requires a verified writable session,
exact Origin and CSRF. Its strict body contains a new random 256-bit `token`,
`expectedRevision`, and optional explicit `takeover` / `renew` flags. Only the
token hash is retained in the protected administrative database. Same-token claim
retries are idempotent and never silently extend authority. Five-minute claims
renew at most once per minute; the owner session must remain active.

Recovery saves, attempt preparation, reconciliation and discard require
`X-EPM-Draft-Lease` as well as the owning revision/idempotency contracts. A
source-owned `RecoveryEditAuthority` port holds the administrative reservation
through the owning business transaction, so a takeover cannot interleave between
validation and commit. Ordinary reads still have the existing one-SELECT session
budget; lease mutation/renewal has separate bounded work. Lease storage is bounded
to 128 rows, expired claims are pruned on claim, and restore invalidates claims.
These latest-format tables are not a migration of the existing VM installation.

`GET /api/operator/changes` returns only workspace/runtime identity, source revision
and UTC time using one source-owned Audit marker read; no per-record/File reads or
maintenance write. Browser polling is visible-only and additional to independent
Home focus/reconnect/attention transitions. The [operator guide](../../operations/HOSTED_DEMO_OPERATOR_GUIDE.md)
describes claim/takeover, expiry and original-result recovery.

Ordinary session authorization uses one indexed SELECT with no last-seen write. Pending enrollment is bounded to sixteen subjects and active session storage to thirty-two sessions per instance; expired/revoked rows are pruned during session establishment. Key discovery uses the configured Cloudflare team only, rejects redirects, bounds its response, and shares a fifteen-minute signing-key cache with refresh throttling. Actual provider sign-in/logout qualification remains pending until the hosted HTTP and browser slices are deployed.
