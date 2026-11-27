# Operator experience

## Purpose, terms and visual direction

The interface helps the operator recognize records, act deliberately and distinguish recorded information from missing or unavailable information. It uses warm neutral surfaces, restrained teal accents, readable typography and semantic Light/Dark tokens. Tables support comparison; contextual directories support recognition; modest property photos aid recognition without decorative dashboard cards. Status always includes text, with color/icon as supporting cues. Theme changes apply immediately via CSS tokens and preserve forms, focus, disclosures and query state.

Core experience terms and domain UI invariants:

- **Needs action:** Supported work requiring operator action now (urgent issues first, then overdue, due-today and undated decision work).
- **Waiting:** Work awaiting a person or event with visible follow-up status; never resolves its source record.
- **Upcoming:** Work with a future action date (next seven days by default, with a longer-range option).
- **Coverage:** Visibility into recorded, missing, review-needed and non-applicable information for supported responsibilities; never an opaque green health score or compliance certification.
- **Property / Owner workspace:** Contextual views composing authoritative records rather than copying them. Owner workspaces distinguish property-level facts from amounts attributable to that owner; multiple owners do not imply known financial shares.
- **Distinct lifecycles and money categories:** Unknown occupancy/availability is never vacant/available. Task completion, reminder dismissal, appointment completion and issue/concern resolution remain distinct actions. Scheduled checks, received rent, held deposits, quotes and paid expenses remain distinct financial concepts.

Core browser workflows are delivered. Home provides live Needs action, Waiting, Upcoming, appointments, information review, recorded-money totals and active vacant/unknown Space drill-downs. [DASH-001](../archive/designs/DASH-001_DESIGN_COMPLETED_2026-10-14.md) records completed aggregation; [functional intake/review backlogs](../active/DATA-002_DESIGN.md) owns legal/HOA, spreadsheet imports, issue-proposal review and connected assistants. Configurable AI controls do not imply registered production models/actions.

## Navigation and scope

Default destinations are Home, Properties, Owners, Tenants, Leasing, Money, Maintenance, Providers and Settings. Tenants opens `/tenants`, including tenant profiles and tenant-role workflows. Shared person and contact records use `/parties`; opening that path without a record or person workflow goes to the Tenants directory. Party terminology, navigation preference IDs and record IDs remain internal contracts. Home/Settings are fixed. Other destinations can be hidden/reordered and restored to defaults. Hidden available destinations remain under More, in search and through context; preferences never remove obligations.

Properties and Owners open searchable directories before individual workspaces. Contextual tabs preserve their selected Property/Owner; main navigation returns to portfolio-wide destinations. Filters are visible/removable. Directory criteria, bounded page position and return context are retained. Record links use typed internal targets rather than arbitrary server URLs. Owners aggregate related properties, including former relationships; no client-owner Party is invented for the local operator. Owner money is explicit-period whole-property activity, not entitlement.

Top-level sidebar destinations have no parent link. Detail, form and secondary pages place one context-aware **← Back to …** link above their main heading; do not repeat that parent link at the bottom. Prefer the originating record or filtered directory, retaining its URL filters, tab, page and click-time scroll position. Direct URLs use an owning-directory/record fallback, never arbitrary browser history. Shared navigation retains at most eight same-workspace parent entries in router history, rejects unsafe/stale return targets, and leaves modified-click/new-tab behavior intact. Home's separate ancestor shortcut remains available during Home-originated workflows. Unsaved-form protection still applies to parent navigation.

Page-level tabs share Property Detail's visual treatment: teal active text and underline, a soft active background, consistent spacing and visible keyboard focus. They stay on one horizontally scrollable row on narrow screens. Route tabs remain links with `aria-current="page"`; in-page tabs retain tab/tabpanel semantics and arrow-key navigation. Filters, segmented controls, pagination and action links are not styled as page tabs. Use the shared `.page-tabs` class rather than page-specific tab styling.

