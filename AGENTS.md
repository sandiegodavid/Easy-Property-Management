# Project Agent Guidance

## Testing

- Run focused tests by default.
- Run the full test suite only when explicitly requested or when a changed integration boundary requires full-suite validation.

## Follow-up implementation reviews

- In reviews, group findings by module or boundary.
- For a follow-up implementation re-review, review only the previously reported findings.
- For each finding, mark it as `resolved`, `still open`, or `regressed`, and include file and line references.
- Move resolved findings to the end of their list, add the review date, and remove them after 30 days.
- Do not perform a general re-review unless explicitly requested.

## Implementation scope

- Address only the named feature and findings.
- List adjacent issues separately; do not implement them unless explicitly requested.

## Design validation

- When applicable, document a test matrix covering these validation areas:
  - happy paths;
  - invalid combinations;
  - idempotency and retry behavior;
  - transaction rollback;
  - persistence/schema validation;
  - backup/restore;
  - query-budget or N+1 constraints.

## Backlog and design

- When designing a backlog, if not already read, read [PRODUCT_BRIEF.md](docs/PRODUCT_BRIEF.md), [ARCHITECTURE.md](docs/ARCHITECTURE.md), and [FEATURE_BACKLOG.md](docs/FEATURE_BACKLOG.md). If missing decisions are encountered, also read [DECISIONS.md](docs/DECISIONS.md).
- When designing a UI backlog, if not already read, also read [UI-001_DESIGN.md](docs/UI-001_DESIGN.md).
- When designing, do not write code.

## MVP greenfield scope

- Treat all MVP backlog items as part of the greenfield project.
- Keep only the latest format and schema.
- Do not add migration effort or migration compatibility work.
