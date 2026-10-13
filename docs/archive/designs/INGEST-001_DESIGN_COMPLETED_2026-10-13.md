# INGEST-001 — completed acceptance, October 13, 2026

Current behavior is consolidated in the [Intake guide](../../modules/intake.md). The [original design](INGEST-001_DESIGN.md) retains rationale. This completes manual retained-source workflows and consumer read/attention contracts, not production assistant transport, transcription, model inference or issue conversion. These remain MCP-001, VOICE-AI-001 and INGEST-002 gates.

## Focused validation matrix

| Area | Executable evidence | Result |
| --- | --- | --- |
| Happy paths | Manual message/note/transcript retention, multipart ordered roles/digests, correction, dismissal/reopening, nonbranching supersession and exact historical evidence comparison | Passed |
| Invalid combinations | Oversized/extra/trusted-provenance HTTP fields, invalid revisions/keys, changed byte reselection, stale correction, foreign revision membership and legal attention/source transitions | Passed |
| Identity/retry | Trusted account/source replay binds evidence and reserves each key, historical replay survives corrections/supersession; concurrent correction and changed-reuse conflicts; lost admission response reconciles with one dispatch | Passed |
| Rollback/disclosure | Audit failure rolls back mutation/receipt; commit failure rolls back attachment bytes; exact evidence read commits local-operator audit before disclosure and denies on audit failure | Passed |
| Persistence/privacy | Canonical evidence/lineage/operation tampering rejection, immutable correction revisions, retained contextual reasons, sensitive receipts audited and metadata-only lists | Passed |
| Backup/restore | Expanded real encrypted round trip compares all five Intake tables, File records/locations/links and Intake/File audits before replay; original ordered associations/hashes, metadata and exact bytes retained | Passed |
| Bounded reads | One versus 25 source rows uses equal SELECT counts with upper bound three; existing consumer batch/bounded exact-history tests; 30-row browser traversal has no gaps, duplicates or detail fan-out | Passed |
| Independent modules | Retention creates no communication; explicit recorded link retains its original source after supersession and projects current replacement context without changing conversation content/revision | Passed |

## Validation results and limitations

- Intake/Communications focused backend suites: **72 passed**.
- Packaged Intake browser suite: **7 passed**, against real temporary workspaces; withheld-read browser errors are synthetic complements to backend audit-failure tests.
- Changed-file Ruff check/format, frontend lint/typecheck, changed-file Prettier, generated-contract reproducibility, package build and diff whitespace passed.
- Repository-wide formatting remains blocked by unchanged `application/demo/dataset.json` and `application/demo/README.md`. Bundle-size warnings are informational.
- No full suite, independent manual usability review or future SaaS export implementation ran. No adjacent AI/issue/assistant workflows or pending review findings are closed here.
