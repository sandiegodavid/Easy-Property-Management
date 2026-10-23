# Active designs and remaining work

This index lists active designs and remaining work. The [backlog](../FEATURE_BACKLOG.md) is authoritative for status and dependencies.

The [agent triage design](agent-triage-design.md) is the accepted direction for remaining assistant-related backlog. Its feature designs below own implementation details; the document does not describe shipped behavior.

## Operator interface delivery

Each functional backlog includes its own UI and browser acceptance. DATA-002/003 own import; INGEST-002 owns issue review; ASST-001 owns shared assistant setup with MCP-001/ASST-FILE-001 transport diagnostics and ASST-INTAKE-001 source controls; AI-DRAFT-001 owns drafting; LEGAL-001 and HOA-001 own their post-MVP workflows. The former UI-002/003/004 plans are archived as superseded allocation history, not separate delivery gates.

## Proposed domain and integration changes

These retain their complete design contracts. Capability availability and backlog status govern when they can be implemented; older baseline observations are design-time context.

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
- [Hosted demo public access](../hosting/qualification/HOSTED_DEMO_PUBLIC_ACCESS_PLAN.md): accepted design decisions and implementation slices for the bounded Google Cloud A/B demo, including operator UI, authorization/sessions, cost/latency gates, recovery and Cloudflare deployment. Protected deployment is in qualification, with remaining acceptance gates and invitations pending; this does not mark SAAS-001/SEC-001/SEC-002 delivered.

Universal Reader has a [UR-001 baseline technical design](UR-001_DESIGN.md), with seven implementation slices and twelve proposed decisions, supported by [research](../research/universal-reader/UNIVERSAL_READER_RESEARCH.md); its parallel work does not replace DATA scopes/dependencies. See [backlog](../FEATURE_BACKLOG.md) for all undesigned/planned features and hard dependencies.

## Completing active work

Dashboard snapshots and independent cron remain conditional post-MVP work. The measured live-read gate skipped snapshot Slices 19–20; the [completed Dashboard design](../archive/designs/DASH-001_DESIGN_COMPLETED_2026-10-14.md#post-mvp-optional-independent-dashboard-snapshot-cron-job) retains the separate performance gate and worker/maintenance requirements for any future proposal.

Verify its retained criteria against implementation and focused tests, update the current guide and backlog, then archive the fulfilled design. Final UI acceptance and pending review findings remain explicit. Historical test counts do not establish a new test run.
