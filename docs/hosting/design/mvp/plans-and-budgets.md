# Plans, budgets and demand gates

[Hosted MVP design index](../HOSTED_MVP_DESIGN.md) · [Schema catalog](../../../database/README.md)

Part of the accepted HOSTED-001 design. Requirements here do not establish implementation, deployment or qualification; Pilot 0 exceptions are in the [delivery plan](delivery-plan.md).

In this guide: [Plans and financial envelope](#plans-and-financial-envelope) · [Provisional product catalog](#provisional-product-catalog) · [Operating budgets and demand validation](#operating-budgets-and-demand-validation)

## Plans and financial envelope

<a id="2-plans-and-financial-envelope"></a>

### Provisional product catalog

| Benefit | Free | Paid 1 — provisional $10/month | Paid 2 — provisional $20/month |
| --- | --- | --- | --- |
| Usable workspace allowance | 50 MB | 200 MB | 1 GB |
| Business application and supported imports | Included | Included | Included |
| Backup cadence | Nightly | Recent recovery-point target of 15 minutes | Recent recovery-point target of 15 minutes |
| Retention | Seven nightly points | Fine-grained points for latest 24 hours, then daily through 30 days | Fine-grained points for latest 24 hours, then daily through 90 days |
| Idle runtime | May suspend after approximately 15 minutes | Keep warm initially | Keep warm initially |
| Tenant portal/payments | Not included | Intended future benefit; not delivered here | Intended future benefit; not delivered here |

Prices are provisional USD monthly product prices, not researched market benchmarks
or authorization to charge. Measure representative portfolios before publishing
allowances. Use exact decimal bytes: 50,000,000 / 200,000,000 / 1,000,000,000.
Each allowance requires a separately [qualified physical byte/inode profile](subscriptions-storage-and-runtime.md#per-tier-physical-storage-sizing-acceptance),
measured peaks and justified margins, plus independent exhaustion/recovery tests.
The Free gate precedes Pilot 0; paid gates precede tier activation. No fixed ratio
or existing trial ceiling establishes sizing.

There is no fixed property/space entitlement in this fresh plan. Recovery assistance
and data export remain available to Free operators; paid plans improve available
recovery points and history, rather than charging for release of existing data.

### Operating budgets and demand validation

- Launch target: **$250/month before credits**, replacing the earlier $20 target.
- Growth target: **$300/month before credits at 100 operators**, subject to measured
  workload, paid/free mix and retained recovery data. These are different operating
  stages; do not interpolate a guaranteed cost per operator.
- Include compute, persistent storage, backups, authentication, transactional email,
  networking and monitoring. Track billing/payment-provider fees separately and
  disclose them in the unit-economics model; tenant payment fees are out of scope.
- The user reports Google credits of approximately $300/month until February.
  Confirm actual account terms/end date before financial planning. Credits fund
  validation and experiments; they do not reduce the recorded steady-state cost.
- Admin authorizes a spending envelope. Automation may place/provision capacity
  within it, using qualified profiles. Exceeding it requires explicit approval.
  Budget alerts are not enforcement. Account for delayed metering and outstanding
  allocations; never promise an exact final cloud invoice ceiling from an alert.
- If capacity does not fit, preserve safety/UX, stop new admissions or unfulfillable
  upgrades, and present measured alternatives. Do not silently exceed the envelope
  or reduce protection to claim the requested operator count fits.

Validate interest before credits expire. Agreed pilot gate: at least five genuine invited
operators, at least three doing recurring work weekly for four consecutive weeks,
at least one informed paid subscriber after paid plans launch, and no unresolved
critical data-loss or cross-operator isolation defect. Pilot 0 measures activation,
repeat use and support/cost evidence without requiring or accepting payment. Track activation, repeat use, paid conversion,
support effort and gross cost per active operator. Seeded/demo logins do not count.
Pivot or redesign if results justify it; avoid building a large platform ahead of demand.

