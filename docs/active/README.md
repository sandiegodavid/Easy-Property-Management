# Active designs and remaining work

This index lists active designs and remaining work. The [backlog](../FEATURE_BACKLOG.md) is authoritative for status and dependencies.

The [agent triage design](agent-triage-design.md) is the accepted direction for remaining assistant-related backlog. Its feature designs below own implementation details; the document does not describe shipped behavior.

## Immediate hosted and portal delivery

- [H01 detailed design](../hosting/design/HOSTED_MVP_H01_DESIGN.md) and [database schema master](../DATABASE_SCHEMA.md): baseline, Pilot 0 schema, typed contracts and implementation proof handoff.
- [HOSTED-001 ordered slices](../hosting/design/mvp/delivery-plan.md#implementation-slices): start H01; release the capacity-qualified Free-operator Pilot 0 at H06 before paid automation.
- [PORTAL-001/002 and FIN-009 plan](PORTALS_IMPLEMENTATION_PLAN.md): tenant/owner workflows following hosting, shared late-fee source and cross-portal acceptance.
- [PAY-001](PAY-001_DESIGN.md): qualified payment engine reused by the tenant portal; operator subscriptions are owned by HOSTED-001.

## Operator interface delivery

Each functional backlog includes its own UI and browser acceptance. DATA-002/003 own import; INGEST-002 owns issue review; ASST-001 owns shared assistant setup with MCP-001/ASST-FILE-001 transport diagnostics and ASST-INTAKE-001 source controls; AI-DRAFT-001 owns drafting; LEGAL-001 and HOA-001 own their post-MVP workflows. The former UI-002/003/004 plans are archived as superseded allocation history, not separate delivery gates.

## Proposed domain and integration changes

These retain their domain contracts. HOSTED-001 and the portals above have immediate priority; other statuses/dependencies remain in the backlog. Local-only assumptions in older designs describe their original composition, not permission to expose their routes or file/credential paths in hosting. A feature needs explicit hosted actor, secret/storage, source-fence and recovery qualification before availability there; imports remain all-tier when delivered. Older baseline observations are design-time context.

- [PAY-001](PAY-001_DESIGN.md): accepted hosted premium tenant rent-payment design; tenant/operator UI, identity and entitlement, processor qualification, Finance extensions, lifecycle/recovery and nine ordered slices. Design only.
- [DATA-002](DATA-002_DESIGN.md).
- [DATA-003](DATA-003_DESIGN.md).
- [HOA-001](HOA-001_DESIGN.md).
- [HOA-002](HOA-002_DESIGN.md).
- [INGEST-002](INGEST-002_DESIGN.md).
- [LEGAL-001](LEGAL-001_DESIGN.md).
- [AI-DRAFT-001](AI-DRAFT-001_DESIGN.md): contextual draft from an EPM-invoked model, without assistant pairing.
- [ASST-001](ASST-001_DESIGN.md): shared connected-assistant technical design and included UI, seven ordered slices and fourteen proposed decisions; real-client qualification remains transport-owned.
- [MCP-001](MCP-001_DESIGN.md): local MCP transport.
- [ASST-FILE-001](ASST-FILE-001_DESIGN.md): proposed file transport and operator workflow, isolation/identity qualification, consistent exchange backup/restore, seven sequential slices and twelve open decisions.
- [ASST-INTAKE-001](ASST-INTAKE-001_DESIGN.md): separately qualified scheduled source discovery and proposal admission.
- [OBS-001](OBS-001_DESIGN.md): local diagnostics and opt-in, privacy-bounded product usage aggregation.

Universal Reader has a [UR-001 baseline technical design](UR-001_DESIGN.md), with seven implementation slices and twelve proposed decisions, supported by [research](../research/universal-reader/UNIVERSAL_READER_RESEARCH.md); its parallel work does not replace DATA scopes/dependencies. See [backlog](../FEATURE_BACKLOG.md) for all undesigned/planned features and hard dependencies.

## Completing active work

Dashboard snapshots and independent cron remain conditional post-MVP work. The measured live-read gate skipped snapshot Slices 19–20; the [completed Dashboard design](../archive/designs/DASH-001_DESIGN_COMPLETED_2026-10-14.md#post-mvp-optional-independent-dashboard-snapshot-cron-job) retains the separate performance gate and worker/maintenance requirements for any future proposal.

Verify its retained criteria against implementation and focused tests, update the current guide and backlog, then archive the fulfilled design. Final UI acceptance and pending review findings remain explicit. Historical test counts do not establish a new test run.

## Historical hosted references

Earlier [synthetic demo qualification](../hosting/qualification/HOSTED_DEMO_PUBLIC_ACCESS_PLAN.md) and [Admin proposal](../hosting/design/HOSTED_DEMO_ADMIN_DESIGN.md) retain their named topology and evidence. They are superseded as implementation direction; use HOSTED-001, not their A/B layouts, activation or manual entitlement assumptions.
