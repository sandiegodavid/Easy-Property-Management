# Active designs and remaining work

This index lists active designs and remaining work. The [backlog](../FEATURE_BACKLOG.md) is authoritative for status and dependencies.

The [agent triage design](agent-triage-design.md) is the accepted direction for remaining assistant-related backlog. Its feature designs below own implementation details; the document does not describe shipped behavior.

## Remaining interface work

- [UI-002 preliminary design](UI-002_DESIGN_preliminary.md): legal/HOA, spreadsheet intake and source-backed issue review.
- [UI-003 preliminary design](UI-003_DESIGN_preliminary.md): task-based connected-assistant setup and health, after one transport qualifies.

## Proposed domain and integration changes

These retain their complete design contracts. Capability availability and backlog status govern when they can be implemented; older baseline observations are design-time context.

- [DATA-002](DATA-002_DESIGN.md).
- [DATA-003](DATA-003_DESIGN.md).
- [HOA-001](HOA-001_DESIGN.md).
- [HOA-002](HOA-002_DESIGN.md).
- [INGEST-002](INGEST-002_DESIGN.md).
- [LEGAL-001](LEGAL-001_DESIGN.md).
- [AI-DRAFT-001](AI-DRAFT-001_DESIGN.md): contextual draft from an EPM-invoked model, without assistant pairing.
- [ASST-001](ASST-001_DESIGN.md): shared connected-assistant boundary.
- [MCP-001](MCP-001_DESIGN.md): local MCP transport.
- [ASST-FILE-001](ASST-FILE-001_DESIGN.md): optional managed file-adapter qualification.
- [ASST-INTAKE-001](ASST-INTAKE-001_DESIGN.md): separately qualified scheduled source discovery and proposal admission.
- [OBS-001](OBS-001_DESIGN.md): local diagnostics and opt-in, privacy-bounded product usage aggregation.

Universal Reader is a separate experiment documented in [research](../research/UNIVERSAL_READER_RESEARCH.md); its parallel work does not replace DATA scopes/dependencies. See [backlog](../FEATURE_BACKLOG.md) for all undesigned/planned features and hard dependencies.

## Completing active work

Dashboard snapshots and independent cron remain conditional post-MVP work. The measured live-read gate skipped snapshot Slices 19–20; the [completed Dashboard design](../archive/designs/DASH-001_DESIGN_COMPLETED_2026-10-14.md#post-mvp-optional-independent-dashboard-snapshot-cron-job) retains the separate performance gate and worker/maintenance requirements for any future proposal.

Verify its retained criteria against implementation and focused tests, update the current guide and backlog, then archive the fulfilled design. Final UI acceptance and pending review findings remain explicit. Historical test counts do not establish a new test run.
