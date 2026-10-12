# Synthetic application demo

This is a reproducible, usable workspace populated through the application's real
HTTP contracts. It includes official records, related identities, command receipts
and audit history. All names, addresses, contact details and transactions are
fictional; email addresses use `example.invalid`.

The dataset and tooling live here. The database lives **outside the repository**,
as required by workspace initialization. Generation writes an ignored
`config.local.json` here pointing to that external workspace. It does not change
`application/config.local.json` or the operator's existing workspace.

## Open the generated demo

From `application/`, using the existing project Python environment:

```bash
.venv/bin/python demo/serve.py
```

Open **http://127.0.0.1:8001/properties**. Use Owners, Leasing, Money,
Maintenance, Providers and Conversations to explore the related records.
Stop the server with Ctrl+C. The launcher uses the compiled UI in
`apps/web/dist`; run `npm run build` first if it is absent or outdated.

The generated workspace for this checkout is:

```text
/Users/dcai/Desktop/Property-Management-Data/synthetic-demo/
```

Its sibling `synthetic-demo-demo-runtime/` contains the seed journal, scenario
catalog, captured demo date, runtime config and verification report.

## Scenarios and exact counts

| Group | Properties | Scenario/activity |
| --- | --- | --- |
| Operator | 3: vacant cottage, rented home, rented office | 1 upcoming furnace issue/appointment, 2 communications, 12 expenses |
| Morgan Chen (Owner 1) | 2 rented homes | 1 unpaid late rent expectation with follow-up Task, 1 communication, 8 expenses, 1 routine inspection appointment, 1 next-month rent prepayment |
| Sam Rivera (Owner 2) | 5: three condo units, rented home, rented office | 2 urgent maintenance issues, 3 competing quotes per issue, 3 communications, 1 condition inspection draft, 20 expenses, 1 repair appointment |

There are **10 properties/10 rentable spaces, 9 executed leases, 9 fully funded
security deposits, 20 providers, 40 paid expenses, 6 recorded communications,
3 appointments, 6 quotes and 1 condition report**. The vacant cottage has no
fabricated lease or deposit. Every occupied rental, including both offices, has
monthly USD rent and an agreed deposit equal to one month's rent, with an actual
recorded deposit receipt. All 20 providers have category assignments, service
areas and links to property expenses across the portfolio. Seven provider
categories include Plumbing, HVAC, Electrical, Landscaping, Appliance repair,
General maintenance and Legal / Attorney.

Office properties are included in the requested property totals. The three
Riverbend condo units share a building address and have distinct unit addresses.
This matches the current model: residential properties have exactly one rentable
space; multiple office suites are supported, but a residential multi-space
building aggregate is not. No unsupported schema or inventory type is inserted.

The Owner 1 appointment is backed by a separate low-priority plumbing issue;
the late-rent concern is represented in Finance and Tasks, rather than as a
maintenance issue. The inspection remains a reviewable pre-move-in draft.
Quotes remain available for comparison; no quotation is silently accepted.

## Generate or resume

Choose an **empty external** folder and run from `application/`:

```bash
.venv/bin/python demo/seed.py \
  --workspace "/Users/dcai/Desktop/Property-Management-Data/synthetic-demo"
.venv/bin/python demo/verify.py
```

The generator uses today's Pacific date on first run. It records that date so a
resumed run preserves its original scenario. The supplied workspace was generated
on October 12, 2026. Dates subsequently age normally with the real application
clock; regenerate into a new empty folder to refresh the scenarios. Rent is
scheduled through next month. One current-month expectation stays unpaid; the
prepaid scenario has an actual payment allocated to next month. On the first day
of a month, unpaid current-month rent is due rather than late.

Original keyed requests are journaled before submission. Interrupted runs resume
and completed runs reuse recorded results without adding duplicate records.
Existing populated folders without this generator's journal are refused. The
generator does not reset or delete any workspace. After editing `dataset.json`,
use a new empty destination; replaying an existing journal retains its original
records. `--as-of YYYY-MM-DD` is available for controlled fixtures; use the actual
current application date for an interactive demo. `--local-config PATH` lets
verification fixtures keep their launcher config separate from this demo.

`verify.py` checks exact record counts, expense group totals, all provider links,
funded deposits, executed leases, one vacancy, late unpaid rent and future rent
payment through read-only SQL and real API reads. It also checks SQLite integrity,
foreign keys and the application's current workspace schema. Verification is
intended immediately after generation, before manual demo edits or date rollover.

## Validate tooling

```bash
ruff check --config pyproject.toml demo/seed.py demo/serve.py demo/verify.py
ruff format --check --config pyproject.toml demo/seed.py demo/serve.py demo/verify.py
```

No real emails, payments or provider appointments are sent. Model connections and
credentials are not configured by the generator.
