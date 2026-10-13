# FIN-008 — completed acceptance, October 13, 2026

Current behavior is consolidated in the [Finance guide](../../modules/finance.md#security-deposits). The [original design](FIN-008_DESIGN.md) preserves contract decisions and rationale. This pass closes the remaining browser review/calculator, Party selection, correction and evidence-history gaps over existing atomic account-revision commands. No schema or persistence-format changes were required.

## Focused validation matrix

| Area | Evidence | Result |
| --- | --- | --- |
| Happy paths | Account/receipts, settlement draft/children/source edits, explicit approval, independently recorded partial refunds and zero-dollar completion | Passed |
| Invalid combinations | Membership/lifecycle guards, missing or unavailable deduction evidence, historical/exception confirmations, interest bounds and applied override reasons, refund and receipt aggregates | Passed |
| Idempotency/retries | Immutable original command responses, changed reuse and stale revisions, duplicate receipt/refund review, draft-child deletion lost-response recovery and retained correction chains | Passed |
| Rollback | Credit/refund/receipt/audit/result failures roll back atomically; source preview and interest calculation create no records | Passed |
| Persistence/schema | Exact Finance schema, terminal state and approval capture/source invariants; retained-data tampering and audit/privacy checks | Passed |
| Backup/restore | Focused Finance/Party suites exercise encrypted retained records and original-result recovery, with source/approval graph rejection tests | Passed |
| Query budgets | One bounded SQL Party-selection query per page; source preview at most three SELECTs; evidence uses shared FILE-001 joined facts without additional per-file reads | Passed for focused assertions |
| Browser/accessibility | Calculation review and renewed override approval, Party payer, duplicate/correction receipts/refunds, source preview, evidence archive/history, account filters and narrow light/dark settlement axe checks | Passed |

Focused validation from `application/`:

- `test_finance.py`, `test_commands.py`, `test_consumer_commands.py`, `parties/tests/test_identity_commands.py`: **84 passed** together.
- `money.spec.ts`: **28 passed**, including four new FIN-008 cases and shared Money regression coverage.
- Configured changed-Python Ruff checks/formatting, frontend lint, complete type checking, changed-file formatting, reproducible contracts, Vite build, local wheel packaging and diff whitespace validation: passed.

Root `npm run format:check` remains incomplete only because of existing `demo/dataset.json` and `demo/README.md` formatting. The informational bundle-size warning remains. The full application suite and a separate manual accessibility audit were not run. Other Finance features and pending review findings retain their own gates; this feature does not initiate payments, infer legal liability or determine statutory deadlines/rates.
