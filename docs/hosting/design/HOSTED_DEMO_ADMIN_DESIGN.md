# Hosted demo administration and additional operators

Design proposal — October 27, 2026. No implementation or deployment is performed by this document. Existing two-operator qualification remains in force until the extension is accepted and tested.

## Can the current Google demo add a third operator?

Yes, as another isolated demo instance on the same VM, subject to capacity qualification. Each operator keeps a separate portfolio, service, Unix identity, access database, hostname and bounded storage volume. This extends the current hosted-demo topology; it does not put several operators into one business workspace or deliver SaaS collaboration.

The application configuration has no global two-operator maximum: `HostedDeployment` pins one `operator_id`, `allowed_email` and `workspace_id` per process. The templated `epm-hosted@.service` can name additional instances. However, provisioning is currently manual and release/reset/cleanup scripts contain A/B assumptions. Simply adding another email to A's Access application would not create C's workspace or authority.

### Observed baseline

Read-only Google Cloud/IAP inspection on October 27, 2026 found:

| Item | Observation and limit of evidence |
| --- | --- |
| VM | `epm-demo`, `us-west1-b`, running `e2-medium` |
| Memory | 3,908 MiB reported total; 2,656 MiB available at inspection; no swap |
| A / B | Active, zero automatic restarts; approximately 325 / 298 MiB cgroup memory |
| Per-service memory limits | MemoryHigh 1 GiB; MemoryMax 1,500 MiB |
| Per-service CPU limit | 90% of one CPU; aggregate limits do not create additional CPU capacity |
| Root disk | 28,691 MiB filesystem, 19,680 MiB available |
| Tunnel | Disabled at boot; the command's exit status 1 reflects `is-enabled=disabled`, not failure of the preceding resource reads |

These are instantaneous observations, not a three-operator load, reboot or backup qualification. The October 26 [release reconciliation](../evidence/HOSTED_DEMO_RELEASE_RECONCILIATION_2026-10-26.json) identifies `release-20261025-03`; older hosting indexes still name an earlier runtime. The Admin screen must discover the effective installed release rather than treating either document as live inventory.

Google documents the E2 medium as 4 GiB with one sustained shared CPU allocation, exposed through two vCPUs. Cloudflare currently lists a free 50-user tier; check the account's actual available seats, including administrators and other applications. Neither statement establishes how many EPM operators this VM can serve. Sources: [Google machine types](https://docs.cloud.google.com/compute/docs/general-purpose-machines), [Cloudflare plans](https://www.cloudflare.com/plans/).

## Recommended scope

Build a small, separate host administration console for the deployment owner. Start by qualifying a third isolated operator; increase the recorded qualified limit only after repeating the load and recovery gates. Provisioned or suspended portfolios still consume disk even when their services are stopped.

Include operator creation, verified enrollment approval, invitation preparation, expiration renewal, immediate disablement, session revocation, service status, recovery status and resumable failed operations. Include all Admin UI and backend work in this delivery. Continue to use existing release/backup/reset services rather than inventing a second business-record or recovery implementation.

Keep destructive reset, restore, release deployment, infrastructure resizing and data deletion in the existing private runbooks for the first console release. The UI can show their status and mark an operation as requiring a private administrator step. No automatic email sending, billing, shared-workspace roles, arbitrary remote commands, real customer portfolios or provider credentials in the business app.

This proposal extends the bounded experiment under SAAS-001/SEC-001/SEC-002; it does not change their completion status or the local MVP's no-login behavior. Do not silently turn the current two-instance acceptance evidence into an N-instance claim.

## Administrator workflow

### 1. Open administration

The deployment owner runs one documented launcher on their computer. It opens an IAP SSH forward to a separate loopback-only Admin service on the VM, then opens its local browser URL. The console is not exposed through the public operator tunnel and does not appear in operator Settings.

The launcher obtains a short-lived single-use bootstrap credential through the authenticated SSH channel. Paste it into the console sign-in form; never place it in a URL, command-line argument, browser storage or log. Bind the issued session to the pre-provisioned administrator identity. An IAP/SSH connection is transport access, not permission for arbitrary local browser requests. The console requires its own session and CSRF protection.

For the initial single administrator, provision identity and recovery CLI access privately during installation. Additional administrator accounts and public Internet Admin access are separate scope. The console cannot grant itself access or manage Google IAM.

### 2. Review the overview

Show active/qualified operator count, available memory, disk reservations, remaining Access seats, tunnel status and oldest verified recovery point. Each has an observation time and available/unknown/stale state.

The primary button is **Add operator**. If blocked, show the specific reason and remediation, such as “Three operators have not passed the capacity test” or “Reserve space for this workspace and its recovery copies.” Permit saving an operator setup draft while capacity is unresolved, but do not allocate ordinary operator resources or invite anyone. Link the capacity blocker to **Qualification plan**, which shows the separate private test procedure below and its evidence/status. Only an explicit, bounded qualification reservation may create test instances above the ordinary qualified ceiling; it does not raise that ceiling or admit invitees.

### 3. Add an operator

Use three short steps, retaining an acknowledged setup draft between steps:

