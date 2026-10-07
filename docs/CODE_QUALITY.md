# Implementation quality checks

The executable configurations under `application/` define the project checks. Run them before completing implementation changes and report the results. Preserve the configured rules; adding suppressions, ignores, or relaxed thresholds requires an explicit user request.

## Python

Use Ruff with `application/pyproject.toml`. From `application/`, run `ruff check` and `ruff format --check` on every changed Python file, using the installed project environment. Fix findings and rerun both commands. Behavioral tests follow the focused-testing guidance in [AGENTS.md](../AGENTS.md).

## React, TypeScript, and JavaScript

The frontend toolchain is established before UI-001 as development tooling only. React screens and shared UI implementation remain deferred until UI-001. Use npm, one workspace manifest, and one committed lockfile under `application/`; install dependencies with `npm ci` on a current Node.js LTS release.

From `application/`, run:

```sh
npm ci
npm run lint
npm run format:check
npm run typecheck
```

`npm run check` runs all three validation commands. `npm run lint:fix` applies available ESLint fixes; `npm run format` applies Prettier formatting. Review automatic changes, then rerun validation.

### Rules and responsibilities

- **ESLint:** flat configuration in `application/eslint.config.mjs`, with `@eslint/js` recommended rules and `typescript-eslint`'s `recommendedTypeChecked` preset. Type-aware parsing uses `projectService: true`. This covers handwritten JavaScript and TypeScript, including tests and tooling. Warnings fail validation through `--max-warnings 0`. See [typed linting](https://typescript-eslint.io/getting-started/typed-linting/).
- **React:** `eslint-plugin-react-hooks`' recommended preset covers components and hooks in `apps/web/src` and `packages/ui/src`; `eslint-plugin-jsx-a11y`'s recommended preset checks JSX accessibility. These checks supplement behavioral and browser accessibility verification. See [React rules](https://react.dev/reference/eslint-plugin-react-hooks) and [JSX accessibility rules](https://github.com/jsx-eslint/eslint-plugin-jsx-a11y).
- **Formatting:** Prettier owns formatting, with `eslint-config-prettier` disabling conflicting ESLint formatting rules. The shared configuration uses two-space indentation, semicolons, double quotes, LF endings, and a 100-column target. Python/backend files and local runtime configuration are excluded. See [Prettier integration](https://prettier.io/docs/integrating-with-linters).
- **Type checking:** `tsconfig.base.json` sets strict checking and no emission. `tsconfig.json` includes all frontend workspace TypeScript and TypeScript tooling. `npm run typecheck` checks the entire included project, including generated API contracts, and fails on compiler errors. ESLint does not replace the compiler.

Generated contract files under `packages/contracts/src/generated` are excluded from ESLint and Prettier because generation owns their content. They remain compiler inputs; UI-001 must also verify reproducible generation with no uncommitted generated diff. Dependencies, coverage, and build output are excluded from source checks.

The initial lockfile uses ESLint 9 because `eslint-plugin-jsx-a11y` 6.10.2 declares compatibility only through ESLint 9. ESLint 9 is deprecated; upgrade ESLint and its accessibility integration together when a supported combination is available. Do not force incompatible peer dependencies. React hooks and TypeScript lint plugins already declare ESLint 10 compatibility.

Before the first TypeScript source exists, `npm run typecheck` explicitly reports a no-source skip. This establishes tooling readiness only and cannot count as frontend feature validation. Once sources exist, type errors fail the command. UI-001 adds React/Vite and their type dependencies, verifies the three checks against real frontend code, and retains project-wide type coverage if package-specific TypeScript configurations are introduced.

## Completion gate

Run the applicable checks after the final edit. A change is ready when lint, formatting, type checking (where applicable), and the required focused behavioral checks pass. A missing dependency or unavailable tool is an incomplete check, not a passing result. Keep [AGENTS.md](../AGENTS.md)'s implementation instructions aligned with these commands.
