# Tasks, conversations and evidence

[Manual contents](README.md)

## Create and work a Task

Task details show deadlines and follow-ups in their saved scheduling zone, normally the property's zone. Reminder details use the related property's zone; unlinked reminders use your browser's zone. Home's combined schedule uses your browser's time and also shows source-local time when different. Recorded, updated and history times use your browser's zone. All-day dates stay on their original calendar day.

Open **Tasks** from Home or work navigation. Quick add begins with a title and due-date/no-date choice. A date creates an all-day deadline in the displayed time zone. Under **Optional Task details**, **Due at** offers an editable date/time picker and **Due time zone** selects its zone; choosing an exact time makes the deadline timed rather than all-day. Priority and related records are also optional. New deadline, reminder and follow-up time inputs default to the related property's time zone, including links through a rental unit, lease or maintenance issue. Without one related property, they use your browser's time zone. Saved or explicitly selected zones stay unchanged when editing or resuming a form.

1. Enter a clear action, correct priority and deadline/context.
2. Save; review the resulting Task rather than assuming saved input means creation.
3. Use filters for status, priority, overdue/today/next-seven-days/no-date and related records.
4. Start/Edit as appropriate. Complete with the actual outcome/note; Cancel for work no longer required.
5. Reopen explicitly when needed. Completed/cancelled outcome and time remain visible in history.

A completion checkbox inside expanded content opens the confirmed completion form. Delete is a separate action and retains command history. Completing a Task never resolves the linked repair, concern or Lease obligation.

## Waiting and follow-ups

Use **Set waiting context** on the Task. Name the person/event and, if useful, an exact follow-up time/zone. This replaces the complete waiting context; recheck every field before saving.

**Follow up at** uses an editable calendar/time picker in the selected time zone. Changing the time zone shows the same instant in that zone; editing the displayed clock time changes the follow-up. Times skipped by daylight saving are rejected without losing your input.

Use **Reschedule follow-up** to change the date or explicitly remove it. Date removal retains the label and shows Not scheduled. **Clear waiting context** removes waiting with confirmation; it does not acknowledge/dismiss reminders.

Due follow-ups become actionable at their exact instant; a future time today remains scheduled. An overdue Task can remain overdue while waiting. Completing/cancelling clears waiting; reopening does not recreate old waiting/reminders.

## Reminders

Add a reminder with its own time. Acknowledge or dismiss the specific reminder when appropriate. Reminder state, Task deadline and waiting follow-up are three separate concepts. Deferring follow-up cannot erase an actual deadline. Current reminders require the application to be running; do not assume phone, email or closed-app alerts.

The saved reminder confirmation and Task reminder details use the related property's time zone, even when the Task deadline uses a different zone. Reopening a checked submission uses the same display rule. Without a related property, they use your browser's zone.

## Record a conversation

1. Open **Conversations** (`/conversations`) or the related record's conversation link.
2. **Create conversation** with participants, channel, time zone, summary/details and correct property/lease/rent/issue context. The time is recorded automatically when you save; editing or correcting the conversation keeps that original time.
3. Edit a draft while it remains a draft.
4. **Record conversation** when it represents a real completed/received contact.
5. Use **Correct recorded conversation** with a reason for later correction; retain history.
6. Add a related follow-up Task where needed.

This is a manual ledger. Recording an email, call or message does not send it, fetch a mailbox or confirm delivery.

## Retain source evidence

Open **Conversations → Retained sources** (`/conversations?intake=true`). These are preserved imported messages, transcripts and files, separate from the conversation ledger.

- **Retain source:** enter the actual source channel, occurrence context, participants and retained content. Describe provenance truthfully; a pasted item is not automatically authenticated external delivery.
- **Import source evidence:** select the supported evidence files/content and preserve their ordered roles. This is not Excel/property import.
- **Correct source:** correct retained evidence through a new retained revision with an explanation.
- **Supersede source:** record the explicit replacement lineage after reviewing both records.
- **Dismiss source:** record the supported no-further-attention decision; it does not erase evidence or resolve an issue.
- **Reopen source:** reopen under the source lifecycle rules when review is required again.

Use available filters and bounded Next pages. Open full evidence through its source record; content can be unavailable if the required audit cannot be recorded. Review duplicate candidates and retained revisions/history before submitting another source. Failed/superseded records preserve history and guard unsupported changes.

Retaining evidence does not automatically create a Maintenance issue or recorded conversation. Create the required manual record explicitly and use supported links; AI proposal approval and assistant ingestion are separate capabilities.

## Attach, inspect and archive files

1. Start from the actual Lease, issue, expense, deposit, owner report or Inspection observation.
2. Choose its Attach action, select the file and review purpose/context.
3. Wait for the file result. If the business record saved but upload failed, retry only evidence.
4. Open metadata/history and download only when content is available.
5. Archive the association with required reason/confirmation when incorrect or no longer active. This is not a general permanent-delete action.

Do not place files manually into managed `files/` or edit database rows. Recovery saves the expected name/size/hash, not bytes; reselect the original file after restart. Use the available contextual file actions for evidence and installer commands for workspace administration, not the general Property Documents placeholder.
