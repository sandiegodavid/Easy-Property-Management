# Project Agent Guidance
You are the owner and long-term maintainer of this codebase, and its design is up to you.
On each turn, continue through checkpoints until complete. Save checkpoint and stop at 2% weekly remaining.

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

### Live UI & Interaction Reviews

- After completing a UI interaction review or live browser test pass (such as executing `docs/ui/interaction-test-plan.md`), always save:
  1. a complete findings and test-results report in `docs/ui/` (e.g., `docs/ui/live-interaction-test-results-<YYYY-MM-DD>.md` or `docs/ui/interaction-test-results.md`) containing the full pass/fail matrix, every confirmed defect with numbered Steps to Reproduce, Expected Result, Actual Result, URLs, HTTP statuses/endpoints, console errors, and cleanup state; and
  2. a structured, prioritized remediation plan in `docs/active/` (with batches, slices, acceptance criteria, a validation test matrix, and a link to the findings report) linked from `docs/active/README.md`.

## Implementation scope

- Address only the named feature and findings.
- Pause if clarification is needed.
- Implement each slice as one cohesive change where practical.
- Document progress and status in the owning plan/design doc after completing each implementation slice.
- Document a checkpoint after completing each implementation slice.
- When changes are made for a slice, update its status and link to its checkpoint in the owning design doc, and check any owning specifications, delivery plans, or dictionaries linked in that design doc's header to update any status, contracts, or implementation notes affected by the slice.
- When adding or modifying database schemas or migration files under `application/database/`, update the owning store dictionary and index docs in `docs/database/` (`overview.md`, `schema-resources.md`, and the owning store markdown file) in the same change so documented tables, columns, constraints, indexes, triggers, and implementation status match the executable DDL.
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
- When designing a backlog, if not already read, read [PRODUCT_BRIEF.md](docs/PRODUCT_BRIEF.md), [ARCHITECTURE.md](docs/ARCHITECTURE.md), [operator-experience.md](docs/ui/operator-experience.md), [frontend-architecture.md](docs/ui/frontend-architecture.md), and [FEATURE_BACKLOG.md](docs/FEATURE_BACKLOG.md). If missing decisions are encountered, also read [DECISIONS.md](docs/DECISIONS.md).
- When designing, do not write code.
- When designing or planning, create a design doc for review.
- When creating a new design doc, update its owning index and linking docs (such as `docs/hosting/README.md`, `docs/hosting/design/README.md`, `docs/hosting/design/HOSTED_MVP_DESIGN.md`, `docs/hosting/design/mvp/delivery-plan.md`, or `docs/active/README.md`) to link to it.

## MVP greenfield scope

- Treat all MVP backlog items as part of the greenfield project.
- Keep only the latest format and schema.
- Do not add migration effort or migration compatibility work.
