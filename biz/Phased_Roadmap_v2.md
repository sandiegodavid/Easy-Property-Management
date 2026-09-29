# Phased Roadmap (v2): Hosted by Default, Local as the Ownership Option

**Product:** Property management app for independent managers (about 10–50 doors, managing for owners)
**Direction:** The customer should only *use* the product; you keep it healthy. Hosted is the default because it needs the least from the customer. Local remains available for customers who value control and privacy. Both share one workspace format.

**How to read this document**
- The roadmap is **gate-based, not date-based.** A phase starts only when the previous phase's exit gate is met, because each gate depends on what pilot customers say.
- Effort sizes (S / M / L) are relative placeholders. I haven't seen your codebase, so confirm them with whoever builds it.
- Numbers marked **[hypothesis]** are starting points to test, not recommendations.
- Nothing here is legal advice. Trust-accounting and licensing questions need review by a qualified professional in each state you serve.

---

## What changed from v1

- **Posture:** hosted is now the default, and local is the ownership option. In v1 hosted was one option among several.
- **Hosted moved earlier**, from Phase 2 to Phase 1, since it removes the most customer effort. A checkpoint after Phase 0 confirms this order against pilot evidence.
- **New local usability standard** (section 3): signed installer, first-run wizard, automatic updates with rollback, managed AI setup, health screen, and more. The essentials are built in Phase 0 and the rest in Phase 1.
- **Deployment options** are now defined explicitly (section 2), including a managed-local service.
- **Phases renumbered:** the old Phases 2–5 are now Phases 3–6, with Connectivity as the new Phase 2.
- **New metrics, decisions, and risks** covering setup effort, support cost per install, and the earlier custodian obligations that come with hosting.

---

## 1. Guiding principles

1. **Customers use; you maintain.** Install, updates, backups, connections, and AI setup should not depend on the customer's technical skill.
2. **Hosted by default, local by choice.** Offer the easiest path first, and keep local for customers who want control.
3. **Ownership contract.** One-click full export in a documented open format. Every hosted feature can be switched off where practical. A data-flow screen lists what leaves the customer's computer (local) or where data is processed (hosted), with consent status.
4. **Same workspace everywhere.** Moving between hosted and local is a download and an import, tested as a round trip.
5. **Don't hold funds or card data.** Use a payments partner's hosted pages. The app records events; it does not move money.
6. **AI drafts, the operator approves.** Nothing is sent, paid, or committed automatically. Keep the AI kill switch and consent prompts at every new integration.
7. **Build only what stops people paying.** Each phase is unlocked by pilot evidence, not by the feature list.
8. **Relay, don't store.** Any always-on service for local customers holds encrypted events in transit and nothing else.

---

## 2. Deployment options

| Option | Who it's for | What the customer does | What you run | Available from |
|---|---|---|---|---|
| **Hosted** (default) | Most small managers | Sign in and use it; own their data via export | Single-tenant hosted workspace, backups, monitoring, managed AI | Phase 1 |
| **Local** | Customers who want control or privacy | Install once; keep their computer and backup destination healthy | Signed installer, updates, health checks, optional remote support | Phase 0 |
| **Local+** | Local customers who need payments or inbound items while the computer is off | Same as Local | Adds encrypted backup service and the relay | Phase 2 |
| **Managed Local** | Local customers who want no involvement | Pay for the service | You or a partner installs remotely and does periodic check-ups | Phase 1 (pilot), scaled in Phase 6 |

All four share one workspace format. Multi-seat access starts as a Hosted feature (Phase 4), so local customers who need seats are guided to Hosted.

---

## 3. Local usability standard

The goal is that a non-technical manager gets productive without a call with you. Items in **Phase 0** are needed before paid pilots; items in **Phase 1** follow.

