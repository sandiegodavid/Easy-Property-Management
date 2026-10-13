# Manual communications and follow-up

## Responsibility

Communications is a local ledger of operator-recorded interactions with saved Parties. It owns drafts, immutable recorded content, participant snapshots, typed links and explicit correction history. It does not fetch mail, send messages or interpret a retained source as an interaction.

## Recording and correction

Create/edit a draft or record an interaction directly, with channel/direction/occurrence and selected participants. Validate every typed target through its owning source on the caller's connection. Recorded interactions are corrected explicitly while prior content remains retained; a later Party rename does not rewrite participant snapshots.

Follow-up is an explicit linked Task consequence. Source communication lifecycle, Task completion and waiting remain independent. Create/patch/record/correct commands require revision and key, retain typed original receipts and provide read-only operation lookup. Audit and required Task effects share the writer transaction and correlation.

## Context and source links

Supported contexts include Property/Space, Lease, maintenance issue, owner concern and Intake source through registered validators. A source link preserves provenance; it never creates/synchronizes Intake evidence or copies it into official issue fields. No automatic cross-domain record is inferred from text.

## API and privacy

`/api/communications` supplies draft/record/correction/detail/list routes and `/operations/{id}` recovers original results. Context reads are bounded and owner-aware. Global activity/search discloses only approved metadata; recorded body and contextual notes remain within the owning ledger detail and redacted audit policies.

For original source snapshots use [Intake](intake.md). For reminder/waiting semantics use [Tasks](tasks.md).

## Browser workflow boundary

Manual conversation browser records expose recorded/corrected history and optional Task follow-up with source context. Retained evidence is reached separately under Conversations; recording an interaction does not send a message or approve an issue proposal. See the [workflow guide](../ui/workflows.md) and [browser validation](../ui/validation.md) for implementation and evidence entry points.

The command review explicitly distinguishes drafts from recorded history and outbound records from sending. Active participant search returns at most 25 shared identities; no Tenant role is required. Each selected participant can use an active contact belonging to that identity, or omit the contact snapshot. Body/contact/correction privacy cues remain contextual. Typed source links are explicitly selected and server-validated; saved links display their preserved Property time zone and current owning-source context, including Intake replacement state.

The timeline supports status, direction, channel, participant, Property/Space/Lease, typed-link, stored-local-date range and follow-up Task-status filters. Cursor selection remains server-owned and bounded; no per-row detail reads were added. Detail displays occurrence in the retained IANA zone, participant/contact snapshots, follow-up deadlines and correction lineage. Recorded entries are never silently edited, and a correction does not replace the original entry's Tasks. Lost command responses reconcile their original operation without recording another interaction or follow-up.

## Implementation map

- [Domain values and invariants](../../application/apps/server/app/modules/communications/domain).
- [Use cases and application ports](../../application/apps/server/app/modules/communications/application).
- [HTTP contracts](../../application/apps/server/app/modules/communications/api).
- [Persistence and source adapters](../../application/apps/server/app/modules/communications/infrastructure).

Persistence identities below are read from the current models. Column definitions, checks and indexes live in the linked models and the [current baseline](../../application/database/sqlite-migrations/versions/0001_initial_schema.py); update them together.

| Tables | Model definitions |
| --- | --- |
| `communications`, `communication_participants`, `communication_links`, `communication_operations` | [sqlalchemy_models.py](../../application/apps/server/app/modules/communications/infrastructure/sqlalchemy_models.py) |

## Validation

COM-001 acceptance completed on October 13, 2026. The [completed acceptance record](../archive/designs/COM-001_DESIGN_COMPLETED_2026-10-13.md) records focused backend/browser results and limitations. Current browser review is in [communication-context.tsx](../../application/apps/web/src/workflows/communication-context.tsx), with lifecycle, contact/filter and recovery cases in [work.spec.ts](../../application/apps/web/tests/work.spec.ts).

- [test_communications.py](../../application/apps/server/app/modules/communications/tests/test_communications.py).

Use the [shared validation matrix](../platform/persistence.md#validation-matrix) when changing this boundary. Core browser acceptance is recorded in [browser validation](../ui/validation.md); later capability acceptance remains in [active work](../active/README.md).
