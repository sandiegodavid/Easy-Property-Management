# Phased Roadmap: From Local MVP to a Local-First Product

**Product:** Property management app for independent managers (about 10–50 doors, managing for owners)
**Direction:** Local-first, not local-only. The customer's workspace stays the system of record; small cloud pieces handle only what must be always on.

**How to read this document**
- The roadmap is **gate-based, not date-based.** A phase starts only when the previous phase's exit gate is met, because each gate depends on what pilot customers say.
- Effort sizes (S / M / L) are relative placeholders. I haven't seen your codebase, so confirm them with whoever builds it.
- Numbers marked **[hypothesis]** are starting points to test, not recommendations.
- Nothing here is legal advice. Trust-accounting and licensing questions need review by a qualified professional in each state you serve.

---

## 1. Guiding principles

1. **Ownership contract.** One-click full export in a documented open format. Every hosted feature can be switched off. A "what leaves this computer" screen lists each data flow and its consent status.
2. **Same workspace everywhere.** Local, Local+, and Hosted all use one workspace format, so moving between them is a download and an import.
3. **Don't hold funds or card data.** Use a payments partner's hosted pages. The app records events; it does not move money.
4. **AI drafts, the operator approves.** Nothing is sent, paid, or committed automatically. Keep the AI kill switch and consent prompts at every new integration.
5. **Build only what stops people paying.** Each phase is unlocked by pilot evidence, not by the feature list.
6. **Relay, don't store.** Any always-on service holds encrypted events in transit and nothing else. Records are created and kept in the workspace.

---

## 2. Phase overview

| Phase | Goal | Starts when | Exit gate (summary) |
|---|---|---|---|
| 0 | Pilot readiness and validation | Now | Backups proven; pilots running; interview decision rule met |
| 1 | Connectivity: payments and inbound relay | Phase 0 gate met | Pilots collect rent through the app; inbound items arrive while the computer is off |
| 2 | Reach: phone, owner links, hosted option | Phase 1 gate met | Pilots use mobile weekly; owners approve or view without asking you to send PDFs |
| 3 | Team and financial workflow | Phase 2 gate met | Assistants use their own seats; bank matching and e-sign/screening in daily use |
| 4 | Trust-accounting readiness | Professional review complete | Owner ledgers and reconciliation reports accepted by customers' accountants |
| 5 | Scale and packaging | Consistent retention across 20+ customers [hypothesis] | Tiers priced, support process running, security posture documented |

---

## 3. Phase 0: Pilot readiness and validation

**Goal:** Make the current local MVP safe to put in front of paying pilot customers, and learn whether the workflow alone earns money.

**Build**
- **Automatic encrypted backups** to storage the customer already owns (iCloud, Google Drive, Dropbox, OneDrive, external drive, or NAS). Encrypt on the device with a customer-held key; provide a recovery key to print or save in a password manager.
- **Backup health on Home.** A stale or failed backup appears as a Needs action item like any other unresolved thing.
- **Versioned snapshots**, for example daily for two weeks, weekly for two months, monthly for a year. Always snapshot before imports and upgrades.
- **Restore drill:** a guided "new computer" restore that finishes in minutes and walks through re-authorizing email, SMS, and AI credentials.
- **Monthly test-restore prompt.**

**In parallel (no build required)**
- Run 8–12 interviews and pick 5–10 paid pilots using the interview script and pilot offer.
- Track the scorecard after every interview.

**Not in scope:** payments, portals, mobile, multi-user.

**Effort:** M (backup and restore engineering plus testing on every supported OS).

**Exit gate**
- Restore tested on each supported platform, including a full new-machine restore.
- At least 4 of 10 interviewees describe a recent painful workflow the app addresses, and at least 2–3 say yes to a paid pilot **[hypothesis]**.
- At least 5 pilots live with a verified first backup.

**Risks and mitigations**
- *Backup key loss:* offer printed recovery key at setup; state plainly that a lost key means lost data unless the customer opts into key escrow later.
- *Support load per install:* keep a written setup checklist and time every onboarding to learn the real cost.

**Stop or pivot signal:** most interviewees say online rent collection is a prerequisite. Then skip straight to scoping Phase 1 before selling further.

---