| # | Friction point | What to build | Phase |
|---|---|---|---|
| 1 | Installing | Signed installer (Apple notarization on Mac, code signing on Windows) that bundles all dependencies. No terminal, scripts, or manual downloads. | 0 |
| 2 | First-run setup | Guided wizard, about 15 minutes [hypothesis]: workspace folder, backup destination and recovery key, spreadsheet import with review, email sign-in through the provider's standard flow (no app passwords). Resumable, with a "Setup 4 of 6" checklist on Home until done. | 0 |
| 3 | Updates | Background updates with staged rollout. Snapshot the workspace before each migration and offer one-click rollback. The customer never downloads a version manually. | 0 |
| 4 | Backups | On by default, encrypted, versioned, with a recovery key. Failures appear as Needs action items. Monthly test-restore prompt. | 0 |
| 5 | Expired connections | Expired email, SMS, or payment credentials become Needs action items with a one-click re-authorize, not a silent failure. | 0 |
| 6 | Support | Health screen (backup status, version, connections, disk space) and a redacted diagnostics bundle sent with one click. | 0 |
| 7 | Support matrix | Define supported OS versions and run a system check at install. Fewer supported combinations means fewer surprises. | 0 |
| 8 | AI setup | A managed AI default that you run, with a plain-language note on what text is sent. Local model or bring-your-own key becomes an advanced setting. Keep the kill switch and consent. | 1 |
| 9 | New computer | A first-class "move to a new computer" flow, tested and timed, including credential re-authorization. | 1 |
| 10 | Remote help | Optional, consented remote-support session so you don't guide people through settings by phone. | 1 |
| 11 | Time away | "While you were away" summary on open. Fully reliable once the relay exists. | 2 |
| 12 | Desk-bound feel | Phone companion and read-only links so local does not mean tied to one computer. | 3 |

**Budget for:** developer program and code-signing costs, a support-tooling choice, and the ongoing effort of testing every supported OS version on each release.

---

## 4. Phase overview

| Phase | Goal | Starts when | Exit gate (summary) |
|---|---|---|---|
| 0 | Pilot readiness and validation | Now | Backups and restore proven; setup effort measured; pilots running; deployment preference collected |
| 1 | Hosted option and managed setup | Phase 0 gate met | Round-trip hosted/local works; managed AI priced; customers have chosen between options |
| 2 | Connectivity: payments and inbound | Phase 1 gate met | Pilots collect rent through the app; inbound items arrive without loss |
| 3 | Reach: phone and owner links | Phase 2 gate met | Weekly mobile use; owners act through links |
| 4 | Team and financial workflow | Phase 3 gate met | Assistant seats in use; bank matching and e-sign/screening in daily use |
| 5 | Trust-accounting readiness | Professional review complete | Ledgers and reconciliation reports accepted by customers' accountants |
| 6 | Scale and packaging | Consistent retention across 20+ customers [hypothesis] | Tiers priced, support running, security posture documented |

---

## 5. Phase 0: Pilot readiness and validation

**Goal:** Make the current local MVP safe and simple enough for paying pilots. Learn whether the workflow earns money and which deployment option customers prefer.

**Build (usability items 1–7 from section 3)**
- Signed installer, first-run wizard, automatic updates with snapshot and rollback.
- Automatic encrypted backups to storage the customer already owns (iCloud, Google Drive, Dropbox, OneDrive, external drive, or NAS), encrypted on the device with a customer-held key. Provide a printable recovery key.
- Versioned snapshots, for example daily for two weeks, weekly for two months, monthly for a year. Always snapshot before imports and upgrades.
- Backup health and expired-connection alerts as Needs action items.
- Health screen and diagnostics bundle.
- Defined support matrix and an install-time system check.

**Concierge note:** if AI setup still needs your hands during pilots, keep it operator-assisted and log the time you spend on it. That log becomes the case for the managed AI default in Phase 1.

**In parallel (no build required)**
- Run 8–12 interviews and pick 5–10 paid pilots, using the interview script and pilot offer.
- **Add a deployment question** to the script (near the reaction questions): "If this ran in the cloud and you signed in from any device, or ran on your own computer with a folder you control, which would you choose and why? What price difference feels fair?" Record answers on the scorecard.
- Time every onboarding and log support contacts for each pilot.

**Not in scope:** payments, portals, mobile, multi-user, hosted build.

**Effort:** L (installer, wizard, updates, and backup/restore across supported platforms).

