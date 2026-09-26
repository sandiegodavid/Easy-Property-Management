# Issue tracker: Local Markdown

During MVP, issues and specifications live as Markdown files under `.scratch/`. The planned post-MVP tracker is GitHub Issues.

## Conventions

- One feature per directory: `.scratch/<feature-slug>/`
- The specification is `.scratch/<feature-slug>/spec.md`.
- Implementation issues are separate files under `.scratch/<feature-slug>/issues/`.
- Issue filenames use `<NN>-<slug>.md`, numbered from `01`; do not combine all tickets into one file.
- Record workflow state in a `Status:` line near the top.
- Append discussion under a `## Comments` heading.

## When a skill says "publish to the issue tracker"

Create the corresponding file under `.scratch/<feature-slug>/`, creating the directory if needed.

## When a skill says "fetch the relevant ticket"

Read the referenced local Markdown file. The user will normally provide its path or issue number.

## Wayfinding operations

The map is a file with one child file per ticket.

- **Map:** `.scratch/<effort>/map.md`, containing Notes, Decisions-so-far, and Fog.
- **Child ticket:** `.scratch/<effort>/issues/NN-<slug>.md`, numbered from `01`.
- **Type:** Record the ticket type as `research`, `prototype`, `grilling`, or `task` in a `Type:` line.
- **Status:** Record `claimed` or `resolved` in a `Status:` line.
- **Blocking:** Record dependencies in a `Blocked by: NN, NN` line. A ticket is unblocked when every referenced ticket is resolved.
- **Frontier:** Select the first open, unblocked, and unclaimed ticket by number.
- **Claim:** Set `Status: claimed` and save before beginning work.
- **Resolve:** Append the answer under an `## Answer` heading, set `Status: resolved`, and append a context pointer to the map's Decisions-so-far.

## Post-MVP migration

When the project adopts GitHub Issues after MVP, rerun the setup skill to replace this workflow rather than maintaining two active trackers.
