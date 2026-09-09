# AI Collaboration Playbook

This guide captures an efficient way to use an AI coding agent for Easy Property Management. It is based on the project's local-first, greenfield, latest-format-only architecture and its preference for explicit product boundaries, auditability, and verified outcomes.

## Core principle

Spend more agent effort before implementation to remove ambiguity, then perform one bounded implementation and one comprehensive review/remediation pass. This reduces architectural churn and repeated review cycles.

## 1. Freeze the feature contract before coding

Before authorizing implementation, request a design-only review of the relevant design, architecture, decision log, backlog dependencies, and affected modules. It should state:

1. Data model and module ownership boundaries.
2. API contract and response shapes.
3. Lifecycle states and transitions.
4. Audit and privacy requirements.
5. Backup, restore, and portability implications.
6. Explicit non-goals.
7. Acceptance and regression tests.

Resolve contradictions before asking for code. This is especially important for cross-cutting features such as files, parties, leases, inspections, finance, and AI.

Suggested prompt:

```text
Read the relevant design, architecture, backlog dependencies, and current implementation.
Do not code. Return the data model, ownership boundaries, API contract, lifecycle rules,
audit/privacy requirements, backup/restore implications, explicit non-goals, and acceptance tests.
Identify contradictions or missing decisions.
```

## 2. Request comprehensive reviews by root cause

Ask for a full feature review against the approved contract before remediation, rather than discovering one related issue at a time.

```text
Review this feature against its design, architecture, data ownership, concurrency, lifecycle rules,
privacy/audit rules, backup/restore, API contracts, and greenfield latest-only policy.
Do not change code. Group findings by root cause and include proposed regression tests.
```

Then remediate the whole list in one cohesive pass:

```text
Implement every listed finding in one cohesive change.
Add regression coverage for each finding.
Do not introduce compatibility paths or broaden scope.
Run focused tests, the full suite, compilation, and diff validation.
```

## 3. Classify feedback before acting

| Kind | Meaning | Response |
| --- | --- | --- |
| Decision needed | A product or architecture choice is unresolved. | Pause implementation and decide it explicitly. |
| Defect | Code violates an approved contract. | Fix directly with a regression test. |
| Cleanup | Readability or future-maintenance opportunity. | Defer unless it blocks correctness, the next slice, or safe review. |

For example, whether a generic File API belongs in the product is a design decision; a SQLite `CHECK` that permits an invalid `NULL` is a defect.

## 4. Put a Definition of Done in every feature design

Use this checklist unless a feature explicitly does not need an item:

- Current-schema tables, constraints, indexes, and exact schema validation.
- Typed application commands and typed API contracts.
- Atomic business writes and corresponding audit events.
- Lifecycle, source-ownership, archive, and concurrency guards.
- File-link validation and contextual privacy policy where files are involved.
- Backup/export/restore regression coverage for new persisted data.
- Focused domain, API, rollback, and failure-path tests.
- Explicit UI scope: delivered or pending.

## 5. Implement vertical slices

Keep a slice small but complete. For example, an inspection slice can create a draft pre-move-in report, add observations, finalize it with audit events, validate evidence links, survive backup/restore, and expose typed APIs. Add post-move-out comparison in a later slice.

Avoid broad horizontal requests such as “add all inspection tables” without a complete operator use case.

## 6. Match reasoning effort to work

| Work | Recommended effort |
| --- | --- |
| Data-model design, lifecycle rules, cross-module architecture, security/privacy, migrations, review synthesis | High |
| Approved vertical-slice implementation and grouped review remediation | Medium |
| Mechanical documentation, formatting, backlog status, straightforward renames, routine checks | Low or minimal |

Use high reasoning for decisions that would otherwise cause rework. Do not spend it on isolated Markdown or status-only changes.

### Model routing for this project

This guidance is based on the project's observed work pattern, not account-level token or time telemetry. The expensive work has been cross-module design and re-review cycles around workspace safety, schema contracts, files, portfolio, tenants, and leases. Route work by uncertainty and blast radius rather than by the number of changed lines.

