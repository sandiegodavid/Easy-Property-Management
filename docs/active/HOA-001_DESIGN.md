# HOA-001 — HOA Notice and Shared-Repair Coordination Design

## Purpose

`HOA-001` provides two narrow, related capabilities: property-linked HOA violation notices and coordination facts for a Maintenance-owned shared common-element repair affecting managed condominium units. It does not introduce broad association management.

## Violation notices

Each notice has a stable ID; affected property; association/sender Party snapshot; received date; original notice file/reference; optional cited rule reference; status `received|reviewing|action_underway|response_submitted|closed`; independent disputed flag; next action/waiting context; communications, tasks, remediation links; claimed-charge facts; and closure outcome/evidence.

Transitions are flexible but audited. Closing requires an outcome and supporting record. An operator may close without association confirmation only with an explicit reason and an **unconfirmed** closure label. Completing linked remediation never closes the notice automatically. Claimed fines, estimates, and actual FIN-002 payments are separate facts.

## Shared HOA-covered repairs

A shared repair is exactly one MAINT-001 issue/case with a primary property for navigation and an HOA coordination record. The coordination record has affected managed property/unit IDs, an optional bounded free-text affected-area note for unmanaged scope, association identity, responsibility/coverage assertion, assertion basis and confidence, supporting evidence, current commitment, and physical-verification closure facts.

The HOA is an organization/contact, never a provider assignment. If it hires a contractor, that contractor remains a distinct provider/assignment. An operator's coverage assertion and an HOA estimate do not establish accepted coverage or a paid expense.

The coordination timeline references immutable COM-001 records and ordered operator notes. Repeated contact is represented by distinct TASK-002 tasks/follow-ups; completing one does not resolve the repair. Close the coordination only after explicit physical outcome verification with date and source. The maintenance issue retains its independent lifecycle and may remain open; unit-specific residual damage is a separate linked issue.

## Read and UI contract

Notices appear in the affected property context. Shared repairs appear once in DASH-001 and in every affected managed-property workspace, with one stable shared-case identity to prevent duplication. Summary fields are shared asset/scope, affected-unit count, HOA state, and next follow-up. Expanded/contextual detail shows coverage evidence, units, timeline, commitment, and actions to record contact, schedule follow-up, link contractor, or verify outcome.

Both records contribute explicit next-action/follow-up facts to DASH-001. They never become a separate permanent HOA destination.

## Deferred scope

Standing governing-rule/document management, association profile administration, architectural approvals, assessments, board administration, and ongoing association operations are HOA-002.

## Verification and definition of done

Verify notice status/dispute independence, explicit/unconfirmed close paths, no automatic closure from repairs, one shared case across multiple managed units, no duplicated Home entry, association/provider separation, repeated follow-ups, retained evidence, and explicit physical verification. Complete only when all writes are audited and source lifecycles remain independent.

## Included operator interface delivery

This UI is part of this functional backlog and its completion criteria. Reuse the delivered UI-001 shell, generated contracts, source-owned commands, Light/Dark themes, keyboard/focus behavior and recovery patterns. Validate real temporary-workspace reads/writes, stale revisions, lost responses, restart/restore and bounded queries; backend-only delivery is incomplete.

#### D38: Keep initial HOA work narrow

The initial HOA feature supports receipt and tracking of HOA violation notices and their resolution. It also supports the D47 case: coordination of an HOA-covered common-element repair affecting condo units. Retain association/sender identity, property, original notice and any cited rule/evidence, dates, next action, communications, linked remediation work, and closure evidence. For a shared repair, retain one Maintenance-owned case, affected managed units, responsibility/coverage evidence, every contact and follow-up, and physical verification. These narrow capabilities do not require a standing HOA rules or board-management module.

A violation notice remains a separate matter from its remediation work. Preserve the original notice, cited rule reference, response, disputed state, claimed amounts, linked remediation, and closure evidence. A shared repair remains a Maintenance record even when it is linked to an HOA notice or coordinated through the association.

