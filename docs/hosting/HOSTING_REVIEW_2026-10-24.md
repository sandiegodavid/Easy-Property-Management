# Review: commit e35de731 and the docs/hosting set

Review date: October 24, 2026. Scope: commit e35de731 ("Google Cloudflare public access
hosting", 172 files, about 16,600 insertions) and the current `docs/hosting/` tree after the
October 24 reorganization. Archive material was treated as history, per the hosting index's
own rule. Code findings below were verified by reading the diff directly (the new
`hosted_access` module, its middleware, identity verifier, session store, router, body
handling, storage budget, and the hosted composition in bootstrap).

## Verdict

The implementation is unusually disciplined. Authorization runs before dispatch against a
default-deny route table, the logout fence the design specifies is actually implemented and
tested, and storage quota is enforced twice (kernel volume plus admission accounting). I
found no high-severity code defect in the parts reviewed. The real risks are elsewhere:

1. Three status summaries contradict the single qualification checkpoint (D1).
2. Monitoring is promised in the plan but nowhere evidenced, and the tunnel is disabled at
   boot, so an unplanned reboot leaves the demo dark until a manual check (D2).
3. Backups depend on one person running a manual daily procedure; that is accepted for the
   demo and should become a hard gate before any real-data pilot (G2).
4. The post-trial run-rate lands at about the USD 30 target with almost no headroom
   (Cost section).

## 1. Gaps and bugs

### Code (verified against the diff)

- **C1 (Low) — one shared rate-limit bucket.** `middleware.py` keeps a single per-process
  in-memory window (600 requests/minute) that counts every request, including public assets
  and unauthenticated ones, before route admission. Per workspace that blast radius is one
  workspace, and Cloudflare Access blocks most unauthenticated traffic at the edge, so this
  is acceptable for the demo. Before multi-operator workspaces, move to per-session buckets
  plus an edge rate-limit rule so one device cannot starve its own workspace.
- **C2 (Low) — zero clock-skew leeway on assertion issue time.** Both
  `service._require_identity` and the verifier's claims check reject an assertion whose
  issued-at is even one second ahead of the VM clock. Standard JWT practice allows a small
  leeway for clock skew. The VM clock is NTP-synchronized, so this is a robustness nit, not
  a live defect; a 30 to 60 second leeway removes a flaky sign-in class without weakening
  the expiry checks.
- **C3 (Low) — key refresh holds the verifier lock across the network fetch.** During a
  Cloudflare certs outage with an expired key cache, verifications queue behind one fetch
  (2 second timeout, 30 second cooldown). Behavior is bounded and fail-closed, which is the
  right side to land on; just expect a brief stall at key rotation or outage edges.
- **C4 (Info) — the Origin/Fetch-Site condition is fragile to edit.** The three-clause
  and/or expression in `_dispatch` is correct on inspection (foreign Origin rejected,
  unsafe methods without an Origin rejected, cross-site rejected except the documented
  sign-in navigation), but its correctness depends on operator precedence. Named booleans
  or a truth-table test would keep a future edit from silently inverting it.
- **C5 (Info) — the server now requires Python 3.14 syntax.** PEP 758 unparenthesized
  exception tuples appear in `middleware.py` and `storage_budget.py`. Consistent with the
  pinned CPython 3.14.9 runtime; worth remembering that any tooling on Python 3.13 or older
  cannot even parse these files.

Checked and sound (so this is on the record): the hand-rolled RS256 verifier pins the
algorithm, issuer and audience, bounds key count and RSA size, rejects duplicate key IDs,
refuses redirects, and fails closed on any fetch or validation error. Current-device logout
blocks the old assertion's fingerprint and all-device logout bumps the operator generation
and not-before fence; there is a test named for exactly this
(`test_current_logout_preserves_other_device_but_blocks_old_assertion_bootstrap`). CSRF is
verified on every unsafe method inside `authenticate` (HMAC of the session token,
constant-time compare), not only at bootstrap. Session authorization is one indexed SELECT
joining the operator projection. Enrollment is bounded (16 pending, 32 sessions). The
restore marker wipes subject, sessions, enrollments, blocked assertions and leases, so a
restored workspace cannot resurrect authority. Storage validation pins the mount identity
and loop backing file and checks full allocation and the root reserve. Uvicorn runs a
single process on loopback with proxy headers disabled, and the hosted middleware is
registered last, so it wraps everything.

### Documentation (verified against the current tree)

- **D1 (High, process) — three summaries contradict the one checkpoint.** The hosting
  index's own maintenance rule says the qualification plan is the single current
  checkpoint, but three summaries still describe last week's state:
  - `docs/hosting/README.md` says the Task persistence/foreign-record test "remains
    unreported" and lists file/receipt work among pending gates. The checkpoint records
    Task, File, receipt and search/bootstrap isolation as passed on October 24.
  - `Hosting_Plan.md` section 4 says Task persistence and foreign-record access "are the
    next prepared checks" and that file/receipt isolation "remain release gates".
  - The qualification plan's own "Path to completion" diagram labels Task persistence as
    the current step, while its checkpoint text names audit-list/recovery isolation,
    missing/foreign CSRF and an additional uninvited identity as next.
  Fix once, structurally: date-stamp the summaries or have them point at the checkpoint
  instead of restating status.
- **D2 (Medium) — monitoring promised, not evidenced.** `Hosting_Plan.md` sections 6 and 9
  call for a minimal independent uptime check and tunnel/certificate availability alerts.
  No document records one configured; the runbook's inspection is manual and local. Paired
  with the boot-disabled tunnel, the demo can be down with no external signal. See
  alternative C for the cheap fix.
- **D3 (Medium) — two sources of truth for the running release.** The systemd template
  still pins the qualified baseline `qual-c8aab474`; the per-instance drop-in
  `20-signin-navigation.conf` selects the actual release `signin-nav-20261024`. Both the
  deployment guide and the operations record warn the reader to inspect the effective
  ExecStart — the warning is doing the work a single pin should do. At the next release
  cut, pin the template and delete the override, or add a verification step that fails
  when they disagree.
- **D4 (Low) — mislabeled link.** `Hosting_Plan.md` section 8 links the words
  "public-access plan" to `design/HOSTED_DEMO_DESIGN.md` (the measurement targets
  anchor). The public-access plan is the qualification document.
- **D5 (Low) — the adopted cost/latency review resolves to a summary.** The design states
  that the recommendations of the cost and latency review are adopted and links the
  87-line editorial summary in `qualification/reports/`. The full 222-line original,
  including the rejected-alternative reasoning, lives only in the archive. The chain is
  disclosed (the summary says where the original is) and the archive copy's SHA-256
  matches the planning manifest, so this is a citation nit, not a records problem:
  have the design cite both.
- **D6 (Low) — one orphaned evidence filename.** `HOSTED_DEMO_PRESSURE_PARTIAL_2026-10-24.json`
  is never named in the docs. The operations record (October 24, item 8) explains that the
  final result supersedes the retained partial report; naming the file there closes the
  loop for a future reader.
- **D7 (Info) — the demo clock is already running.** The protected configuration's window
  is October 24, 18:51 UTC through November 7, 18:51 UTC. The remaining gates (audit-list
  and recovery isolation, CSRF negatives, an uninvited identity, live shared-editing
  tests, cache/compression measurement, the full latency/load protocol, final tunnel boot
  enablement) must fit inside that window or be renewed. The checkpoint would be stronger
  with one line scheduling them against November 7.

### Qualification and operations gaps (mostly already tracked; sharpened)

- **G1 — every capacity number is still a target.** The latency/load protocol (50
  observations, three runs, four browsers, plus report and staggered-backup load) has not
  run. The docs state the E2 medium's shape correctly (two exposed vCPUs, one sustained
  vCPU in aggregate), so CPU throttling under the report/backup load is the metric most
  likely to move a decision. The one hard measurement available, about 195 MiB sampled
  peak memory per service at idle startup, says memory is not the near-term constraint.
