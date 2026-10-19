# Demo-workspace browser tests

Playwright end-to-end suites that run against a **manually started demo server**
with a seeded synthetic workspace (see `application/demo/README.md`). Unlike the
suites in `apps/web/tests` — which spin up disposable smoke servers per run via
`npm run test:web` — these suites reuse one seeded workspace so assertions can
target its known records.

## Prerequisites

From `application/`, prepare the Python environment once (see the repository
README), then seed and serve the demo workspace:

```bash
export EPM_PYTHON="$PWD/.venv/bin/python"
.venv/bin/python demo/seed.py --workspace "$HOME/Desktop/Property-Management-Data/synthetic-demo"
.venv/bin/python demo/serve.py
```

The launcher serves the compiled UI on `http://127.0.0.1:8001`. Rebuild the
frontend (`npm run build`) and restart the launcher after frontend changes.

## Run

From `application/`, with the demo server running:

```bash
npm run test:demo
```

This is `playwright test --config playwright.demo.config.ts`, which targets
`./apps/web/tests-demo` at `http://127.0.0.1:8001`. To run a single file:

```bash
npx playwright test --config playwright.demo.config.ts properties
```

Chromium must be installed once: `npx playwright install chromium`.

## Suites

| File | Covers |
| --- | --- |
| `properties.spec.ts` | `/properties` directory against the seeded demo portfolio: listing order, search, status-filter links, review-status isolation, ownership/rental-unit card disclosure, archived empty state, property open/return, create-workflow entry |
| `maintenance.spec.ts` | `/maintenance` workspace against the seeded demo issues: issue listing, card status/priority/category/property, category and priority filters, resolved empty state, issue detail with quote comparison, owner-concerns empty tab, report-issue workflow entry |
| `providers.spec.ts` | `/providers` directory against the seeded demo providers: listing, name search, category filter, card categories/services/areas/preference, empty-search state, provider open/return, category catalog link |
| `home.spec.ts` | `/home` against the seeded demo workspace: day heading, work-queue tabs, filter form, collection links, inventory summary, recorded-money metrics (all read-only) |
| `owners.spec.ts` | `/owners` directory against the seeded demo owners: listing order, name search, related-property counts and bounded previews, archived empty state, relationship-scope filter, owner open/return |
| `tenants.spec.ts` | `/tenants` directory against the seeded demo tenants: initial prompt, name search, full-roster search and browse, tenant open/return, empty-search state |
| `leasing.spec.ts` | `/leasing` workspace against the seeded demo leases: directory listing and status filter, lease detail (terms, milestones, participants), commercial card label, money cross-navigation, create-draft workflow entry |
| `money.spec.ts` | `/money` workspace against the seeded demo finances: view tabs and rent filters, expectation listing, settlement filter, property/lease-scoped records, expenses, deposits, empty scheduled-checks tab |

## Conventions

- **Read-only by default.** Suites must not submit workflows or mutate the
  demo workspace, so `demo/verify.py` counts stay valid. If a suite needs
  writes, it must clean up after itself.
- **Fresh seed for repeatability.** Expected counts describe a freshly seeded
demo; dates age normally. Reseed into a new directory (see
demo/README.md) when assertions drift.
- **Keep out of `apps/web/tests`.** `scripts/web_acceptance.mjs` runs every
  spec there against disposable smoke workspaces; demo suites would fail
  there because the seeded records do not exist.
- Follow the existing spec style: `@playwright/test` imports, exact
  accessible names (`getByRole`/`getByLabel`), and `test.use` with the
  loopback `Origin` header.
