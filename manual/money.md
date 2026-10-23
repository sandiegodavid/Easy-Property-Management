# Money

[Manual contents](README.md)

**Money** separates Rent, Received rent, Expenses, Deposits, Scheduled checks, Owner reports, Expense categories and Reporting. Check Property/Lease filters before entering anything. The app records external activity; it does not move money or connect to a bank account.

## Set up rent expectations

1. Execute/review the Lease and select its applicable term.
2. Open **Review rent setup** from the Lease or **Rent → Synchronize rent schedule**.
3. Preview the schedule. Check the anchor, due dates, covered periods, prorated first/final amounts and property time zone.
4. Confirm the exact reviewed schedule. Changed inputs require another preview; responsibility overrides require their own reason/confirmation.
5. Save synchronization, then inspect Expected, Money received and Still due.

Future lease changes do not rewrite old expectations. Review changed terms and synchronize explicitly. Use **Void rent expectation** only when appropriate; inspect payment allocations before correcting obligations. **Review rent timeliness** records mark-missed/clear-missed decisions with dates/reasons and does not make a legal determination.

## Record actual rent received

1. Open the rent period and choose **Record payment**. Its still-due amount and allocation are filled in for you.
2. Confirm the amount in USD dollars, **Received on** date and payment method. The date starts at today in the property's time zone; change it for a different payment date.
3. For a partial payment, edit both the payment and selected period's allocation. To cover more periods, check their boxes and adjust the amounts, or use **Allocate remaining…** when offered. The totals show anything not yet allocated. You can save an unfinished form before the totals match; the complete payment must be allocated before submitting.
4. Inspect likely duplicates and existing receipts before confirming another receipt.
5. Save and review the confirmation: amount, received date, method, and whether each period was paid in full or still had a balance after this payment. Choose **Back to rent** or **Record another payment**. Open the receipt from Received rent to add evidence or review later changes.

“Automatic bank payment” describes an arrangement outside the app; it does not authorize a debit. A prior receipt may suggest an editable method. Optional method descriptions, references and notes are under **Additional details**. Enter only safe masked references, such as `Check •••• 9182`, not raw bank/account/check identifiers. Other payment method requires an explanation.

An early payment actually received and allocated to a future expectation is received money. A scheduled undeposited check is not.

### Correct a receipt

Open the actual receipt and review date, allocations, method and replacement history. Use the offered void/correction flow, provide the reason and confirm. Record a replacement only through the supported predecessor/context flow. Preserve the original and check the resulting ledger. If another window changed the ledger, review latest facts while retaining input. Do not re-enter a receipt after an unknown response; recover its original result first.

## Scheduled prepaid checks

1. Schedule one check for exactly one full eligible rent-expectation period and payer.
2. Verify its future deposit date and reminder. Scheduling is not receipt of rent.
3. When eligible and actually deposited, **Deposit prepaid check** and explicitly create/adopt the compatible receipt.
4. If it is returned, **Return prepaid check**; inspect the linked receipt's reversal and reopened balance.
5. Void an unused instrument or **Replace prepaid check** using the permitted predecessor state. Keep lineage/history rather than duplicating a scheduled instrument.

Depositing here records your external action; the app does not deposit funds at a bank.

## Paid expenses, refunds and categories

1. Open **Expenses → Record paid expense**.
2. Select property and optional rental unit, paid date, amount, category, payee and who paid; link the provider when applicable.
3. Record only confirmed paid spending. A quote, estimate or unpaid invoice is not an expense.
4. Save, then attach evidence. A failed evidence upload leaves the paid expense recorded; retry only that upload.
5. Edit allowed context, or void/replace the actual financial record with the required history/reason.

Record a received expense refund separately with its received date/amount. Void an incorrect refund through its own action. A refund received in a later month belongs to that later reporting period.

Use **Expense categories** to create/edit/archive/restore the catalog. Category changes do not rewrite historical expenses. This catalog is separate from provider and issue categories.

## Security deposits and settlement

The lease's agreed deposit is not proof money was received.

1. Open **Deposits**, create the Lease's deposit account from the explicit term/agreed amount and confirm its context.
2. Record actual deposit receipts with payer, recipient, date and amount. Correct erroneous receipts by the supported void action.
3. After the relevant move-out review, **Prepare deposit settlement**.
4. Add/edit/delete draft deductions and credits. For each deduction, enter the operator-reviewed amount and add permitted supporting sources: files, finalized inspections, rent expectations or paid expenses.
5. Review held receipts, selected source evidence, credits, deductions and refund due. Record any required deadline and rule/source notes; no automatic legal deadline is implied.
6. **Approve deposit settlement** only after checking the complete frozen review.
7. Record each actual deposit refund. Partial refunds remain partial.
8. **Complete deposit settlement** only when actual refunds exactly fulfill the approved amount, or the explicit zero-refund closure is confirmed.

Delete a draft deduction/credit/source only through its matching action and confirmation. Correct approved/financial records through void/replacement history; voiding a settlement does not undo actual money already refunded. A later receipt or negative reconciliation value needs explicit review. A zero balance alone does not close a settlement.

## Owner-reported rent

1. Open **Owner reports → Record owner rent report** for the specific client owner, Lease and received-payment context.
2. Record amount, **Received on** date, payment method, reporter and evidence. The report time is recorded automatically when you save, including replacement reports; editing a pending report keeps its original report time. Pending claims do not increase received income.
3. Edit a pending report or reject it with an explanation when appropriate.
4. To verify, compare source evidence with Finance receipts. Explicitly adopt one compatible existing receipt or create one through verification with reviewed allocations.
5. Review both report and ledger changes if a conflict appears. Verify the final Finance record is counted once.

A verified report can retain historical verification even if its linked receipt is later voided; inspect that receipt's current state. Use ordinary Finance receipts for self-owned property money rather than inventing a client-owner report.

## Reporting

Choose an explicit inclusive From/Through period and scope, then open a metric to view its source records. Use the matching View all/source pages rather than summing only visible rows. Restart changed/expired views with filters retained.

| Figure                 | Interpretation                                                                                |
| ---------------------- | --------------------------------------------------------------------------------------------- |
| Rent received          | Current non-voided receipts dated in the selected period, each once                           |
| Expenses paid          | Paid non-voided expenses in the period                                                        |
| Expense refunds        | Active actual refunds received in the period                                                  |
| Net recorded expenses  | Expenses paid less refunds received                                                           |
| Rent less net expenses | Recorded rent less paid expenses plus refunds; not profit or bank cash                        |
| Deposit obligation     | Current held-money reconciliation at capture, not a historical balance at the report end date |

Archived properties may contribute retained history. For owner context, select a related Property when required; whole-property activity does not establish owner entitlement. Owner statements, management fees, payouts and bank reconciliation are separate scopes.
