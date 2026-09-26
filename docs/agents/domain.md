# Domain Docs

How engineering skills should consume this repository's domain documentation when exploring the codebase.

## Before exploring, read these

- `CONTEXT.md` at the repository root.
- Relevant architecture decision records under `docs/adr/`.

If these files do not exist, proceed silently. Do not flag their absence or suggest creating them upfront. Domain-modeling workflows create them when terminology or decisions are resolved.

## File structure

This repository uses a single-context layout:

```text
/
├── CONTEXT.md
├── docs/adr/
│   ├── 0001-example-decision.md
│   └── 0002-another-decision.md
└── application/
```

`CONTEXT.md` contains the shared domain model and glossary. `docs/adr/` contains decisions that apply to the application as a whole.

## Use the glossary's vocabulary

When output names a domain concept in an issue title, refactor proposal, hypothesis, or test, use the term defined in `CONTEXT.md`. Do not drift to synonyms the glossary explicitly avoids.

If a required concept is absent, reconsider whether the proposed language fits the project. When the omission represents a real domain gap, record it for domain modeling.

## Flag ADR conflicts

If proposed work contradicts an existing ADR, surface the conflict explicitly rather than silently overriding the decision. Name the ADR and explain why reopening it may be justified.
