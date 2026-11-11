# Operator provisioning and onboarding

[Hosted MVP design index](../HOSTED_MVP_DESIGN.md) · [Schema catalog](../../../database/README.md)

Part of the accepted HOSTED-001 design. Requirements here do not establish implementation, deployment or qualification; Pilot 0 exceptions are in the [delivery plan](delivery-plan.md).

## Admin creation and automatic onboarding

<a id="5-admin-creation-and-automatic-onboarding"></a>

Admin selects **Add operator** and supplies display name, exact sign-in email,
available workspace slug, support contact and proposed plan. Default to Free and an
empty workspace. An optional small synthetic dataset is a per-operator demonstration
choice, not a required population or count; demo activity is excluded from pilot metrics.
Admin may propose a paid plan but cannot authorize an undisclosed charge on behalf
of the operator. Explicit complimentary grants must be audited, time-bounded and
capacity-qualified, never hidden quota edits.

The creation flow is:

1. Validate identity/slug uniqueness, qualified release/profile, available capacity
   and spending envelope. Show the reviewed assignment before submission.
2. Admit one durable job and reservations; return a Pending row immediately. Closing
   the browser does not cancel or resubmit it.
3. Allocate private persistent workspace/control/scratch resources, publish the
   protected configuration and initialize actual source authority with access disabled.
4. Start/verify the source, initialize business data, verify routing/isolation and
   create a verified off-host recovery point. Progress is async with retained status.
5. Send a short-lived single-use invitation only when ready. Keep the recipient/URL
   assignment pinned and invite sending deduplicated; expiry of an invitation is
   not expiry of the account. Provide controlled resend/reissue.
6. The operator signs in with the invited verified identity and claims the assignment.
   Automatically enable it only when current readiness/recovery and identity checks
   all pass. Admin's invitation is the routine authorization: no second manual
   identity approval/completion click is required for an ordinary successful claim.
7. Show the operator their workspace, Free plan, usage and any proposed paid offer.
   Paid activation requires the operator's checkout authorization and confirmed payment.

**Business access remains disabled while setup runs**, including seeding and exception
handling. A healthy container or authenticated but unassigned identity is insufficient.
Failed steps remain Pending/Needs attention with safe reasons and retry lookup. Never
create another workspace, discard partial records or enable access simply to clear an
error. Retire resources only through ownership-verified, reviewed cleanup.

Admin overview/detail shows operator count, qualified capacity, plan/effective allowance,
usage/freshness, service state, backup age, release and operation history. Separate
Pending setup, Ready for claim, Active, Suspended runtime, Access disabled and Needs
attention. An idle suspended container is not a disabled operator. Keep the UI responsive
while jobs run; show retry/reconciliation actions rather than raw infrastructure tools.