**Exit gate**
- Restore tested on each supported platform, including a full new-machine restore.
- Per-pilot setup time and support contacts recorded, with a clear view of what needed live help.
- The interview decision rule is met: at least 4 of 10 interviewees describe a recent painful workflow the app addresses, and at least 2–3 say yes to a paid pilot **[hypothesis]**.
- Stated deployment preference collected from every interviewee.
- At least 5 pilots live with a verified first backup.

**Checkpoint: deployment decision.** Stated preference is not behavior, so treat it as a signal only. If most interviewees prefer hosted, proceed with Phase 1 as written. If most prefer local for control, keep the Phase 1 hosted scope minimal and pull Local+ (relay and encrypted backup service) forward.

**Risks and mitigations**
- *Backup key loss:* printed recovery key at setup; state plainly that a lost key means lost data unless the customer opts into key escrow later.
- *Support load per install:* keep a written setup checklist and measure real time.
- *Signing and OS updates breaking the installer:* test on each supported OS version before every release.

**Stop or pivot signal:** most interviewees say online rent collection is a prerequisite. Then scope Phase 2 sooner before selling further.

---

## 6. Phase 1: Hosted option and managed setup

**Goal:** Offer the easiest path (hosted) and remove the biggest remaining local friction (AI setup).

**Build**
- **Single-tenant hosted workspace** using the same format as local, with sign-in, account recovery, and basic billing (manual invoicing is acceptable at first).
- **Download my workspace** and import back, tested as a hosted/local round trip on real pilot data.
- **Managed AI default:** you run the provider connection, explain in plain language what text is sent, and require consent. Local model and bring-your-own key become advanced settings. Track AI cost per customer.
- **Hosted operations:** tenant isolation, encryption in transit and at rest, backups with tested restores, access logs, monitoring, and a basic incident response plan.
- **Move-to-new-computer flow** (usability item 9), timed and tested.
- **Optional consented remote support** (usability item 10).
- **Packaging decision:** confirm the four options in section 2 and their pricing hypotheses.
- **Managed Local pilot:** offer remote install and periodic check-ups to a few customers to learn the real support cost.

**Not in scope:** multi-user, payments, portals.

**Effort:** L.

**Exit gate [hypothesis]**
- A hosted/local round trip works with no data loss on pilot data.
- Every pilot has been offered a real choice, and the choices are recorded.
- Managed AI cost per customer is known and priced.
- Security baseline in place: isolation, restore-tested backups, incident plan.

**Risks and mitigations**
- *You become a data custodian earlier:* keep single-tenant isolation, minimize retention, document what you store, and review the AI provider's data-retention and training terms before enabling managed AI.
- *Hosting cost per customer:* measure it in this phase before setting prices.
- *Weakened "local" differentiator:* lean on the workflow, AI-with-approval design, and the ownership contract (export, transparency, kill switch).

---

## 7. Phase 2: Connectivity (payments and inbound)

**Goal:** Remove the most likely objection, "it can't collect rent," and stop missing inbound items.

**Build**
- **Payments through a partner:** payment links and a hosted tenant pay page from a payments provider. Webhooks record payment events, reconciled against the coverage states (recorded, missing, not applicable).
- **Inbound email, SMS, and payment events:** hosted customers receive these directly. **For local customers, a relay** holds encrypted events until the app pulls them, then deletes them. Records are created and kept in the workspace.
- **Backup service for Local+:** encrypted, customer-held key, so you never see the data.
- **Data-flow screen** for both hosted and local, listing each flow, provider, and consent state.
- **"While you were away" summary** (usability item 11), backed by the relay for local customers.
- **Failed and returned payments** as Needs action items.

**Not in scope:** holding funds, card data storage, owner payouts through the app.

**Dependencies:** choose a payments partner (check current fees, ACH return handling, and terms for platforms); decide relay hosting and encryption model.

**Effort:** L.

**Exit gate [hypothesis]**
- At least half of pilot customers collect some rent through payment links.
- Inbound items arrive with no lost or duplicated records over 30 days, including for local customers whose computer was off.
- No security incident, and the relay holds no data past delivery.