## 4. Phase 1: Connectivity (payments and inbound relay)

**Goal:** Remove the most likely first objection, "it can't collect rent," and stop missing inbound items when the computer is off.

**Build**
- **Payments through a partner.** Payment links and a hosted tenant pay page from a payments provider. Webhooks record payment events in the workspace. Reconcile against the coverage states (recorded, missing, not applicable).
- **Relay service.** A small, always-on mailbox that holds encrypted events (inbound email, SMS, payment notifications) until the app pulls them. Records are created locally and the relay deletes after delivery.
- **"What leaves this computer" screen** listing each data flow, its provider, and consent state.
- **Notification of failed or returned payments** as Needs action items.

**Not in scope:** holding funds, card data storage, owner payouts through the app.

**Dependencies:** choose a payments partner (check current fees, ACH return handling, and terms for platforms); decide relay hosting and encryption model.

**Effort:** L (partner integration, webhooks, relay security).

**Exit gate [hypothesis]**
- At least half of pilot customers collect some rent through payment links.
- Inbound items reach the app after the computer has been off, with no lost or duplicated records over 30 days.
- No security incident, and the relay holds no data past delivery.

**Risks and mitigations**
- *Payment failures and returns:* build clear states for pending, cleared, and returned payments before pilots use it.
- *Regulatory scope creep:* have the payments partner hold funds and handle money-transmission obligations; confirm this with counsel.
- *Relay becomes a data store:* enforce short retention, encryption at rest, and audits of what it retains.

---

## 5. Phase 2: Reach (phone, owner links, hosted option)

**Goal:** Let the operator work away from their desk, and let owners and tenants interact without you emailing PDFs.

**Build**
- **Phone companion.** Today's Needs action, contact lookup, and photo upload into the inbox. Read-first, with limited edits.
- **Owner links.** Read-only statement links, and expiring approval links for disbursements. Each link shows one person's own data and can be revoked.
- **Portal-lite for tenants.** Magic-link maintenance request form and pay page. No account required.
- **Hosted option.** A single-tenant hosted copy of the workspace, plus a "download my workspace" button. Decide between this and end-to-end encrypted sync; I'd lean toward the hosted copy because it is simpler to build and support.
- **Packaging decision:** define Local, Local+ (encrypted backup plus relay), and Hosted.

**Not in scope:** multi-user editing, full tenant and owner portals with accounts.

**Effort:** L.

**Exit gate [hypothesis]**
- Most pilot customers use the phone companion weekly.
- Owners approve or view through links without the operator emailing files.
- At least a few pilots choose Hosted, and none report that moving between tiers lost data.

**Risks and mitigations**
- *Link leakage:* short expiry, single-purpose tokens, revoke on demand, access logs.
- *Sync conflicts:* avoid true multi-device sync in this phase; the hosted copy is the single source when enabled.

---

## 6. Phase 3: Team and financial workflow

**Goal:** Support an assistant or second staff member, and connect the money workflow.

**Build**
- **Second seat and roles** (owner/operator, assistant with limited permissions, read-only accountant). Audit history shows who did what.
- **Bank feeds through an aggregator**, matched against expected payments using the existing coverage states.
- **E-signature integration** through a provider, with signed PDFs returned into the record.
- **Tenant screening partner integration.** Send applicants to the provider so you never store their sensitive identifiers; store only the result and consent record. Keep the brief's fair-housing and consumer-report cautions.
- **Listing syndication** only if pilots ask for it.

**Dependencies:** Hosted option from Phase 2 (multi-user is easier with a hosted source of truth); aggregator and provider terms.

**Effort:** L.

**Exit gate [hypothesis]**
- Assistants use their own seats weekly.
- Bank matching cuts manual reconciliation time for most customers.
- At least half of new leases use the e-sign flow.

**Risks and mitigations**
- *Permission mistakes:* start with three fixed roles rather than custom permissions.
- *Screening compliance:* use a provider, keep human review for every decision, and get legal review of your notices and flows.

---

## 7. Phase 4: Trust-accounting readiness

**Goal:** Serve managers who hold client-owner funds, only after professionals confirm the rules.

**Before any build**
- Review each target state's licensing and client-trust-account requirements with a lawyer or licensed professional.
- Talk to customers' accountants about what they need to accept the records.

