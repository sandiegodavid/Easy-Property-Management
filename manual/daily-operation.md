# Daily operation

[Manual contents](README.md)

## Begin and end the day

1. Start the application using [the supplied launcher command](installation.md#3-start-and-open).
2. Open **Home**. Check the scope, capture/checked times and any unavailable warnings.
3. Handle urgent work and overdue obligations first. Use View all when counts exceed the preview.
4. Review due follow-ups, Waiting without a scheduled follow-up, upcoming dates and appointments.
5. Record actual payments, spending, contacts and physical work. Review information gaps separately.
6. Before stopping, save substantial unfinished input and reconcile uncertain saves. Follow your backup routine.

## Navigate and find records

Properties and Owners open directories. Search/filter, open the intended record, then use contextual sections for its related information. Main navigation returns to a portfolio destination; contextual links preserve the selected Property/Owner. Check visible filters before recording anything.

Home and Settings remain available. Hidden destinations are under **More**. Use **Search (Ctrl/⌘ K)** for supported record metadata; it does not search every attachment or raw source message. Include archived records when needed. If a continuation expires or recorded sources change, use the offered Restart while retaining filters.

Tasks and Conversations are available through contextual links and work navigation. For direct access, replace `/home` in your local URL with `/tasks`, `/conversations`, `/maintenance?tab=concerns`, `/parties` or `/settings/recovery` as appropriate.

## Expand an item

Click anywhere on its non-editable summary bar, including the text or chevron. Click again to collapse. With keyboard focus on the bar, Enter or Space toggles it. Inputs and action buttons are inside the expansion. Collapse does not save, discard, complete or change the record. More than one item can remain open.

## Read Home correctly

| Section | Meaning and next step |
| --- | --- |
| Needs action | Complete supported action list, including urgent repairs, due/late rent, due Tasks/follow-ups/reminders, ordinary unresolved work and reviews. Expand, inspect reasons and use the owning workflow. |
| Waiting | Explicitly awaiting a person/event. Verify whom/what and next follow-up; Not scheduled means no date is set. Waiting does not remove deadlines or urgency. |
| Upcoming | Future work in the selected 7/30/90-day horizon. Some source-specific reviews can already be actionable. |
| Calendar and appointments | Recorded Maintenance appointments. Completion of an appointment does not resolve the repair. |
| Information review | Missing required information or review needs. Resolve the underlying record; acknowledgment cannot fill missing facts. |
| Money | Recorded activity for the exact displayed inclusive dates, not bank balance, profit or owner entitlement. Open the metric's contributing records. |
| Inventory | Active-property vacancy/unknown Spaces. Unknown occupancy is not vacant. |

Home includes unresolved obligations on archived properties. All-properties scope also includes Tasks without a property; a property filter excludes those unlinked Tasks. Current Home has a **Property ID** field rather than a name picker; prefer contextual links or use the identifier shown in the Property workspace. Apply Home filters after changing scope, horizon or money dates.

The default money period is the full calendar month selected from server UTC time; it is not month-to-date. Property business dates use their stored time zones. Cross-zone appointments show their zone. Different sections may have different captured times.

Home loads asynchronously. **Refresh Home** starts a read; use Retry for a failed section. Live attention checks run on entry, focus, changes, due transitions and periodically while visible. New work can display **New items need attention**; use the offered update action while preserving your current form. Older lists and unavailable sources must not be read as an all-clear. No Dashboard cron or closed-app alert service is installed.

## Review information coverage

1. Open the relevant Property/Owner workspace and its coverage or Information review link.
2. Read the area, source facts and why it needs attention.
3. Correct missing records in their owning workflow, then refresh the area.
4. If manual review is requested, enter the allowed reason/date and submit the explicit review action.
5. Choose Not applicable only when the source rules offer it and the reason is true. Required gaps remain until the underlying records are corrected.

A later relevant source change may require renewed review. Maintenance acknowledgment records your review time; it does not certify that no physical issue exists.

## Save, resume and correct

A saved **unfinished form** is input, not an official record. An official Lease/Inspection/settlement draft is a separate stored draft and still does not mean execution/finalization/approval.

Use **Save unfinished form** when pausing. **Unfinished forms** in the header lets you resume. Submission uses the action's displayed Save button plus any required confirmations. Wait for its saved result and review the owning record. File bytes and credentials must be selected/entered again after restart.

If a save outcome is unknown, use **Check original result** before considering **Retry original attempt**. Do not start a second payment/issue/form to work around uncertainty. If another window changed the source, review its latest version while retaining edits. See [troubleshooting](troubleshooting.md).

Use Edit for supported mutable context; use Correct, Void, Replace or Archive when the record requires history. Deleting a Task does not erase its prior command history. Financial corrections never mean silently rewriting a settled receipt.