| Work pattern | Best model role | Prompt shape | Efficiency reason |
| --- | --- | --- | --- |
| New feature, data model, state machine, privacy boundary, storage/backup behavior, or cross-module ownership | Architecture model with high reasoning | Design only; enumerate decisions, invariants, non-goals, and acceptance tests. | Prevents expensive implementation reversals. |
| Approved bounded backend/API slice | Implementation model with medium reasoning | Name the approved design sections, affected modules, stopping boundary, and required verification. | Keeps implementation focused without re-litigating architecture. |
| Comprehensive review after a slice | Review model with high reasoning | Review the feature contract, diff, tests, failure paths, and prior findings together; do not edit. | Finds related root causes in one pass rather than drip-feeding defects. |
| Mechanical documentation, backlog wording, formatting, test execution, or a narrow one-file fix | Fast model with low/minimal reasoning | State the exact files, desired text or behavior, and validation command. | Preserves high-reasoning capacity for decisions. |

Do not ask one turn to design, implement, review, and refactor a broad feature. Use four deliberate handoffs instead: **design → approve → implement → comprehensive review/remediate**. Each handoff has a smaller, more reliable context and a clear completion condition.

### Build small context packets

Give the model the minimum authoritative inputs needed for the task:

- Feature design and its backlog row.
- The relevant architecture or decision-log section.
- Directly affected modules and schema files.
- Prior unresolved review findings, if any.
- Exact required test commands.

Avoid pasting the full project history or every resolved review comment. Instead, name the authoritative files and state which earlier findings remain open. For schema changes, always include the model, current Alembic baseline, exact-schema validator, and related tests together; this project has repeatedly shown that changing only one representation causes drift.

### Use one review packet, not a stream of isolated findings

When requesting re-review, give the reviewer a compact evidence packet:

```text
Review FEATURE-ID against its approved design and the current diff.
Previously resolved findings are: [short list].
Focus on: lifecycle states, atomicity, schema/model/baseline/validator alignment,
privacy/audit, backup/restore, and API behavior.
Run: [focused test command] and [full test command].
Do not edit. Return only unresolved findings, grouped by root cause.
```

After review, fix the complete list in one change. If a later review discovers a new architectural concern, classify it as a decision needed rather than folding an unapproved redesign into a defect-fix turn.

### Prefer explicit verification budgets

Use proportionate checks instead of automatically repeating every expensive action after every documentation or narrow code edit:

- Documentation-only: `git diff --check` and targeted rendering/format verification where relevant.
- One-module behavior change: focused module tests, compilation, and diff check.
- Persistence, schema, audit, file, workspace, or API composition change: focused tests plus the full suite, compilation, and diff check.

Ask the agent to report checks that actually ran and their outcomes. Do not accept an implied test result.

## 7. State the stopping boundary

Use concise scope markers:

```text
Design only. Do not modify files.
```

```text
Implement only the approved design; do not refactor adjacent modules.
```

```text
Fix all listed findings, but do not commit.
```

```text
Commit the current verified work only; do not squash unrelated history.
```

## 8. Keep one current architecture truth

When a design decision changes, update the feature design, `ARCHITECTURE.md`, `DECISIONS.md`, and feature backlog together where each is affected. The greenfield latest-format-only policy remains a standing implementation constraint: update the current baseline directly and do not add adoption or compatibility paths unless explicitly requested.

## 9. Standard feature implementation prompt

```text
Read FEATURE-ID design, ARCHITECTURE.md, DECISIONS.md, the backlog row, and all directly affected modules.

Implement the approved FEATURE-ID backend/API slice only.
This is greenfield and latest-format-only: update the current baseline directly; add no legacy,
adoption, or compatibility behavior.

Requirements:
- preserve module ownership and dependency inversion;
- use typed application commands and typed API contracts;
- make each business mutation atomic with its audit event;
- enforce source ownership and lifecycle rules;
- validate schema exactly;
- add focused regressions, including rollback, concurrency, and privacy cases where applicable;
- verify backup/restore when new persisted data is introduced.

Do not build UI unless explicitly included.
Do not commit.
Run focused tests, full tests, compilation, and diff validation.
```