Search and read filters apply automatically: dropdowns and checkboxes immediately, text and date input after a short pause. Filter changes restart pagination, preserve focus and scroll, and replace the current URL rather than adding a history entry for each change. Back/Forward restores the displayed filter values; leaving a page cancels pending input. Invalid date ranges or incomplete record IDs retain the input for correction. Applying filters never submits a record-editing form.

## Inline disclosure and forms

The entire non-editable item summary bar toggles details immediately beneath it. The visible guidance is “Click anywhere on an item’s summary bar to expand or collapse its details.” The bar contains text/status/chevron, with no inputs, nested links or separate action buttons. Enter/Space activate its native button. Several rows can expand independently; aria-expanded/controls and unique panel IDs reflect visibility. Local Collapse restores trigger focus.

Forms, actions and navigation sit inside the expansion. Collapse preserves unfinished input and makes no domain transition. Short actions stay contextual; substantial Lease, Inspection and settlement work uses dedicated workflows. Consequential changes require owning-source review and explicit confirmation where required. Current records, original operation receipts, source evidence, saved incomplete forms and official drafts remain visibly distinct.

Workflow forms keep labels visible (placeholders are examples, never labels) and mark required/optional state explicitly. They use one bottom action row with the primary action first and the secondary “Save unfinished form” beside it, wrapping on narrow screens. Create labels name the action directly, such as “Create property”, “Create task”, “Record rent receipt” or “Add contact details”. Edit labels name the change, such as “Save property changes”, “Save task changes”, “Save contact details” or “Save ownership change”. Source-review controls sit with form status, and create/edit return navigation appears above the form. AI draft review uses the same action styling with its own “Save draft edits” and “Dismiss draft” actions; connection setup uses a “Create connection” action and does not offer an unfinished-form save.

Reserve confirmation dialogs for consequential lifecycle actions (void, archive with impact, lease execution/termination, settlement approval and explicit source-record closure); each confirmation names the record and irreversible consequence without repeating routine form fields. After a successful command, update the authoritative result in place, announce it and expose the next relevant step—do not auto-navigate away when the operator needs to inspect the result or retry a secondary operation. Toasts supplement the updated page and are never the sole evidence that an official write occurred.

Autosave exposes acknowledged saving/saved/failed/conflicted states (`Unsaved changes`, `Saving…`, `Draft saved <time>`, `Save failed`). Warn before abandoning unsaved short-form input until a save succeeds. Conflicts preserve input for explicit current-source review. Lost responses retain the original key and reconcile before another dispatch. File recovery stores metadata/hash and requests matching byte reselection. Partial success identifies what committed: an attachment failure never invites re-entering a committed payment.

### Correction history

Show the current effective record first, paired with a compact **History** link and relevant correction labels. Financial and authoritative corrections use explicit void-and-replace flows that explain impact and preserve original records. Everyday history exposes what happened, when, the recorded actor, reasons and evidence; technical audit metadata stays secondary, and aggregates retain source-record drill-down.

## Availability, progressive setup and information review

Loading, successful empty, unavailable, partial and retained stale results have distinct presentations. Failed money reads never show zero balances. Independent section failures preserve unaffected sections. Counts/timestamps/continuations and domain classifications come from the server. Unknown occupancy is not vacancy; no empty issue list proves a property is problem-free.

Setup is progressive and resumable: allow a minimal valid record, then offer a resumable setup checklist for applicable questions. Missing information blocks only actions that require it. Information review distinguishes **Recorded**, **Missing required information**, **Needs review** and justified **Not applicable** (never a bypass for required information). Supported areas include occupancy/availability, lease, rent tracking, deposits and maintenance review. When conditions coexist, lead with the most actionable and retain others in detail. Each gap explains why it appeared and links to its resolution. Manual acknowledgment retains review provenance and cannot fill a required gap. Relevant source changes trigger explicit renewed review; unrelated events do not expire all reviews on an arbitrary timer. Waiting names the person/event and optional follow-up; undated waiting shows `Follow-up not scheduled`. Deferring reminders never hides urgency, rewrites source deadlines or resolves the underlying issue.

## Built-in AI assistance principles