- **G2 — the backup scheduler is a person.** Accepted in the design for two operators,
  with a 24-hour disclosed risk window. The failure mode is silent: recovery status reads
  a local ledger only and never contacts R2, so a missed day surfaces only at the
  administrator's next inspection. Recommendation: make "unattended backup plus a
  stale-recovery-point alert" a written admission gate for the real-data pilot, not a
  later nicety. The plan's section 12 already lists qualified unattended recovery as a
  commercial gap; promote it into section 5's admission list.
- **G3 — no bare-host rebuild has been proven.** Reference recovery is verified, and the
  operations record is explicit that it is not a lost-host rebuild; the qualification
  register likewise marks a full rebuild unproven. The January 15 funding review is a
  natural deadline to run one rebuild on a scratch VM end to end.

## 2. Cost, capacity and latency

### Cost

Post-trial monthly run-rate at October 2026 list prices for the recorded configuration:

- E2 medium, us-west1: about USD 24.46
- 30 GB standard persistent disk: about USD 1.20
- External IPv4: about USD 3.65 (the docs' own dated figure)
- R2 archives at current scale: effectively USD 0 (about 0.5 MB per archive, 14 retained
  points across both workspaces)
- Domain amortized: about USD 1

Total: about USD 30 per month. The target is achievable, but with essentially no
headroom — a larger disk, a second VM, or paid monitoring breaks it. Two endorsements of
choices already made: keeping the external IPv4 is right (the tunnel is outbound, but
package updates and R2 uploads still need egress, and Cloud NAT would cost more than the
address); and refusing to downsize to 2 GB before measurement is right, because the saving
(about USD 12) is small next to a failed qualification cycle.

One cost hygiene item: retained releases each carry a full virtual environment on a 30 GB
disk. The 80/89 percent disk guards catch the failure, not the cause. Cap retained
releases at current plus the qualified rollback baseline and say so in the operations
record.

### Capacity

- The binding constraints at MVP scale, in order: sustained CPU (one vCPU aggregate) during
  reports and imports; the 250 MiB per-workspace volume (by design); host disk for
  releases and backup staging; then memory. Service limits (MemoryHigh 1 GB, MemoryMax
  1500 MB each, cloudflared 256 MB) sum to more than the 4 GB host only at their ceilings;
  the High watermarks throttle first. On a 2 GB host those limits cannot both stand, which
  the design's re-qualification rule already covers.
- The plan's refusal to name a workspaces-per-host number before measurement is correct.
  When the load protocol runs, density should be stated as "workspaces per host at the
  p95 gates under the four-browser plus background load", not as an idle-RSS division.

### Latency

- The origin side is already lean: loopback dispatch, local JWT verification, one indexed
  session SELECT, no per-request provider call, no routine session write. The 20 ms
  incremental-auth budget is credible.
- The unmeasured risk is the path, not the origin: browser to Cloudflare edge to tunnel to
  Oregon. For San Diego operators that should sit well inside the reference network
  (RTT at most 100 ms), and the design already requires measuring actual operator networks
  separately from reference targets.
- The cheapest large win left is gate 4: qualified compression and edge caching for
  fingerprinted assets with Access enabled. Cold loads currently ride the tunnel for every
  asset. Do that before any private-data caching; the change poll (15 seconds, one Audit
  marker read, about 960 checks per hour across four browsers) is already cheap and needs
  no redesign.

## 3. Alternatives, with tradeoffs

- **A. Compute: stay on GCE E2 medium (chosen) vs DigitalOcean 4 GB at USD 24 flat vs
  Lightsail 4 GB at USD 24.** Staying costs roughly USD 5 more per month post-trial and
  keeps the existing runbook, IAP-only SSH and all recorded evidence valid. Moving buys a
  simpler bill and, on DigitalOcean, a full 2 vCPU shape, at the price of requalifying
  storage, boot and recovery on a new provider. Verdict: stay for the demo and the first
  pilot. If the load protocol shows CPU throttling, the honest next step is a dedicated-CPU
  instance (for example E2 standard 2, about USD 49), which is a funding decision against
  the USD 30 target, not a provider hop to save USD 5.
- **B. Backups: manual daily (chosen) vs unattended with a server-side secret store**
  (systemd credentials or a root-only key file plus a timer). Manual keeps passphrase
  custody entirely with the administrator and a human verifies every point; its cost is a
  single-person dependency and silent misses. Unattended execution holds the 24-hour RPO
  on weekends and travel; the passphrase at rest on the host adds less exposure than it
  first appears, because host compromise already exposes the live data — the marginal
  secret is the off-host archive history. Verdict: manual is right for the demo; make
  unattended plus alerting a pilot admission gate (G2).
- **C. Tunnel boot state: disabled at boot (chosen for acceptance) vs enabled at boot.**
  Disabled guarantees no accidental public exposure before final acceptance; it also
  guarantees a dark demo after any reboot until someone starts it by hand. Verdict: at
  invitation time, enable at boot and pair it with a free-tier external uptime check on
  the public sign-in URL. That one check also delivers the plan's tunnel/certificate
  availability monitoring (D2) for USD 0.
- **D. Live files in R2 (rejected).** The rejection is technically sound today: the file
  adapter requires bucket versioning and exact VersionId behavior, which R2 does not
  provide. The real alternative is not "use R2 anyway" but relaxing the adapter's
  versioning dependency, which is the same territory as the open FILE-001 cleanup
  findings. Defer until file traffic is measured; if it is ever taken up, R2's zero
  egress pricing fits browser downloads better than B2's cheaper storage with capped free
  egress. Not an MVP decision.
- **E. Control plane: per-process administrative SQLite (chosen) vs managed Postgres
  (deferred).** Agree with the deferral. The administrative store is tiny (at most 32
  sessions and 16 enrollments per process) and Postgres buys nothing until multi-host
  placement, accounts or billing exist — which is exactly the trigger the plan names.
- **F. Ingress: Cloudflare Access plus named tunnel (chosen) vs a self-hosted identity
  proxy vs a VPN-only tool.** Access gives email PIN sign-in and per-application policy
  with no second internet-facing auth system to patch on a one-vCPU host, and the
  application still verifies assertions itself, which is the right defense in depth.
  A VPN-only path would force client installs on operators and points away from the
  product's direction. Stay.
- **G. SQLite tuning: current WAL settings (chosen) vs synchronous NORMAL or a read
  pool.** Agree with deferring both. NORMAL trades away acknowledged-write durability on
  power or OS failure, and neither change is supported by a measurement yet. If the load
  protocol later shows write latency binding, the honest order is query plans first, then
  contention behavior under the four-browser load, then revisit with data.

## 4. Recommended next actions, in order

1. Fix the three stale status summaries (D1). Fifteen minutes; prevents a wrong
   "what is next" decision by anyone resuming from the index or the plan.
2. Decide tunnel boot enablement together with the external uptime check, at invitation
   time (D2, alternative C).
3. Run the latency/load protocol before general invitations (existing gate 5). It is the
   only step that converts capacity from designed to known.
4. Pin the release in one place at the next release cut (D3).
5. Put the post-trial run-rate numbers and one bare-host rebuild on the January 15
   funding review agenda (G3, Cost).
6. Promote unattended backup plus stale-point alerting into the hosted MVP admission
   list (G2).

## What was not reviewed

The frontend hosted-session implementation beyond the contracts it consumes; the FILE-001
findings (a separate open thread); provider console state (billing, firewall and R2
settings are operator-reported in the docs and were taken as such); and the archive
sources, per the index's rule that they are context, not current instructions.

## Addendum — full documentation audit (same day)

A complete read of all nine live documents, the qualification reports and the evidence
files surfaced the following additional findings, each verified against the current text.
They extend section 1's documentation findings without changing the verdict.

- **D8 (Medium) — the runbook's recovery example carries workspace A's retired UUID.**
  The `recovery-a.json` example in `HOSTED_DEMO_OPERATIONS.md` shows workspace_id
  `0efb09a0-5af2-4e6f-904f-154a50ab9445`. The deployment record's identity table lists that
  value as A's retained old private UUID; the current hosted UUID is
  `611d3445-0cce-4858-a10d-b5d5202d601a`. The example is labelled as containing
  placeholders, but this field is a real stale value rather than an obvious placeholder
  like the `REPLACE_PRIVATELY` keys. Because publication revalidates workspace identity, a
  config copied from the example fails closed: safe, but an administrator following the
  runbook builds a recovery config that cannot publish until they diagnose why. Replace
  the value with an unmistakable placeholder.
- **D9 (Medium) — the retention rule is weaker than the retention promise.** The plan
  (section 7) and the design (section 7 and its decision register) promise "seven
  successful daily recovery points" per workspace. The runbook implements something
  different: "the latest successful snapshot from each of the latest seven UTC days".
  After two missed days the implemented rule holds five points spanning seven days, not
  seven points. The divergence appears exactly when recovery matters most, during a
  disrupted week. Either change the rule to retain the last seven successful points
  regardless of calendar, or restate the promise in the plan and design to match the
  rule.
- **D10 (Medium) — no incident-response or credential-loss procedure.** `Hosting_Plan.md`
  section 9 requires incident, credential-loss, export/deletion and recovery procedures.
  Recovery is covered well; incident response is not. The runbook has one rotation
  paragraph and notes that rotation/revocation outage proof is outstanding, but no
  containment sequence for a leaked tunnel credential, R2 key or Access account
  (fence sessions, revoke at the provider, rotate, re-verify). The highest-pressure
  scenario in the set has the least written guidance.
- **D11 (Medium) — no operator-data export or deletion procedure.** Nothing documents
  end-of-demo data return or deletion: how an operator's portfolio is exported to them,
  when the R2 business archives are deleted, or how the administrator reference bundles
  are destroyed. Reference retention is described only as "manual". Section 7 requires
  the pilot to disclose retention and deletion handling explicitly; as written, that
  disclosure could not be executed as a procedure.
- **D12 (Low) — the qualification register's per-row "remaining work" text is frozen at
  pass time (extends D1).** For example, the register row for Task ownership still lists
  File, receipts, search and bootstrap boundaries as remaining, while the rows directly
  below record those as passed. Only audit-list, recovery, cache, CSRF, an uninvited
  identity and concurrency actually remain. Same fix as D1: one living summary, or
  date-stamp each row's scope text.
- **D13 (Low) — the design register claims a cost artifact that is still outstanding.**
  The decision register describes the runtime-cost decision as a "USD 30/month
  infrastructure target with recorded actual estimate". The qualification register's
  Resource/billing row lists "Actual gross regional estimate/credit audit" as still
  remaining. The Cost section of this review supplies an estimate from list prices;
  the recorded actuals still need to replace it before the January funding decision.
- **D14 (Low) — "USD 30 alerts per operator" inverts the intended meaning.** The hosting
  index, the runbook and the qualification register all say the USD 30 alerts are
  configured "per operator". The deployment guide describes one project-level budget
  and makes clear the intended word is "operator-reported". Read literally, three
  documents describe a budget per demo operator.
- **D15 (Low) — an agent work instruction is embedded in the qualification plan.** The
  plan ends with a "Usage guard" paragraph (save work and stop at stated session-usage
  thresholds; resume only on user direction). That is a working instruction for an AI
  session, not a release requirement; a future reader or auditor will misread it as an
  operational rule of the demo. Move it out of the qualification document.
- **D16 (Low) — two smaller gaps.** No runbook response procedure exists for a tunnel or
  prolonged auth-key outage (the behavior is specified in the design; the response steps,
  including what to tell operators, are not). And the domain `epmdemo.xyz` has no recorded
  renewal date or lapse procedure, although a lapse would disable both demos and the
  Access team URLs at once.
- **Also noted:** the current verified recovery points predate the newest evidence
  records (the checkpoint discloses this; the index's Recovery line does not carry the
  caveat). And the dominant recurring cost of the manual backup model, the administrator's
  daily labor, is priced nowhere in the set; the USD 30 target is infrastructure only.

## Addendum 2 — code audit completion (same day)

The remaining code-audit results were verified against the diff before inclusion. One
automated alarm is disposed of first: a compile check of the new module under Python 3.13
flags the unparenthesized exception tuples as syntax errors. That is the expected PEP 758
situation from C5 — the code targets the pinned CPython 3.14.9, under which the syntax is
valid, and the deployed service runs it. Not a defect. The verified findings:

- **C6 (Medium) — migration 0001 was edited in place; existing local workspaces will fail
  audit schema validation.** The commit modifies
  `database/sqlite-migrations/versions/0001_initial_schema.py` to add `hosted_operator`
  to the `audit_events` actor-kind CHECK and a new actor-reference length CHECK, with no
  new migration version. `modules/audit/infrastructure/schema_validation.py` now demands
  exactly the new constraint text and raises `MigrationSchemaError` ("audit_events has
  incompatible constraints") on any mismatch. A workspace database created before this
  commit therefore fails validation when the new build opens it. The hosted path is
  unaffected (fresh workspaces on the current schema), and the project's greenfield-only
  policy sanctions backup/restore as the data path — but the concrete exposure is a
  pre-existing local workspace opened directly by the upgraded app. Worth one explicit
  check: open a pre-commit local workspace with the new build and confirm the failure
  mode is the expected validation error with a documented restore path, not a surprise.
  If any local workspace matters, export its backup before upgrading.
- **C7 (Medium-Low) — re-invoking Claim editing after a successful claim wedges the
  holder.** The backend lease claim is idempotent for the same token ("owns and live"
  returns the existing row, which covers lost responses, and the design's same-token
  retry rule). But the frontend (`apps/web/src/shared/recovery.ts`, `claimEditing`)
  clears its pending token on success and mints a fresh random token on the next call,
  never reusing the held lease token. A second Claim editing invocation therefore
  presents a different token against the user's own live lease; the backend treats it
  as foreign, returns 409, and the frontend's error path clears local authority. The
  user must use Take over or wait out the five-minute lease. No data is lost, and the
  lost-response path works as designed; the gap is only the deliberate re-click, and no
  test covers holder re-claim (takeover by another session is covered).
- **C8 (Low) — the 30-second whole-body deadline fights the 50 MiB file ceiling.**
  `request_body.py` wraps the entire body read in a 30-second timeout. A maximum-size
  file therefore needs roughly 14 Mbps of sustained uplink; an operator on slower
  hotel or café Wi-Fi hits a hard timeout that presents like a size failure. The design
  caps body size but budgets no transfer time. A per-chunk idle timeout, or a total
  deadline scaled to the admitted body size, would match the stated file contract.
- **C9 (Low) — a prune that fails midway leaves the ledger listing points already
  deleted, until the next publish.** `recovery_publication.publish` saves the ledger
  (retention pending, full point list) before deleting non-retained points, by design,
  so a failed prune cannot erase the new verified point. If a delete fails mid-loop,
  the ledger still lists the points deleted earlier in that same loop. The state is
  flagged (retention pending), the runbook's repair/retry path covers it, the newest
  point is never pruned in its own run, and a restore attempted in the window fails at
  download rather than restoring bad data. Residual fix if it ever matters: re-save the
  ledger with the actually-deleted keys removed before returning.
- **C10 (Info) — GET /sign-in is broader than the design's public exception.** The
  design permits the exception only with no Origin header, HTML acceptance, Fetch Mode
  navigate and Fetch Destination document. The middleware serves the sign-in page to
  any GET /sign-in, including headerless non-browser requests. No data is exposed (the
  shell is the pre-sign-in page and every API still requires authentication), so this
  is spec fidelity, not a hole: tighten the check or amend the design sentence so the
  two agree.
