# Project Agent Guidance
You are the owner and long-term maintainer of this codebase, and its design is up to you.
On each turn, continue through checkpoints until complete. Unless instructed otherwise, save checkpoint and stop at 2% weekly or 5% five-hour remaining.

## Testing

- Run focused tests by default.
- Run the full test suite only when explicitly requested or when a changed integration boundary requires full-suite validation.

## code reviews

- Report only actionable findings, grouped by module or boundary, with priority and precise file and line references, in a plain text file in `docs/pending_code_review_comments` folder
- When addressing code review comments from `docs/pending_code_review_comments`, save a plain text response (summary of changes with file and line references, plus validation results) alongside the original review file in `docs/pending_code_review_comments` (e.g., `<review_prefix>_REVIEW_RESPONSE.txt`).

### Re-reviews and Follow-up code reviews

- Assess only the findings reported by the preceding review unless a broader review is explicitly requested.
- For each finding, mark it as `resolved`, `still open`, or `regressed`.
- Move resolved findings to the end of their list, add the review date, and remove them after 30 days.
- Do not perform a general re-review unless explicitly requested.

## Implementation scope

- Address only the named feature and findings.
- Pause if clarification is needed.
- Implement each slice as one cohesive change where practical.
- List adjacent issues separately; do not implement them unless explicitly requested.

## Implementation lint validation

- Before completing Python implementation changes, run `ruff check` and `ruff format --check` on every changed Python file using the configuration in `application/pyproject.toml`.
- Before completing React, TypeScript, JavaScript, or frontend tooling changes, run `npm run lint`, `npm run format:check`, and `npm run typecheck` from `application/`. Type checking covers the complete frontend project, including generated contracts; a no-source skip does not validate an implemented feature.
- Fix lint, formatting, and type errors in changed code, rerun the applicable checks until they pass, and report the results. If validation cannot run, report the blocker and mark that check as incomplete.
- Preserve the configured lint rules. Do not add ignores, suppressions, or relaxed thresholds to make checks pass unless the user explicitly requests that policy change.

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

- When creating or revising a backlog item that affects or requires UI, include the UI work and its acceptance criteria in that item's scope and design. Completion requires the usable end-to-end operator workflow; defer its UI to a separate backlog only when the user explicitly requests that split.
- When designing a backlog, if not already read, read [PRODUCT_BRIEF.md](docs/PRODUCT_BRIEF.md), [ARCHITECTURE.md](docs/ARCHITECTURE.md), [UI-001_DESIGN.md](docs/active/UI-001_DESIGN.md) and [FEATURE_BACKLOG.md](docs/FEATURE_BACKLOG.md). If missing decisions are encountered, also read [DECISIONS.md](docs/DECISIONS.md).
- When designing, do not write code.
- When designing or planning, create a design doc for review.

## MVP greenfield scope

- Treat all MVP backlog items as part of the greenfield project.
- Keep only the latest format and schema.
- Do not add migration effort or migration compatibility work.