Built-in AI controls live under Settings → **AI assistance**; AI remains optional and never becomes a permanent navigation destination. Keep default presentation brief and expand setup, scope, limits and diagnostics beneath D35 summary bars.

- **Explicit route and consent:** Present **Off**, **On this device** and **Cloud service** with only registered, evaluated adapters/models. Cloud setup uses write-only credentials stored in the OS credential store (never in workspace data, browser storage or backups), a synthetic connection test and explicit destination/data-class disclosure; changing destination requires explicit permission. On-device setup shows runtime/model requirements and verified status without automatic background downloads.
- **Truthful availability and no silent fallback:** Show task availability separately (e.g., summaries Ready while transcription Unsupported). Unsupported or unavailable actions explain why and preserve manual work. Never silently fall back to cloud or another vendor; an explicit “Try with [provider]” must name the destination, preserve the draft and re-check disclosure/governance.
- **Governance and draft review:** **Pause all AI assistance** blocks new model calls; late in-flight results must still pass current governance, and existing drafts remain reviewable. Label supported drafts with **Generated with [provider/model] · On this device/Cloud service**, keep source, bounded governed input, suggestion and operator edits separate, surface stale-source conflicts and require source-checked approval through the owning domain contract.

## Accessibility, responsive layout and local operation

Target **WCAG 2.2 AA** for supported workflows. Semantic landmarks, heading order, labeled native controls, keyboard actions (Enter/Space on disclosure bars; no arrow-key accordion override since multiple rows stay open), skip navigation, `:focus-visible` contrast in both themes, error summaries linking to invalid controls, restrained live-region announcements and `prefers-reduced-motion` support govern all views. Route changes move focus to the page heading and announce the title without stealing focus during background refresh. Dialogs provide an accessible name, initial focus, focus containment, safe Escape handling and focus restoration to the invoking control.

Layout adapts by available width using CSS grid/flex and container-aware rules (not JavaScript viewport branching):

- **≥ 1200px:** slim full sidebar and full evidence/table layouts.
- **768px–1199px:** compact sidebar; supporting columns collapse below the primary region.
- **< 768px:** single content column, accessible navigation drawer, horizontally safe tables or labeled row cards and stacked action groups.

Content remains usable at 200% zoom and at a 320 CSS-pixel viewport without two-dimensional page scrolling (data tables may use a labeled horizontal scroll region). Recorded acceptance covers keyboard/focus, 200% text reflow and automated WCAG checks at 390px, 900px and 1440px; these proofs do not claim exhaustive accessibility certification.

The single-operator application runs locally without sign-in. Responsive windows do not imply remote access. Unsupported routes explain capability limits. Files are accessed through validated APIs; secrets, source text and financial records stay out of browser storage.

## Deep dives

- [Frontend architecture](frontend-architecture.md): code, state, API and recovery boundaries.
- [Workflow guide](workflows.md): domain journeys and source authority.
- [Validation guide](validation.md): executable evidence and completed delivery records.
- [Active work](../active/README.md): remaining capabilities.
- [Visual reference](../../demo/operator-experience.html): synthetic design comparison; future prototype states are not current capabilities.

## Planned hosted and portal workflows

The current guide documents delivered operator behavior. [HOSTED-001](../hosting/design/mvp/delivery-plan.md#implementation-slices) adds Admin/operator setup, identity, usage/protection/progress and later subscription/update controls. Pilot 0 at H06 shows Free pilot usage/support, uses one maintenance window and exposes no paid upgrade, individual scheduling or idle-wake controls. [PORTAL-001/002](../active/PORTALS_IMPLEMENTATION_PLAN.md) later add role-scoped rent/late-fee/lease/payment views, tenant issues and owner concerns/reports, including matching operator publication/handling UI. Reuse interaction/accessibility patterns, with tenant/owner authorization enforced by the server. These are planned additions, not capabilities established by core UI acceptance.

## Stedana branding

The operator workspace uses the Stedana wordmark without a tagline. Hosted workspace sign-in uses the owner lockup with “property management for small portfolios and their owners.” Both follow the app theme. See the [branding checkpoint](stedana-branding-checkpoint.md).
