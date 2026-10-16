# Operator experience

## Purpose and visual direction

The interface helps the operator recognize records, act deliberately and distinguish recorded information from missing or unavailable information. It uses warm neutral surfaces, restrained teal accents, readable typography and semantic Light/Dark tokens. Tables support comparison; contextual directories support recognition. Status always includes text, with color/icon as supporting cues. Theme changes preserve forms, focus, disclosures and query state.

Core browser workflows are delivered. Home provides live Needs action, Waiting, Upcoming, appointments, information review, recorded-money totals and active vacant/unknown Space drill-downs. [DASH-001](../archive/designs/DASH-001_DESIGN_COMPLETED_2026-10-14.md) records completed aggregation; [UI-002](../active/UI-002_DESIGN_preliminary.md) owns legal/HOA, spreadsheet imports, issue-proposal review and connected assistants. Configurable AI controls do not imply registered production models/actions.

## Navigation and scope

Default destinations are Home, Properties, Owners, Leasing, Money, Maintenance, Providers and Settings. Home/Settings are fixed. Other destinations can be hidden/reordered and restored to defaults. Hidden available destinations remain under More, in search and through context; preferences never remove obligations.

Properties and Owners open searchable directories before individual workspaces. Contextual tabs preserve their selected Property/Owner; main navigation returns to portfolio-wide destinations. Filters are visible/removable. Directory criteria, bounded page position and return context are retained. Record links use typed internal targets rather than arbitrary server URLs. Owners aggregate related properties, including former relationships; no client-owner Party is invented for the local operator. Owner money is explicit-period whole-property activity, not entitlement.

## Inline disclosure and forms

The entire non-editable item summary bar toggles details immediately beneath it. The visible guidance is “Click anywhere on an item’s summary bar to expand or collapse its details.” The bar contains text/status/chevron, with no inputs, nested links or separate action buttons. Enter/Space activate its native button. Several rows can expand independently; aria-expanded/controls and unique panel IDs reflect visibility. Local Collapse restores trigger focus.

Forms, actions and navigation sit inside the expansion. Collapse preserves unfinished input and makes no domain transition. Short actions stay contextual; substantial Lease, Inspection and settlement work uses dedicated workflows. Consequential changes require owning-source review and explicit confirmation where required. Current records, original operation receipts, source evidence, saved incomplete forms and official drafts remain visibly distinct.

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
