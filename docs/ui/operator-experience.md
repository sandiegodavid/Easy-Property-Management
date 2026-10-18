# Operator experience

## Purpose and visual direction

The interface helps the operator recognize records, act deliberately and distinguish recorded information from missing or unavailable information. It uses warm neutral surfaces, restrained teal accents, readable typography and semantic Light/Dark tokens. Tables support comparison; contextual directories support recognition. Status always includes text, with color/icon as supporting cues. Theme changes preserve forms, focus, disclosures and query state.

Core browser workflows are delivered. Home provides live Needs action, Waiting, Upcoming, appointments, information review, recorded-money totals and active vacant/unknown Space drill-downs. [DASH-001](../archive/designs/DASH-001_DESIGN_COMPLETED_2026-10-14.md) records completed aggregation; [UI-002](../active/UI-002_DESIGN_preliminary.md) owns legal/HOA, spreadsheet imports, issue-proposal review and connected assistants. Configurable AI controls do not imply registered production models/actions.

## Navigation and scope

Default destinations are Home, Properties, Owners, Tenants, Leasing, Money, Maintenance, Providers and Settings. Tenants opens `/tenants`, including tenant profiles and tenant-role workflows. Shared person and contact records use `/parties`; opening that path without a record or person workflow goes to the Tenants directory. Party terminology, navigation preference IDs and record IDs remain internal contracts. Home/Settings are fixed. Other destinations can be hidden/reordered and restored to defaults. Hidden available destinations remain under More, in search and through context; preferences never remove obligations.

Properties and Owners open searchable directories before individual workspaces. Contextual tabs preserve their selected Property/Owner; main navigation returns to portfolio-wide destinations. Filters are visible/removable. Directory criteria, bounded page position and return context are retained. Record links use typed internal targets rather than arbitrary server URLs. Owners aggregate related properties, including former relationships; no client-owner Party is invented for the local operator. Owner money is explicit-period whole-property activity, not entitlement.

Top-level sidebar destinations have no parent link. Detail, form and secondary pages place one context-aware **← Back to …** link above their main heading; do not repeat that parent link at the bottom. Prefer the originating record or filtered directory, retaining its URL filters, tab, page and click-time scroll position. Direct URLs use an owning-directory/record fallback, never arbitrary browser history. Shared navigation retains at most eight same-workspace parent entries in router history, rejects unsafe/stale return targets, and leaves modified-click/new-tab behavior intact. Home's separate ancestor shortcut remains available during Home-originated workflows. Unsaved-form protection still applies to parent navigation.

Page-level tabs share Property Detail's visual treatment: teal active text and underline, a soft active background, consistent spacing and visible keyboard focus. They stay on one horizontally scrollable row on narrow screens. Route tabs remain links with `aria-current="page"`; in-page tabs retain tab/tabpanel semantics and arrow-key navigation. Filters, segmented controls, pagination and action links are not styled as page tabs. Use the shared `.page-tabs` class rather than page-specific tab styling.

Search and read filters apply automatically: dropdowns and checkboxes immediately, text and date input after a short pause. Filter changes restart pagination, preserve focus and scroll, and replace the current URL rather than adding a history entry for each change. Back/Forward restores the displayed filter values; leaving a page cancels pending input. Invalid date ranges or incomplete record IDs retain the input for correction. Applying filters never submits a record-editing form.

## Inline disclosure and forms

The entire non-editable item summary bar toggles details immediately beneath it. The visible guidance is “Click anywhere on an item’s summary bar to expand or collapse its details.” The bar contains text/status/chevron, with no inputs, nested links or separate action buttons. Enter/Space activate its native button. Several rows can expand independently; aria-expanded/controls and unique panel IDs reflect visibility. Local Collapse restores trigger focus.

Forms, actions and navigation sit inside the expansion. Collapse preserves unfinished input and makes no domain transition. Short actions stay contextual; substantial Lease, Inspection and settlement work uses dedicated workflows. Consequential changes require owning-source review and explicit confirmation where required. Current records, original operation receipts, source evidence, saved incomplete forms and official drafts remain visibly distinct.

Workflow forms use one bottom action row with the primary action first and the secondary “Save unfinished form” beside it, wrapping on narrow screens. Create labels name the action directly, such as “Create property”, “Create task”, “Record rent receipt” or “Add contact details”. Edit labels name the change, such as “Save property changes”, “Save task changes”, “Save contact details” or “Save ownership change”. Source-review controls sit with form status, and create/edit return navigation appears above the form. AI draft review uses the same action styling with its own “Save draft edits” and “Dismiss draft” actions; connection setup uses a “Create connection” action and does not offer an unfinished-form save.

Autosave exposes acknowledged saving/saved/failed/conflicted states. Conflicts preserve input for explicit current-source review. Lost responses retain the original key and reconcile before another dispatch. File recovery stores metadata/hash and requests matching byte reselection. Partial success identifies what committed: an attachment failure never invites re-entering a committed payment.

## Availability, information review and assurance

Loading, successful empty, unavailable, partial and retained stale results have distinct presentations. Failed money reads never show zero balances. Independent section failures preserve unaffected sections. Counts/timestamps/continuations and domain classifications come from the server. Unknown occupancy is not vacancy; no empty issue list proves a property is problem-free.

Information review distinguishes Recorded, Missing required information, Needs review and justified Not applicable. Each gap explains why it exists and links to its resolution. Manual acknowledgment retains review provenance and cannot fill a required gap. Relevant source changes require explicit renewed review; unrelated events do not invalidate all information reviews. Waiting names the person/event and optional follow-up; undated waiting is visibly unscheduled. Source deadlines, urgency and independent reminders remain intact.

## Accessibility and local operation

Semantic landmarks, labeled native controls, keyboard actions, skip navigation, focus restoration, error summaries and restrained status announcements support accessible operation. Both themes retain contrast and visible focus; reduced motion is respected. Supported narrow layouts stack actions and preserve readable content/tables. Recorded acceptance covers keyboard/focus, 200% text reflow and automated WCAG checks at 390px, 900px and 1440px; these proofs do not claim exhaustive accessibility certification.

The single-operator application runs locally without sign-in. Responsive windows do not imply remote access. Unsupported routes explain capability limits. Files are accessed through validated APIs; secrets, source text and financial records stay out of browser storage.

## Deep dives

- [Frontend architecture](frontend-architecture.md): code, state, API and recovery boundaries.
- [Workflow guide](workflows.md): domain journeys and source authority.
- [Validation guide](validation.md): executable evidence and completed delivery records.
- [Active work](../active/README.md): remaining capabilities.
- [Visual reference](../../demo/operator-experience.html): synthetic design comparison; future prototype states are not current capabilities.
