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

Both records contribute explicit next-action/follow-up facts to DASH-001. They never become a separate permanent HOA destination in MVP.

## Deferred scope

Standing governing-rule/document management, association profile administration, architectural approvals, assessments, board administration, and ongoing association operations are HOA-002.

## Verification and definition of done

Verify notice status/dispute independence, explicit/unconfirmed close paths, no automatic closure from repairs, one shared case across multiple managed units, no duplicated Home entry, association/provider separation, repeated follow-ups, retained evidence, and explicit physical verification. Complete only when all writes are audited and source lifecycles remain independent.