**Risks and mitigations**
- *Payment failures and returns:* build clear states for pending, cleared, and returned payments before pilots use it.
- *Regulatory scope creep:* have the payments partner hold funds and handle money-transmission obligations; confirm this with counsel.
- *Relay becomes a data store:* enforce short retention, encryption at rest, and audits.

---

## 8. Phase 3: Reach (phone and owner links)

**Goal:** Let the operator work away from a desk, and let owners and tenants interact without you emailing PDFs.

**Build**
- **Phone companion:** today's Needs action, contact lookup, photo upload into the inbox. Read-first, with limited edits.
- **Owner links:** read-only statement links and expiring approval links for disbursements. Each link shows only one person's data and can be revoked.
- **Portal-lite for tenants:** magic-link maintenance request form and pay page, with no account required.
- For local customers, links serve pushed snapshots. For hosted customers they are served directly.

**Not in scope:** multi-user editing, full tenant and owner portals with accounts.

**Effort:** M for hosted, L when local snapshots are included.

**Exit gate [hypothesis]**
- Most pilot customers use the phone companion weekly.
- Owners approve or view through links without the operator emailing files.
- Local customers report the app no longer feels tied to one computer.

**Risks and mitigations**
- *Link leakage:* short expiry, single-purpose tokens, revoke on demand, access logs.
- *Sync conflicts for local customers:* use one-way snapshots rather than multi-device sync.

---

## 9. Phase 4: Team and financial workflow

**Goal:** Support an assistant or second staff member, and connect the money workflow.

**Build**
- **Second seat and roles** (operator, assistant with limited permissions, read-only accountant). Audit history shows who did what. Delivered first on Hosted; local customers are guided to Hosted if they need seats.
- **Bank feeds through an aggregator**, matched against expected payments using the coverage states.
- **E-signature integration** through a provider, with signed PDFs returned into the record.
- **Tenant screening partner integration:** send applicants to the provider so you never store their sensitive identifiers; store only the result and consent record. Keep the brief's fair-housing and consumer-report cautions.
- **Listing syndication** only if pilots ask for it.

**Effort:** L.

**Exit gate [hypothesis]**
- Assistants use their own seats weekly.
- Bank matching cuts manual reconciliation time for most customers.
- At least half of new leases use the e-sign flow.

**Risks and mitigations**
- *Permission mistakes:* start with three fixed roles rather than custom permissions.
- *Screening compliance:* use a provider, keep human review for every decision, and get legal review of your notices and flows.

---

## 10. Phase 5: Trust-accounting readiness

**Goal:** Serve managers who hold client-owner funds, only after professionals confirm the rules.

**Before any build**
- Review each target state's licensing and client-trust-account requirements with a lawyer or licensed professional.
- Talk to customers' accountants about what they need to accept the records.

**Build (subject to that review)**
- **Owner ledgers** showing every receipt, disbursement, and balance per owner.
- **Reconciliation reports** the accountant can use (bank vs. ledger, three-way where required).
- **Disbursement approval trail** building on the existing approve-and-record flow.
- **State-aware checklists**, marked clearly as planning aids rather than compliance guarantees.

**Not in scope:** claiming legal compliance; moving funds.

**Effort:** L, plus professional review cost.

**Exit gate**
- Reports accepted by at least a few customers' accountants.
- Professional review complete for each state you market in.

**Risks and mitigations**
- *False assurance:* avoid words like "compliant" until reviewed, and keep showing sources and requiring human verification.

---

## 11. Phase 6: Scale and packaging

**Goal:** Turn working pilots into a repeatable business.

**Build and prepare**
- Publish pricing for Hosted, Local, Local+, and Managed Local.
- Onboarding that doesn't need you: guided import, checklist, help articles.
- Support process: response targets, escalation path, status page for the hosted service and relay.
- **Cost review of Local:** compare support cost per local install with hosted. If local costs much more, price it accordingly, narrow the support matrix, or steer it toward Managed Local.
- **Security posture:** incident response plan, access controls, vendor list, and a decision on formal audits (for example SOC 2) once customers ask.
- Data-processing terms and a plain-language privacy statement.