Standing rules management, architectural approval requests, assessments, board administration, and other broader HOA capabilities are explicitly deferred to HOA-002. Preserve records and links so these can be added later without recreating violation or coordination history. Notice-related claimed or disputed amounts and HOA repair estimates remain contextual facts; they do not automatically create paid expenses or tenant charges.

#### D41: Close HOA notices through an explicit outcome

Use Received, Reviewing, Action underway, Response submitted, and Closed, with flexible transitions and a separate disputed flag. Completing a linked repair can make evidence submission the next action but never closes the notice automatically. Closing records an outcome and supporting record, such as association acceptance or withdrawal. Operator closure without HOA confirmation requires a reason and an explicit unconfirmed label. Claimed fines and actual payments remain separate.

#### D47: Track one shared HOA-covered repair across affected condo units

When a building system or common element affects multiple condominium units, create one shared maintenance case rather than duplicate independent issues. Select a primary property for navigation and link every affected managed property or unit. If the operator does not manage every affected unit, retain a bounded free-text affected-area note without creating fake portfolio records. The case appears once on Home and in every linked property workspace.

The case records the affected scope (for example, Shared building water regulator), the association responsible for coordinating or covering the work, the basis and confidence of that responsibility, and the current next action. The HOA is a saved organization/contact, not a provider assignment. If the HOA hires a contractor, preserve the contractor as a separate provider and keep the HOA relationship visible. An operator-entered coverage assertion is not proof that the HOA has accepted responsibility, and an HOA estimate or claimed charge is not a paid property expense.

Show an ordered coordination timeline containing every call, email, submitted document, response, promise, appointment, and operator note. Each communication remains a distinct source-linked record. Repeated follow-ups are separate Tasks with waiting-for context and dates; completing one follow-up may schedule the next but never resolves the maintenance case. Home shows the current actionable follow-up or Waiting state without repeating the case once per affected unit.

The case remains open until the physical outcome is explicitly verified. HOA acknowledgement, approval, contractor assignment, or a promised replacement date are milestones rather than resolution. Closing requires an outcome such as regulator replaced and service verified, plus the verification date/source. Unresolved damage inside an individual unit can remain a separate linked issue after the shared asset is repaired.

In the summary bar, show the shared asset, affected scope, current HOA state, and next follow-up, for example: Shared water regulator · 3 units affected · Waiting for Cascadia HOA · Follow up Sep 25. Expanding it shows responsibility/coverage evidence, affected managed units, the communication timeline, current commitment, and actions to record contact, schedule another follow-up, link a contractor, or verify completion.

##### HOA follow-up presentation example

Inside the expanded shared-repair case, show:

> **Waiting for Cascadia HOA**
>
> Three contacts recorded · Replacement date still unconfirmed
>
> Next follow-up: September 25
>
> **Prepare follow-up** · **Record response**

Preparing the follow-up uses the selected correspondence and latest commitment to draft a message. Review shows the proposed content, supporting records, and intended changes together. Draft approval and message sending are distinct actions. Keep the next follow-up and unresolved repair visible until separately updated or physically verified; an assistant's work status never establishes repair completion.

The actions sit inside expanded content per [UI-001 D35](../ui/operator-experience.md). AI-assisted preparation follows [ASST-001's connection boundary](ASST-001_DESIGN.md) when a connected assistant is used and the owning AI-DRAFT-001 action in either execution path; drafting availability is not guaranteed by HOA-001 alone.

Deliver contextual `/hoa/notices/:noticeId` from property/owner context and shared-repair detail within Maintenance and every affected managed-property workspace. Register one explicitly grouped Home entry per shared repair, preserving all underlying deadlines and follow-ups; never group by similar text. Include evidence, disputes, response, waiting and confirmed/unconfirmed closure UI, with confirmation and original-result recovery. Extend bounded search and information review. No permanent HOA destination. Test repeated unanswered/answered contacts, multi-unit presentation without duplicate Home counts, repair completion without automatic notice closure and physical-verification closure. Reuse delivered DASH-001 qualified reassurance and independent unavailable states; this feature does not depend on LEGAL-001.
