# Synthetic application demo

This demo creates a usable workspace through the application's real HTTP contracts, including official records, related identities, command receipts and audit history. All names, addresses, contact details and transactions are fictional; email addresses use `example.invalid`. It does not send real messages, payments or appointment requests, or configure model connections and credentials.

The dataset and scripts live in this directory. Generated records live in an **external workspace**, separate from the operator's data. The demo uses its own ignored `demo/config.local.json` and leaves `application/config.local.json` unchanged.

## First-time setup

Prepare the project Python environment and npm dependencies using the [repository setup instructions](../../README.md#prepare-a-development-checkout). Run all commands below from `application/`. They invoke `.venv/bin/python` explicitly, so activating the environment or having a system `python` command is not required.

In each new terminal, select the same interpreter for npm's Python tooling:

```bash
export EPM_PYTHON="$PWD/.venv/bin/python"
```

If `.venv/bin/python` is missing, complete the repository setup first. If your project environment lives elsewhere, substitute its Python executable in these commands and in `EPM_PYTHON`.

The npm tooling prefers this `application/.venv` environment when `EPM_PYTHON` is unset, falling back to the repository-level environment. If a build reports stale contracts after dependency changes, run `npm run contracts:generate`, review the generated changes, then rebuild using the same interpreter. Different FastAPI/Pydantic versions can generate different OpenAPI snapshots.

### 1. Generate the workspace

Choose a new, empty directory outside the repository:

```bash
.venv/bin/python demo/seed.py --workspace "$HOME/Property-Management-Data/synthetic-demo"
```

The generator initializes the workspace and writes `demo/config.local.json` pointing to it. It also creates a sibling directory named `<workspace-name>-demo-runtime` containing the request journal, captured scenario date, runtime configuration and record catalog.

For the example above:

```text
Property-Management-Data/
├── synthetic-demo/                 Workspace database, files and manifest
└── synthetic-demo-demo-runtime/    Generator journal, catalog and verification report
```

### 2. Verify the generated scenarios

Run verification immediately after generation:

```bash
.venv/bin/python demo/verify.py
```

The verifier checks exact record counts, expense-group totals, provider links, funded deposits, executed leases, the vacancy and rent scenarios. It uses read-only SQL and real API reads, checks SQLite integrity and foreign keys, and validates the current application schema. It prints the result and saves `verification.json` in the sibling runtime directory.

Verification assumes the original scenario date and records. Manual edits or date rollover can change the expected results; see [Dates and repeatability](#dates-and-repeatability).

### 3. Build and open the browser UI

```bash
npm run build
.venv/bin/python demo/serve.py
```

Open **http://127.0.0.1:8001/properties**. Explore the existing Home, Properties, Owners, Leasing, Money, Maintenance and Providers workflows, including related conversations and Tasks. Stop the server with Ctrl+C.

After updating server code, restart the launcher. If an older running server rejects a clicked link with `transport_origin_required`, paste the URL directly into the browser's address bar; the corrected transport policy permits public app-page navigation while keeping cross-site API reads and writes blocked.

The launcher reads `demo/config.local.json` and serves the compiled UI from `apps/web/dist`. It requires neither wheel packaging nor frontend staging. Rebuild with `npm run build` after frontend changes, then restart the launcher.

## Open an existing demo

Once generation and the frontend build are complete:

```bash
.venv/bin/python demo/serve.py
```

To use another port or a separate demo configuration:

```bash
.venv/bin/python demo/serve.py --config /absolute/path/to/demo-config.json --port 8002
```

Open the corresponding loopback URL, for example `http://127.0.0.1:8002/properties`.

## Included scenarios

| Group                 | Properties                                       | Scenario/activity                                                                                                                            |
| --------------------- | ------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------- |
| Local operator        | 3: vacant cottage, rented home, rented office    | 1 upcoming furnace issue/appointment, 2 communications, 12 expenses                                                                          |
| Morgan Chen (Owner 1) | 2 rented homes                                   | 1 unpaid rent expectation with follow-up Task, 1 communication, 8 expenses, 1 routine inspection appointment, 1 next-month rent prepayment   |
| Sam Rivera (Owner 2)  | 5: three condo units, rented home, rented office | 2 urgent maintenance issues, 3 competing quotes per issue, 3 communications, 1 condition inspection draft, 20 expenses, 1 repair appointment |

The generated workspace contains:

| Record type                    |   Count |
| ------------------------------ | ------: |
| Properties / rentable Spaces   | 10 / 10 |
| Executed leases                |       9 |
| Fully funded security deposits |       9 |
| Providers                      |      20 |
| Paid expenses                  |      40 |
| Recorded communications        |       6 |
| Appointments                   |       3 |
| Quotes                         |       6 |
| Condition reports              |       1 |

Every occupied rental, including both offices, has monthly USD rent and an agreed deposit equal to one month's rent, with an actual deposit receipt. The vacant cottage has no fabricated lease or deposit.

All 20 providers have category assignments, service areas and links to property expenses. The seven categories cover plumbing, HVAC, electrical, landscaping, appliance repair, general maintenance and legal/attorney services.

Office properties are included in the property totals. The three Riverbend condo properties share a building address but have distinct unit addresses and one rentable Space each. This follows the current model: residential properties have exactly one rentable Space; multiple office suites are supported, while a residential multi-Space building aggregate is not.

Owner 1's inspection appointment belongs to a separate low-priority plumbing issue. The unpaid-rent scenario lives in Finance and Tasks rather than Maintenance. The condition report remains a reviewable pre-move-in draft, and quotes remain available for comparison without an automatic acceptance.

## Dates and repeatability

The first generation captures today's date in `America/Los_Angeles`. Resuming reuses that date, while the running application continues to use its real clock. Rent is scheduled through the following month: one current-month expectation remains unpaid and an actual prepayment is allocated to next month. On the first day of the month, current-month rent is due rather than late.

Dates age normally. To refresh an interactive demo, generate into a new empty directory using the current date. For controlled fixtures, the generator accepts `--as-of YYYY-MM-DD`; this sets scenario dates without freezing the application clock.

## Resume or customize generation

Rerun the same seed command with the same workspace path to resume an interrupted run. Original keyed requests are journaled before submission, and completed steps reuse their recorded results without creating duplicate records.

The generator refuses a populated destination without its own journal and does not reset or delete a workspace. Keep the sibling runtime directory with its workspace so the journal and scenario catalog remain available. After changing `dataset.json`, use a new empty destination; an existing journal retains its original records.

Use `--local-config` to keep another demo or test fixture's launcher configuration separate:

```bash
.venv/bin/python demo/seed.py \
  --workspace /absolute/path/to/new-demo \
  --local-config /absolute/path/to/demo-config.json
.venv/bin/python demo/verify.py --config /absolute/path/to/demo-config.json
.venv/bin/python demo/serve.py --config /absolute/path/to/demo-config.json
```

## Validate the tooling

From `application/`:

```bash
ruff check --config pyproject.toml demo/seed.py demo/serve.py demo/verify.py
ruff format --check --config pyproject.toml demo/seed.py demo/serve.py demo/verify.py
```

For everyday operation and data protection, use the [operator manual](../../manual/README.md). Build and packaging details belong in the [repository README](../../README.md#production-build-and-packaging-instructions).