**Exit gate [hypothesis]**
- 20+ paying customers with consistent retention.
- Support hours per customer low enough to price sustainably, by option.
- A clear answer to "why not Buildium" that customers repeat back to you.

---

## 12. Cross-cutting workstreams

| Workstream | Ongoing responsibilities |
|---|---|
| Security and privacy | Encryption, credential handling, access logs, retention limits, the AI kill switch, minimized data sent to AI providers |
| Workspace compatibility | Versioned workspace format with migrations; test that Hosted, Local, and Local+ round-trip without data loss |
| Local usability and support | Installer signing, OS matrix testing, update rollouts and rollbacks, health screen, diagnostics, onboarding checklist |
| Legal and compliance | Fair housing, consumer reports, payments, state licensing and trust rules, terms of service |
| Product feedback | Weekly pilot check-ins, exit interviews at day 60, feature requests tied to phase gates |

---

## 13. Open decisions

| Decision | Options | When to decide |
|---|---|---|
| Default posture | Hosted default with local as ownership option (assumed here) vs. keep local as default | Deployment checkpoint after Phase 0 |
| Hosted architecture | Single-tenant hosted copy (simpler) vs. end-to-end encrypted sync (harder, stronger ownership story) | Start of Phase 1 |
| Managed AI provider and terms | Provider choice, data-retention terms, cost per customer, pricing pass-through | Phase 1 |
| Remote support tooling | Consented screen-sharing or a purpose-built diagnostics channel | Phase 1 |
| Supported platforms and OS versions | Mac, Windows, or both; minimum versions | Phase 0 |
| Payments partner | Compare fees, ACH returns, platform terms, payout speed | Start of Phase 2 |
| Relay hosting and model | Managed queue vs. custom service; retention and encryption design | Start of Phase 2 |
| Bank aggregator | Compare coverage, cost, and terms | Start of Phase 4 |
| Pricing by option | Setup fee, monthly price by option, per-door vs. flat | Test in Phase 0 interviews; finalize in Phase 6 |
| Key escrow | Offer optional escrow vs. customer-only keys | Phase 0 |

---

## 14. Metrics by phase

**Usability metrics (track from Phase 0 onward)**
- Setup completion rate without a live support call.
- Time from install to first imported property.
- Update success rate and rollbacks needed.
- Restore success rate and time to restore on a new computer.
- Support contacts per install in the first 30 days.
- Expired-connection alerts resolved without help.

**By phase**
- **Phase 0:** interviews completed; pilot conversion; onboarding time; deployment preference.
- **Phase 1:** hosted vs. local choices; managed AI cost per customer; hosting cost per customer; round-trip success.
- **Phase 2:** share of rent collected via links; failed or returned payments handled; relay delivery reliability.
- **Phase 3:** weekly mobile users; owner links opened or approved.
- **Phase 4:** assistant seat activity; hours saved on reconciliation; e-sign completion rate.
- **Phase 5:** accountant acceptance; open review items.
- **Phase 6:** retention, support hours per customer by option, tier mix, referral rate.

---

## 15. Stop, pivot, or slow-down signals

- Most pilots leave after 60 days citing missing payments, and Phase 2 doesn't reverse it: consider partnering or integrating with an existing platform rather than competing on features.
- Setup or support time for local eats the margin: steer customers to Hosted or Managed Local, tighten the support matrix, or reprice.
- Most customers choose Hosted: local becomes a small ownership option, and your positioning rests on the workflow, AI-with-approval design, and export guarantees rather than on "local."
- Customers reject any cloud component: stay Local and lean on concierge service, and accept a smaller niche.
- Security or compliance cost grows faster than revenue: pause new integrations until the foundation is stable.

---

## 16. Things to verify before committing

- Current fees, terms, and API limits for any payments, bank-aggregator, e-sign, and screening providers (these change).
- AI provider data-retention and usage terms before enabling a managed AI default.
- Code-signing and developer-program requirements and costs for each platform you ship.
- State requirements for managers who hold client funds.
- Whether competitors have added AI intake or local-data options since this was written; check before repeating any claim about differentiation.
