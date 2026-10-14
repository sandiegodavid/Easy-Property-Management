# Active designs and remaining work

This index lists active designs and remaining work. The [backlog](../FEATURE_BACKLOG.md) is authoritative for status and dependencies.

## Remaining interface work

- [UI-002 preliminary design](UI-002_DESIGN_preliminary.md): legal/HOA, spreadsheet intake, issue proposals and connected assistants.

## Proposed domain and integration changes

These retain their complete design contracts. Capability availability and backlog status govern when they can be implemented; older baseline observations are design-time context.

- [DATA-002](DATA-002_DESIGN.md).
- [DATA-003](DATA-003_DESIGN.md).
- [HOA-001](HOA-001_DESIGN.md).
- [HOA-002](HOA-002_DESIGN.md).
- [INGEST-002](INGEST-002_DESIGN.md).
- [LEGAL-001](LEGAL-001_DESIGN.md).
- [MCP-001](MCP-001_DESIGN.md).

Universal Reader is a separate experiment documented in [research](../research/UNIVERSAL_READER_RESEARCH.md); its parallel work does not replace DATA scopes/dependencies. See [backlog](../FEATURE_BACKLOG.md) for all undesigned/planned features and hard dependencies.

## Completing active work

Dashboard snapshots and independent cron remain conditional post-MVP work. The measured live-read gate skipped snapshot Slices 19–20; the [completed Dashboard design](../archive/designs/DASH-001_DESIGN_COMPLETED_2026-10-14.md#post-mvp-optional-independent-dashboard-snapshot-cron-job) retains the separate performance gate and worker/maintenance requirements for any future proposal.

Verify its retained criteria against implementation and focused tests, update the current guide and backlog, then archive the fulfilled design. Final UI acceptance and pending review findings remain explicit. Historical test counts do not establish a new test run.