1. **Operator:** display name, exact sign-in email, optional non-secret reference code and support contact. Explain that the code is a label, not a password. Each operator signs in with their own approved email and may use several devices. Default to a fresh synthetic portfolio; offer an empty synthetic workspace. Do not offer cloning another operator's edited database.
2. **Demo:** select an already installed, qualified release and synthetic template version; choose start and expiry within the existing fourteen-day window. Show the assigned hostname, storage/file limits, capability profile and expected backup policy. Hostname, UUIDs, Unix user, paths and ports are generated from host inventory, not editable shell/path inputs. Read/write demo is the normal profile; read-only remains an explicit supported alternative.
3. **Review:** summarize recipient, isolation, dates, reservations and steps. **Create isolated demo** starts one durable operation. Existing A/B instances are not restarted or rebound.

Reject accidental duplicate active email assignments by default and offer **Open existing operator**. A deliberate second workspace for the same email is outside the initial workflow. Compare according to the configured identity policy; never strip plus-addressing or provider-specific dots to infer an identity.

Closing the browser does not cancel a committed provisioning job. The overview shows its progress and links back to the operation result.

### 4. Provision without granting business access

The job reserves the instance key, exact hostname, port, storage and resource profile; provisions the non-login Unix account, private directories, fully allocated 250 MiB image/mount, private temporary storage, root-owned configurations and per-instance access database; creates and validates fresh workspace identities; then starts its single writer.

Configure an exact-host Cloudflare Access application/audience and exact-email policy before publishing the tunnel route/DNS. A route must never expose an origin that has no matching Access protection. Keep the tunnel catch-all deny rule. Verify enforcement, host/audience/workspace binding and service readiness, not just DNS resolution.

The workflow reconciles the provider's observed resources after every external call. If the API credential is not installed, pause at **Administrator setup required**, give precise Dashboard instructions and expected non-secret identifiers, then independently verify their completion. Cloudflare tokens and tunnel credentials never pass through the browser. Do not claim this step is automatic until API permissions and the selected tunnel-management mode have been qualified.

After resource checks, show **Scheduled · Starts [time]** before the enabled window, or **Waiting for first sign-in** once it opens, not **Active**. Before the start time, do not promise enrollment or business access; retain the existing date checks. Prepare a copyable invitation containing the assigned URL, exact sign-in email, start and expiry with a named time zone and UTC offset, synthetic-data restriction and support contact. The administrator sends it manually. **Copy invitation** is not delivery confirmation. A pre-enrollment recovery point protects the fresh data; approved-binding recovery must be refreshed after enrollment.

Use these instructions in the invitation, populated from the current deployment window:

> Your demo opens [start date/time, zone, UTC offset] and expires [expiry date/time, zone, UTC offset]. Before it opens, the link may show that access has not started; return at the start time. Then open [assigned URL], sign in with [exact email] using Cloudflare's email PIN, and select **Continue to workspace** to request approval. A pending-approval screen is expected on first use. Contact [support] if needed; do not repeatedly request new PINs to resolve pending approval. After the administrator confirms approval, return to the same link and select **Continue to workspace** again. Renew sign-in if prompted. Use synthetic data only.

### 5. Approve the verified enrollment

The operator opens the link and completes Cloudflare sign-in. Existing EPM bootstrap creates a pending subject without returning business data. The Admin detail screen then shows the verified issuer, email, subject reference, received time and intended operator/workspace binding.

The administrator checks the intended person and selects **Approve access**. Bind approval to the exact current pending enrollment and instance revision; never activate from a typed email alone. Validate current dates, resource qualification and healthy runtime again. Approval enables the known subject using the existing access service and records its result. Offer **Copy approval instructions**: “Your access is approved. Return to [assigned URL], sign in with [exact email] if prompted, and select Continue to workspace again. Your demo expires [time, zone, UTC offset].” The administrator sends this manually; copying does not establish delivery. The operator explicitly continues/signs in; no shared operator session or PIN is sent by the Admin UI.

Show **Access active · Recovery verification pending** until an encrypted approved-binding reference is published and read back. Require that evidence and the new-instance acceptance checks before **Mark onboarding complete**. Existing sessions, token hashes, CSRF material and draft leases never enter recovery bundles.

### Recovery-pending handoff and completion

