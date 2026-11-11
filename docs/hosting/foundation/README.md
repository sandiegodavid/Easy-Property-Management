# Hosted infrastructure foundation

The container, storage and gateway foundation is delivered within its tested
infrastructure scope. Start here for current implementation and operating guidance;
the [foundation design](../design/HOSTED_MVP_H02_DESIGN.md) owns accepted boundaries
and D1–D13 rationale. Managed identity, real operator admission, logical metering and
recovery remain with their [owning features](qualification-and-handoff.md#remaining-delivery).
No qualified hosted release or customer-access grant follows from infrastructure proof.

| Question | Guide |
| --- | --- |
| What ships, and how does it start? | [Packaging and launch](packaging-and-launch.md) |
| Who owns schemas, allocations and original commands? | [Inventory and host commands](inventory-and-host-commands.md) |
| How are data, writers and resources isolated? | [Runtime and capacity](runtime-and-capacity.md) |
| How are ingress, egress and secrets enforced? | [Networking and access](networking-and-access.md) |
| How do I build, use the Linux lab or operate the retained host? | [Development and host operations](development-and-host-operations.md) |
| What was tested, what failed, and what remains? | [Qualification and handoff](qualification-and-handoff.md) |

These guides describe behavior and limits by topic. Commands remain in the linked
executable runbooks; schema columns remain in the [database catalog](../../database/README.md).
The [acceptance register](../qualification/HOSTED_MVP_ACCEPTANCE.md) owns release gates.
Dated observations, original source/artifact pins and machine-readable results are
preserved in the [evidence index](../qualification/reports/README.md#infrastructure-evidence-by-topic).
Their numbered filenames identify provenance, not a required reading order.

The [archived planning snapshot](../archive/HOSTED_MVP_H02_PLANNING_2026-11-13.md)
retains the earlier ordered plan. Use current guides for behavior and operations;
use historical reports only with their recorded source, platform and scope.