**Build (subject to that review)**
- **Owner ledgers** that show every receipt, disbursement, and balance per owner.
- **Reconciliation reports** the accountant can use (bank vs. ledger, three-way where required).
- **Disbursement approval trail** that builds on the existing approve-and-record flow.
- **State-aware checklists**, marked clearly as planning aids rather than compliance guarantees.

**Not in scope:** claiming legal compliance; moving funds.

**Effort:** L, plus professional review cost.

**Exit gate**
- Reports accepted by at least a few customers' accountants.
- Professional review complete for each state you market in.

**Risks and mitigations**
- *False assurance:* avoid words like "compliant" until reviewed; keep the brief's approach of showing sources and requiring human verification.

---

## 8. Phase 5: Scale and packaging

**Goal:** Turn a set of working pilots into a repeatable business.

**Build and prepare**
- Publish pricing for Local, Local+, and Hosted tiers.
- Onboarding that doesn't need you: guided import, checklist, help articles.
- Support process: response targets, escalation path, status page for the relay and hosted services.
- **Security posture:** incident response plan, access controls, vendor list, and a decision on formal audits (for example SOC 2) once customers ask for them.
- Data-processing terms and a plain-language privacy statement.

**Exit gate [hypothesis]**
- 20+ paying customers with consistent retention.
- Support hours per customer are low enough to price sustainably.
- Clear answer to "why not Buildium" that customers repeat back to you.

---

## 9. Cross-cutting workstreams

| Workstream | Ongoing responsibilities |
|---|---|
| Security and privacy | Encryption, credential handling, access logs, retention limits, the AI kill switch, minimized data sent to AI providers |
| Workspace compatibility | Versioned workspace format with migrations; test that Local, Local+, and Hosted round-trip without data loss |
| Support operations | Onboarding checklist, time per install, common failure playbook, backup/restore help |
| Legal and compliance | Fair housing, consumer reports, payments, state licensing and trust rules, terms of service |
| Product feedback | Weekly pilot check-ins, exit interviews at day 60, tracked feature requests tied to phase gates |

---

## 10. Open decisions

| Decision | Options | When to decide |
|---|---|---|
| Hosted vs. encrypted sync | Single-tenant hosted copy (simpler) vs. end-to-end encrypted sync (harder, stronger ownership story) | Start of Phase 2 |
| Payments partner | Compare fees, ACH returns, platform terms, payout speed | Start of Phase 1 |
| Bank aggregator | Compare coverage, cost, and terms | Start of Phase 3 |
| Relay hosting and model | Managed queue vs. custom service; retention and encryption design | Start of Phase 1 |
| Supported platforms | Mac, Windows, or both at launch | Phase 0 |
| Pricing | Setup fee, monthly by tier, per-door vs. flat | Test in Phase 0 interviews; finalize in Phase 5 |
| Key escrow | Offer optional escrow vs. customer-only keys | Phase 0 |

---

## 11. Metrics by phase

- **Phase 0:** interviews completed; pilot conversion; time to onboard; restore success rate.
- **Phase 1:** share of rent collected via links; failed or returned payments handled; relay delivery reliability.
- **Phase 2:** weekly mobile users; owner links opened or approved; hosted adoption.
- **Phase 3:** assistant seat activity; hours saved on reconciliation; e-sign completion rate.
- **Phase 4:** accountant acceptance; open review items.
- **Phase 5:** retention, support hours per customer, tier mix, referral rate.

---

## 12. Stop, pivot, or slow-down signals

- Most pilots leave after 60 days citing missing payments, and Phase 1 doesn't reverse it: consider partnering or integrating with an existing platform rather than competing on features.
- Support time per customer eats the margin at your pilot price: change the price, tighten the target segment, or move to Hosted sooner.
- Customers reject any cloud component: stay Local and lean on concierge service, and accept a smaller niche.
- Security or compliance cost grows faster than revenue: pause new integrations until the foundation is stable.

---

## 13. Things to verify before committing

- Current fees, terms, and API limits for any payments, bank-aggregator, e-sign, and screening providers (these change).
- State requirements for managers who hold client funds.
- Whether competitors have added AI intake or local-data options since this was written; check before repeating any claim about differentiation.