In this state the primary action is **Verify onboarding recovery**. It opens a persistent checklist linked to the instance and operation, not a transient modal. Show the exact instance key, workspace UUID, current binding revision, approved-subject reference and pinned configuration digest; the support-facing summary uses safe references rather than credentials. Link directly to [daily manual recovery points](../operations/HOSTED_DEMO_OPERATIONS.md#daily-manual-recovery-points) and [administrator recovery bundles](../operations/HOSTED_DEMO_OPERATIONS.md#administrator-recovery-bundle-and-host-loss).

The checklist presents the private terminal launcher with the server-assigned instance and handoff IDs as fixed arguments. Its implementation is part of the recovery tooling slice: it loads the registered paths/configuration itself and runs the existing backup, publication and reference validators as the appropriate owner. No passphrase is entered into the browser. It must produce a protected verification report even when a step fails; a printed “success” or pasted object name is not evidence. Report generation and registration are a new adapter over the existing private recovery procedures, not an already available command.

Required evidence is a validated encrypted business archive, independent off-host read-back/decryption and workspace identity validation, a successful isolated restore drill for this new workspace, and an encrypted approved-binding reference independently read back/decrypted and compared with the current binding. Record point IDs, digests, source snapshot marker, completed-at times, verifier/release identity, restore result and policy-age checks. Do not put decrypted data or secrets in the report. A binding revision changes when the operator/workspace/approved identity or pinned deployment configuration changes; ordinary session issuance does not change it. The approved-binding reference must be captured after that binding was approved.

The private helper registers the report through the authenticated local broker into a protected evidence registry. Bind it to the handoff ID, instance/workspace UUIDs, binding revision and configuration digest; prevent ordinary browser or operator callers from publishing verification assertions. The browser's **Check verification** sends only the handoff ID and expected instance revision. The backend reads the registered report, verifies provenance and required successful checks, compares all current identities/digests, and checks recovery age against policy. It returns missing, failed, stale or verified evidence with specific next steps. Arbitrary browser-provided report paths and manually checked boxes cannot satisfy verification.

Reloading or reconnecting restores the same checklist and registered evidence. If the binding changes during the terminal work or verification, retain the report as history, mark it stale for onboarding and require a new binding reference/check. Do not mark the operator complete automatically. When recovery evidence and new-instance acceptance are current, enable **Mark onboarding complete**. This explicit audited action includes the verified evidence ID, acceptance record ID and expected instance revision; it rechecks both records and current access/binding in the completion transaction. A conflict or stale evidence preserves recovery-pending state. A successful action records the onboarding result and changes lifecycle to **Active · Onboarding complete**, without granting extra access or renewing sessions. Completion is idempotent; new access/binding changes require their own verification and cannot reuse stale completion evidence.

### 6. Maintain access

| Control | Meaning / confirmation |
| --- | --- |
| Copy sign-in instructions | Copy the existing assigned URL and instructions; does not grant or renew access |
| Approve pending enrollment | Exact verified subject; cannot substitute another email or bypass disabled state |
| Extend demo | Explicit new window within the existing maximum fourteen-day duration, expiry preview, configuration validation and recorded cutover; never silently extend on sign-in |
| Revoke all sessions | Keep the assignment; durably revoke current sessions and require fresh eligible identity proof |
| Disable access | Immediately fence app authority, revoke sessions/leases, then remove edge allowance/revoke provider access; retain records and recovery points |
| Enable access | Requires an explicit healthy/qualified/unexpired instance, reviewed approved binding and fresh proof; never undo a pending disable automatically |
| Change sign-in email | Private assisted rebind: disable, stage exact new policy/configuration, receive verified replacement enrollment, explicitly rebind/activate; old identity remains denied |
| View operation | Status, safe error, timestamps, completed and next steps; **Resume** retries the same operation |

Disable/revoke must work if the workspace is full, corrupt, expired or its writer is stopped. If the access store cannot be fenced, stop and verify the owning service and block its ingress; show **Containment pending** until denial is observed. Never report success based only on an upstream API acknowledgement. A disabled operator can still own retained data; **Disable** is not **Delete**.

Email replacement and expiry renewal need coordinated config/runtime changes because the current deployment object is immutable. For renewal, fence/drain that instance, atomically publish validated config, restart with its existing workspace, verify effective dates and require fresh sign-in before activation. Record old/new configurations and resume state; do not restart all operators. If failure occurs, leave the target fenced for explicit recovery. Where an email change needs private assistance, show this honestly rather than presenting a nonfunctional button.

## Admin interface

Use the existing visual tokens, Light/Dark appearance, semantic tables, labeled fields and asynchronous status patterns. Serve a separate Admin entry point/bundle; do not import the business workspace gate or assume an operator bootstrap. Reuse visual primitives, not operator mutation/recovery authority.

### Overview

```text
Demo administration                                      Add operator
2 active / 3 qualified     Host: healthy     Recovery: 1 needs attention

Attention: Operator C approved-binding backup not yet verified

Operator       Access / setup          Expires       Service      Recovery
Operator A     Active                  Nov 06        Healthy      Verified · date
Operator B     Active                  Nov 06        Healthy      Verified · date
Operator C     Waiting for sign-in     Nov 10        Healthy      Pre-enrollment only

Filter: All / Needs attention / Active / In setup / Disabled / Expired
```

Illustrative rows/dates and qualified ceiling only; they do not describe the live deployment. Derive counts from their corresponding access and qualification facts.

Prefer a compact summary strip, one actionable attention list and an operator table. Row names navigate to details; action menus have separate labeled buttons. A multi-step provisioning operation gets a dedicated progress page, not a long-lived modal. Mobile uses labeled cards preserving the same actions and status meaning.

### Operator detail

Header: operator name, reference, assigned URL, lifecycle/access badges and expiry. Primary action follows the state: **Resume setup**, **Copy invitation**, **Review enrollment**, **Verify onboarding recovery**, **Mark onboarding complete**, or **Extend demo**. Offer **Copy approval instructions** after approval. Recovery verification and onboarding completion remain distinct from activation. Secondary menu contains revoke/disable. Destructive controls are visually separated and require a plain-language consequence plus reason.

Sections:

- **Access:** intended email, verified binding, activation/expiry, supported capability profile and valid app-session count. No “online now” claim: the existing authorization path deliberately does not write last-seen per request. Never return session/lease/assertion hashes.
- **Runtime and capacity:** effective release/checksum, service/mount checks, reserved/measured memory and disk with timestamps; exact public hostname. Hide host filesystem paths from the ordinary overview; show sanitized operational identifiers in details.
- **Recovery:** distinct last local archive, off-host read-back, restore drill and approved-binding reference verification. An existing file or recent upload is not “recoverable.” Show RPO policy and overdue/unknown status.
- **Operations:** chronological setup/access operations, actor, reason, result and safe correlation IDs. Expand to show checked steps; raw shell logs, emails from business data and secrets are never response content.

### Latency, failure and accessibility

All status queries and operations are asynchronous. Keep the shell/navigation responsive, announce results and retain input after validation errors. Poll an open active job at a bounded interval (for example two seconds with backoff); use slower visible-only overview refresh and stop polling hidden pages. Show observation times and retained stale data during connection loss. Missing readings never become green/zero.

Disable duplicate submissions while awaiting a result, but retain the original operation key. A lost response offers **Check operation**; do not silently create another job. Stale revisions offer **Review latest status** while preserving edits. Closing a setup draft offers **Save and close** / **Discard draft**; discard only before provisioning starts. Once provisioning starts, **Stop setup** requests a safe checkpoint and retains created resources in a disabled state. It does not remove a Unix account or filesystem.

Keyboard focus moves to the step heading/error summary; confirmations are labeled and keyboard operable; status changes use restrained live announcements. Do not rely on color alone. No business-record entry, cross-operator search or “sign in as operator” control belongs here.

## Backend boundaries and security

### Separate control plane

Add a host-administration application with its own composition root, loopback listener, administrative store and session boundary. It can share a wheel/release with EPM but is a separate process and route inventory. Normal hosted/local EPM processes do not register these routes or inherit its credentials.

The unprivileged Admin HTTP process submits typed commands to a narrow local privileged broker over a root-controlled Unix socket. Authenticate the socket peer and bind each request to a validated Admin session/operation. The broker accepts fixed operation kinds and inventory IDs; resolves all paths, users, ports, units and release artifacts itself; validates ownership/no symlinks; and invokes fixed argument vectors without shell evaluation. No generic `exec`, arbitrary unit/path/file upload, sudo password, SSH key or browser-supplied environment.

Provisioning/mount/systemd changes require privilege. Run workspace initialization, seed generation, validation and owning access commands as the target service user. Root-owned Cloudflare/recovery credentials are available only to narrowly scoped adapters. Never mount every business workspace into the Admin HTTP process or open their databases to build the overview. Existing host administration is already trusted with system access; this design confines the added browser boundary rather than claiming protection from a malicious host root.

Use source-owned application operations for enrollment/disable/revoke/rebind. Extend the current CLI/application seam to return typed results and bounded administrative status; do not have the console manipulate another module's SQL rows or scrape its human-readable CLI text. Persist an authorization audit outcome atomically with each access-state mutation in that instance's access store; the control-plane log records the orchestration and evidence references separately. Cross-store failures reconcile through the operation journal, not a claimed distributed transaction.

### Admin authentication

Bootstrap credential: at least 256 random bits, hash-only storage, one use, five-minute expiry, issued through an allowlisted IAP/SSH administrator command. Admin session: opaque token in an HttpOnly, SameSite=Strict, host-only cookie; 30-minute idle/eight-hour absolute expiry with explicit reauthentication for access changes. The forwarded HTTP endpoint is loopback-only: do not claim a Secure-cookie guarantee over plain HTTP. Prefer a dedicated loopback HTTPS setup when available; otherwise document the local-process threat and tunnel dependency. Use a distinct cookie name and fixed launcher port/Host allowlist so it cannot be confused with an operator session.

Require exact Host/Origin and session CSRF for unsafe requests, reject cross-site Fetch Metadata, deny CORS and arbitrary forwarded headers, and keep CSP/frame restrictions. Bootstrap credential exchange requires the same origin protections. Limit attempts and do not log request bodies/credentials. Revoking Admin access fences its jobs before further steps; IAP revocation alone must not be assumed to terminate an already established forward. No admin role is inferred from an operator cookie or email header.

### Reauthentication, reconnect and committed work

For an uncommitted access change (approve, enable, disable, revoke, renew, rebind or qualification promotion), obtain a new one-use grant through the same IAP/SSH launcher. The console exchanges it at the reauthentication endpoint for a server-held, single-use authorization bound to the Admin identity/session, exact action/request hash and target revision, expiring in five minutes. Consuming it and admitting the durable operation are atomic. This avoids asking for a fresh grant again when an already admitted operation is merely being looked up after a lost response. A reauthentication response alone never submits the action: show the reviewed current action and require explicit confirmation.

| Event | Committed job / administrator next step |
| --- | --- |
| IAP forward or browser connection lost | Already admitted bounded work continues to its next durable checkpoint or human gate. Restart the launcher/forward, obtain a new bootstrap grant if the session is unusable, then retrieve the original operation; no automatic mutation replay |
| Idle or absolute Admin session expiry | Session/CSRF expires; admitted work retains its original authorization while the administrator identity remains enabled. Pending human gates and new commands wait for a new session and, where required, action-bound reauthentication |
| Explicit console logout | Revoke that browser session, clear local credentials, and stop new UI commands. It does not cancel committed work; label this on logout and offer a separate safe-stop request before logout when desired |
| Administrator authority revoked | Increment the durable administrator authority generation, revoke sessions/grants and fence owned jobs from further consequential steps. An in-flight external effect is reconciled at the checkpoint; if it could grant access, use containment and keep the job paused. Only an authorized administrator can explicitly review/resume it |

Workers check current administrator authority generation as well as instance fencing before every consequential step; browser session expiry alone is not identity revocation. A committed approval may therefore finish after a network drop or ordinary logout, but a queued activation must not cross a recorded administrator-revocation fence. Do not automatically undo an already completed approval solely because its response was lost.

Keep acknowledged setup drafts and operation/action keys in the control-plane store under the administrator's stable identity, independent of session lifetime. Non-secret draft/operation IDs may be in canonical console routes. On authentication loss, preserve that safe return route; after sign-in, reload its saved draft or operation from the server. Unacknowledged input is visibly unsaved and may require re-entry; do not claim it was saved or persist sensitive form content in browser storage.

If an action response was lost before an operation ID arrived, use an authenticated exact lookup by the original idempotency key, or the administrator's bounded recent-operation list after browser restart. If found, show its original result/status. If not found, explicitly re-read the target revision and enrollment/evidence, obtain fresh action authorization as needed, and let the administrator confirm the original unchanged intent/key. If the reviewed request must change, abandon that uncommitted intent and create a new key after review. Neither sign-in nor returning to the page silently resubmits an approval. **Resume** after an administrator-authority fence requires new authorization and a current revision review; it does not reuse the revoked grant.

### Authoritative host inventory

Use a separate protected control-plane SQLite database outside all portable workspaces:

| Record | Essential content |
| --- | --- |
| Instance | Stable instance UUID/key, operator/workspace UUIDs, exact intended email, hostname, allocated port, installed release/profile/template IDs, lifecycle, revision, timestamps |
| Allocation | Unique hostname/port/user/mount/image reservations, disk/resource budgets, owning instance/operation and retirement status |
| Operation | UUID, stable administrator identity/authority generation, idempotency key, canonical request hash, expected revision, status, safe error/result, cancellation flag, timestamps |
| Step | Stable sequence/kind, desired spec hash, provider IDs, verified external effects, checkpoint and reconciliation evidence |
| Qualification | Release/resource-profile identity, test authorization and reservations, controlled identities, tested operator/device count, workload, measured latency/headroom/recovery results, evidence date and explicitly promoted ordinary ceiling |
| Recovery handoff/evidence | Instance/workspace identity, binding revision/configuration digest, protected verifier provenance, point/digest/restore/age results, acceptance reference, status and completion operation; no credentials |
| Observation | Bounded service/resource/recovery fact, source and checked-at time; disposable and explicitly stale when unavailable |
| Admin audit/session | Append-only safe operation events; separate hash-only expiring sessions/bootstrap grants, excluded from recoverable authority |

Business records remain in their original owning modules. Existing per-instance access stores remain authoritative for enrollment, generation, sessions and leases; the inventory's access status is observed, not a duplicate authority. Enforce unique active email, hostname, port, instance key and workspace identities. Use server-generated opaque instance keys; retain A/B as existing allocated keys and never derive C from a count or email.

Discovery is reconciliation, not automatic adoption. Register A/B by inspecting root-owned configuration, effective systemd commands, mount identities and access bindings, then administrator confirmation. A discrepancy or unmanaged `epm-hosted@*.service` blocks destructive cleanup and further conflicting allocations. Never overwrite a populated path to “repair” inventory.

### Durable operations and failure handling

Provisioning is a resumable saga because filesystem, SQLite, systemd and Cloudflare cannot commit atomically. Suggested states:

`draft → provisioning → awaiting_external_setup / waiting_for_sign_in → awaiting_approval → access_active_recovery_pending → active`

Separate access flags and service observations from lifecycle; also represent `failed_step`, `disabled`, `expired` and `retired`. A healthy process is not evidence of active access or successful onboarding.

Reserve allocations and write the operation in one control-plane transaction. One mutating operation per instance; serialize host allocations, mount changes, route/config publication and capacity reservations. Never hold a database transaction open over provider/network calls. Read-only status and urgent disable remain available while a long job runs; disable fences queued activation and wins over subsequent resume. Use a per-instance authority generation checked before every grant-enabling step.

Each step records intent before its external effect, then verifies the effect and checkpoints. After a crash between effect and checkpoint, inspect actual ownership/spec/provider IDs before retrying. Identical operation key/request returns the original result; changed payload with the same key is 409. Changed desired settings need a new reviewed request/revision. A lost browser response is resolved by operation lookup. Do not assume Cloudflare provides the same idempotency semantics: adapters reconcile exact tagged resource identity and refuse ambiguous duplicates.

Failure leaves the new instance access-fenced, preserves resources and shows the failed step plus **Resume** or private remediation. Do not delete resources automatically. Compensation removes only a provably operation-owned, unaccepted resource after explicit administrator confirmation; it never touches A/B. Do not auto-reactivate after cancellation, restore, renewal failure or a later disable.

## Proposed API contracts

These belong only to the private Admin service. Business `/api/hosted/*` and operator APIs retain their existing authorization. Use generated OpenAPI types and the shared problem envelope/status mapping; validation is 422, oversized content 413, missing resources 404, stale/conflicting requests 409, absent/denied authority 401/403, capacity/admission limits 429 with a safe explanation, unavailable dependencies 503. Pending jobs return 202; lookup returns 200 with operation state.

| Contract | Purpose |
| --- | --- |
| `POST /admin-api/session` | Exchange single-use SSH bootstrap grant for Admin session/CSRF |
| `GET /admin-api/session`, `DELETE /admin-api/session` | Current authority and logout |
| `POST /admin-api/session/reauthenticate` | Exchange a fresh SSH grant for single-use action authorization bound to intent hash/target revision; does not execute the action |
| `GET /admin-api/overview` | Independent capacity, attention and source availability summaries |
| `GET /admin-api/instances?cursor=…&state=…` | Bounded directory, total and observed status; no workspace reads |
| `GET /admin-api/instances/{id}` | Revision, safe configuration, enrollment summary, service/recovery observations |
| `POST /admin-api/setup-drafts`, `PATCH/DELETE /admin-api/setup-drafts/{id}` | Versioned unsent setup only; cannot discard started provisioning |
| `POST /admin-api/instances` | Confirmed setup snapshot/revision plus idempotency key → operation and instance IDs |
| `POST /admin-api/instances/{id}/actions` | Typed approve/disable/enable/revoke/renew/complete-onboarding intent, expected revision, reason and idempotency key; approval includes exact enrollment reference; completion includes verified recovery and acceptance IDs |
| `GET /admin-api/instances/{id}/recovery-handoff` | Persistent private-step instructions, handoff ID and required/current evidence status |
| `POST /admin-api/instances/{id}/recovery-handoff/check` | Verify broker-registered evidence for the handoff and expected current revision; never accept browser-supplied success claims |
| `GET /admin-api/operations/{id}` | Durable status, safe ordered steps and original result |
| `GET /admin-api/operations/by-key/{key}` | Authenticated exact lookup of the administrator's original request after a lost response; static route precedes the ID route |
| `POST /admin-api/operations/{id}/resume` | Resume the same validated intent; no settings mutation |
| `POST /admin-api/operations/{id}/cancel` | Durable safe-stop request; no implied resource deletion |

No request accepts arbitrary host paths, Unix usernames, shell commands, Access audience overrides or service-unit names. Read/write profiles expand only to existing valid capabilities. Bound strings, bodies, page sizes and retained operations/drafts; never silently prune failed or live jobs needed for reconciliation. Scope read query budgets to the control-plane store: a directory page uses a fixed number of bounded queries, not one per workspace or provider call. A background inventory sweep records observations; opening the overview must not fan out to all business services or Cloudflare.

## Capacity and additional-instance admission

The current 4 GiB VM may accommodate three lightly used portfolios; the observation above cannot justify unlimited operators. Keep the initial qualified maximum at two until the extension passes acceptance. Capacity evaluation includes a running Admin service/broker, all reserved instances, OS/tunnel overhead, backup staging, preserved resets/releases and off-host recovery costs.

Do not copy A/B's 1,500 MiB hard limit blindly to C: three such limits alone total 4,500 MiB. Qualify a smaller per-instance profile against realistic peak memory, or explicitly approve a larger VM. A profile must reserve at least 25% host memory for OS/host services/headroom and accommodate aggregate enforceable service limits inside the remaining envelope, including Admin processes. CPU remains a shared sustained budget; measure concurrent loads and throttling rather than summing CPUQuota percentages. No automatic billing change or cap reduction.

Reserve fully allocated per-instance workspace images plus measured initialization and recovery/reset staging. Deny admission if free disk after commitments is below the greater of 20% filesystem capacity or the largest supported recovery job's measured requirement. Count retained disabled portfolios and existing reservations. Use measured archive expansion/staging bounds; 250 MiB of live workspace is not the full disk cost of one operator.

Record a qualified operator/device ceiling for a specific release and resource profile. For C, test three operators with two active browsers each and staggered reports/uploads/backups; preserve existing latency gates and at least 25% memory headroom without OOM/restarts. The number of Access seats is a separate check, not a server-capacity setting. Unknown provider quota/capacity blocks invitation/activation while allowing draft setup.

Before general invitations, explicitly decide whether to enable tunnel startup at boot and test the resulting mount → instance → ingress recovery behavior. A deliberately manual-start tunnel is acceptable only with a visible availability policy; do not represent it as automatic recovery. More operators amplify the same VM failure domain.

### Private path from a ceiling of two to three

Qualification is a separate private, broker-enforced operation available through the IAP administrator CLI; the console's **Qualification plan** displays its status and evidence. It is not a checkbox override on **Add operator** and cannot invite an ordinary third operator. Implement the following procedure before the ordinary capacity blocker ships:

1. **Record a bounded test plan.** Select the installed candidate release/profile, target of three simultaneous test instances/six browsers, controlled tester emails, exact protected test hostnames, storage/recovery reservations, time-limited test window, maintenance/rollback plan and evidence directory ID. Use distinct verified identities controlled by consenting testers; do not impersonate existing operators. The broker issues a durable qualification ID and permits only those exact test allocations. The ordinary ceiling stays two. The exception bypasses only the prior measured count, never physical capacity, storage, identity, resource ownership or access checks.
2. **Make physical capacity available.** Three candidate service limits plus host/Admin reservation must fit the selected VM before starting tests. If that requires smaller limits or a larger host, use an explicitly approved private profile/deployment change first. If A/B plus the three tests cannot fit, arrange a disclosed maintenance window, fence/drain/stop A/B, create verified recovery points and preserve their configurations/data/allocations. Test instances replace their running load temporarily; they do not overwrite their workspaces. Count all retained disk and recovery commitments. If the budget still cannot fit, stop the plan; neither the UI nor CLI may overcommit it.
3. **Run three isolated test instances on this host.** Provision fresh synthetic workspaces and test-specific Access applications/policies/routes through the same typed provisioning steps, bound to the qualification ID and controlled identities. No ordinary invitation copy/activation is available for these instances; private tester instructions permit only the named test participants. Existing normal workspaces remain inaccessible to the testers. Isolated test roots used in unit tests are prerequisites, not a substitute for these Linux/Cloudflare tests.
4. **Collect host evidence.** Exercise all three with six browsers and the specified concurrent/background workload; verify isolation, latency/headroom, independent off-host recovery/restore, expiry/revocation, mount failure and the chosen real reboot/tunnel-start policy. Register immutable digests and observed outcomes under the qualification ID through trusted private tooling. Record the exact VM, release/profile and test workload; failures remain failures and leave the ordinary ceiling unchanged. A planned VM reboot requires the maintenance window even if A/B could otherwise stay running.
5. **Retire tests and restore ordinary service.** Disable/revoke all test identities, stop test writers and remove their ingress before restoring A/B from preserved bindings/configurations (normally no data restore is necessary). Require fresh eligible sign-in after fencing, verify A/B access and data, and record preserved test evidence and any retained storage. Release test reservations only after their effects are verified; no automatic deletion or test-to-customer reassignment. If recovery to A/B fails, leave the test failed/unfinished and do not promote capacity.
6. **Explicitly promote the ceiling.** If the tested release/profile differs from restored A/B, explicitly roll it out to A/B through the private deployment procedure, recheck their data/access and resource limits, and record rollback evidence before promotion. A reauthenticated administrator uses the private qualification command to review the complete evidence, A/B restoration/rollout, current matching host/release/profile and absence of conflicting reservations. Commit an audited promotion to three under an expected inventory revision and idempotency key. A typed administrator declaration without the registered evidence cannot promote. The console now shows **3 qualified**, and ordinary **Add operator** can provision a fresh C using normal admission, enrollment, recovery and acceptance. Never convert a test subject/workspace into C by renaming it.

The profile used by the ordinary running instances must match the tested profile; applying it to A/B is an explicit qualified rollout, not an implicit consequence of promotion. Changes to host size, release/profile or tested workload bounds invalidate applicability until reviewed/requalified. A/B retain their original qualified configuration if the proposed profile fails. The CLI and broker own test-plan creation/resume/abort/evidence/promotion with the same durable-operation and reauthentication rules; their concrete command syntax is an implementation deliverable, not a claim that the commands exist today. UI status must link to the installed command's documented usage and never recommend a manual database edit.

## Recovery and operational tooling changes

- Generalize the release Mac/VM wizards, fresh-demo descriptors/reset helper, inspection, rollback and release cleanup to consume the validated registered instance inventory. Remove `a/b` validation, A/B loops and `8001 if a else 8002` fallbacks. Preserve per-instance rollback protection and exact source/schema/release checks. C's selected rollback release must remain protected even while stopped.
- Preserve one writer and existing File/domain validation. Seed each fresh workspace through current deterministic demo facilities with new IDs; never copy another active workspace's identity. Keep first Add operator limited to installed qualified releases/templates, not browser wheel uploads.
- Reuse existing encrypted business archives, off-host R2 publication/read-back and separate approved-binding reference bundles. No new unencrypted backup format. Passphrases remain private terminal prompts in the first console release; the registered recovery handoff/report and **Check verification** bind private evidence to the current instance and approval before explicit onboarding completion. Automated unattended secret custody is separate scope.
- Include host inventory/configuration, provider resource references, operation journals and allocation reservations in a separate encrypted host-control recovery artifact. Exclude usable Admin/operator sessions, bootstrap grants, token/lease hashes and provider credentials. After host restore, reconcile resources and recreate authorization through fresh verification; never resume a queued activation automatically.
- Recovery jobs are staggered across instances. Draining/stopping one workspace is disclosed as its maintenance window. A dashboard archive timestamp does not prove off-host recoverability; retain independent publication/restore evidence.
- Disabled/expired data is retained under the existing demo recovery policy until explicit private retirement. Retirement must release allocations only after deletion/retention/provider cleanup are confirmed; no console Delete button in this release. Retired keys are never reused accidentally.

## Ordered implementation slices

1. **Inventory and arbitrary instance tooling:** root-owned instance registration/discovery, stable allocation IDs, A/B adoption, removal of A/B assumptions throughout deploy/reset/cleanup/recovery. Add C in isolated test roots; no live invitation.
2. **Private Admin authority:** separate launcher/listener/session boundary, action-bound reauthentication, reconnect/expiry/logout versus identity-revocation behavior, narrow broker and typed source-owned admin operations; deny tests proving operator processes cannot invoke them.
3. **Durable operation engine:** control-plane schema, idempotency/revisions, reservations, fencing, checkpoints, external-effect reconciliation, safe cancel/resume and audit. Include the private bounded qualification-plan/evidence/promotion commands so later UI admission has an executable qualification path. Keep current business schema unchanged.
4. **Read-only Admin UI:** overview/directory/details, async observations, capacity/recovery availability, operation status and exact evidence times. Display observed A/B and unqualified C without claiming new acceptance.
5. **Add operator end to end:** reviewed setup draft, resource/Cloudflare provisioning or verified manual handoff, fresh seed validation, scheduled start/waiting enrollment, complete invitation and post-approval copy, exact subject approval and durable progress UI.
6. **Lifecycle and recovery completion:** revoke/disable with broken-workspace containment, explicit enable, coordinated expiry renewal and assisted rebind. Include the private recovery helper/report registry, persistent recovery checklist, current-binding verification and audited complete-onboarding action. Update operator/admin instructions.
7. **Three-operator qualification and rollout:** execute the private two-to-three procedure, collect load/capacity/provider/isolation/reboot/recovery evidence, restore A/B, explicitly promote the matching profile/ceiling, then onboard fresh C. Only then consider four or more under the same gate.

Each slice needs focused backend and UI/browser evidence for its boundary. This is the proposed delivery plan, not a completed backlog or deployment claim.

## Test and acceptance matrix

| Area | Required proof |
| --- | --- |
| Happy paths | A/B adoption; fresh C; private Admin login; exact verified enrollment; two devices update C with existing conflict/recovery behavior; revoke/disable/renew and invitation copy |
| Invalid combinations | Duplicate email/origin/port/workspace, invalid capability sets/window, unqualified release/profile, path/symlink injection, mismatched subject/audience, unknown broker operation and overcapacity all fail before unsafe effects |
| Isolation/authority | A/B/C cannot read each other's records, Files, receipts, recovery forms or sessions; operator APIs/origins/cookies cannot reach Admin/broker; no raw admin tokens or private paths leak |
| Idempotency/retry | Lost create/activate responses, duplicate clicks, restart after every external effect, provider timeout with committed effect, changed payload/key conflict; one instance/resource set and exact original result |
| Concurrency/rollback | Simultaneous creates reserve unique ports/storage; disable wins over in-flight activation/renew/resume; failed provisioning leaves fenced owned resources; compensation does not affect A/B |
| Persistence/schema | Current control-plane/access schemas and constraints; incomplete/unreadable inventory never treated as empty; release cleanup discovers and protects C plus unmanaged instances |
| Backup/restore | C business archive and binding reference published/read back, independent restore drill; host-control journal restored safely; no sessions/credentials revived; interrupted jobs cannot grant access on restore |
| Performance/query budget | Three operators/six browsers plus Admin/report/upload/staggered backup; existing p95 latency gates; ≥25% memory headroom, bounded disk staging, no OOM/restart; fixed bounded inventory queries without per-row workspace/provider calls |
| UX/accessibility | Keyboard/mobile/themes, field errors preserve drafts, durable progress after reload, partial/stale statuses, confirmation consequences, lost-response lookup and cancellation without implied deletion |
| Availability | Workspace-full/corrupt/stopped disablement, Cloudflare/IAP/provider outages, unknown signing keys, tunnel reboot policy, mount failure and invalid resource observations fail closed with actionable status |
| Qualification bootstrap | Starting at ceiling two, ordinary C remains blocked while an authorized, capacity-fitting private three-test plan runs; controlled identities only; A/B preservation/restoration, failed-plan non-promotion, immutable evidence and explicit promotion to three; normal fresh C then follows ordinary admission |
| Invitation handoff | Future-start invitee sees exact start/zone and return instruction; pending first sign-in explains approval; post-approval copy tells them to return/continue; copying never marks delivery or grants access |
| Recovery handoff/completion | Reload during terminal work restores checklist; forged report, wrong workspace, earlier binding/configuration, pre-approval reference or expired evidence cannot complete; current verified read-back/restore plus acceptance enables one audited completion; races remain pending |
| Admin continuity | Drop IAP or expire/logout the session during setup and a committed approval response; reconnect retrieves the original result/draft without resubmitting. Uncommitted approval requires current revision and new action authorization; revoked administrator generation pauses jobs and blocks grants until explicit authorized review |

## Decisions and remaining deployment inputs

Recommend the isolated-instance topology, private IAP Admin console, typed broker, manual invitation, explicit subject approval, fourteen-day renewable window, fresh synthetic data and capacity-qualified expansion described above. Shared-portfolio users and public Admin hosting remain separate designs.

Before implementation acceptance, supply the approved administrator identity, chosen console connection mode/port, protected provider credential permissions or manual setup mode, installed release/template, per-instance capacity profile, initial qualified ceiling, backup secret custody and tunnel boot policy. These are explicit installation/qualification inputs; none should be guessed or silently enabled. No clarification is needed to write this proposal, but a live third-operator invitation must wait for those inputs and measured acceptance.

## Implementation references

- [Hosted deployment schema](../../../application/apps/server/app/modules/hosted_access/application/configuration.py), [session schema](../../../application/apps/server/app/modules/hosted_access/infrastructure/schema.py), [existing private admin commands](../../../application/apps/server/app/modules/hosted_access/infrastructure/admin.py).
- [Hosted systemd template](../../../application/deploy/hosted-demo/epm-hosted@.service), [VM release wizard](../../../application/scripts/epm-release-vm.sh), [Mac release wizard](../../../application/scripts/epm-release-mac.sh), [reset helper](../../../application/scripts/release_demo.py), [cleanup inventory](../../../application/scripts/release_cleanup.py).
- [Existing hosted design](HOSTED_DEMO_DESIGN.md), [configuration contract](../deployment/HOSTED_DEMO_CONFIGURATION.md), [ongoing runbook](../operations/GOOGLE_CLOUD_ONGOING_RUNBOOK.md), [operations/recovery](../operations/HOSTED_DEMO_OPERATIONS.md), [qualification](../qualification/HOSTED_DEMO_PUBLIC_ACCESS_PLAN.md).
