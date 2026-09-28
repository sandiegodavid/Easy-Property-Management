# Project Agent Guidance

## Testing

- Run focused tests by default.
- Run the full test suite only when explicitly requested or when a changed integration boundary requires full-suite validation.

## Follow-up implementation reviews

- In reviews, group findings by module or boundary.
- For a follow-up implementation re-review, review only the previously reported findings.
- For each finding, mark it as `resolved`, `still open`, or `regressed`, and include file and line references.
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
