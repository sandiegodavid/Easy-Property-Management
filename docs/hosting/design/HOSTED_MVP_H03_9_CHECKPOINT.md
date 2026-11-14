# H03.9 Operator Security and session workflows

H03.9 provides the managed Operator Security panel, session status, renewal,
and device sign-out. The managed composition serves the packaged sign-in UI
and identity endpoints. The [H03.10 checkpoint](HOSTED_MVP_H03_10_CHECKPOINT.md)
records the subsequent business request and edit-lease admission work.
Packaging and deployed qualification remain H03.11 and H03.12 work. The H03.9 evidence is local and uses synthetic identity fixtures.

- Renewal opens a separate window and verifies the changed session through
  the owning source. The same identity resumes the mounted editor only after
  **Continue to workspace**. A different verified identity remounts the
  private scope. The top-level fallback tells the operator to save or copy
  unfinished input before navigating. No command is replayed.
- Security lists up to 32 live devices using public session selectors, coarse
  browser labels, last-seen times, and a current-device indicator.
- Sign-out commits source revocation first and reconciles the original receipt
  centrally. The initiating tab and its same-session sibling tabs close
  private content immediately for current or all-device sign-out. If the
  response is lost, the initiating tab retains only an operation ID and scoped
  check proof in session storage. **Check sign-out status** checks the
  original result without resubmitting the source command.
- At the cap, a fresh signed handoff and its matching destination challenge
  allow an explicit device choice. The source revokes that device and creates
  the new session in one transaction, with the displaced managed-session
  reference in the original receipt. Central acknowledgement reconciles
  that exact managed session.

## Focused validation

219 focused Python tests and 14 Playwright tests passed. Ruff lint and
formatting, frontend lint, formatting and typechecking, and Git whitespace
checks passed.

| Area | Local evidence |
| --- | --- |
| Browser renewal | Window opens without opener authority, blocked-window fallback, same-identity input and focus preservation, explicit continuation, different-identity reset. |
| Device security | Keyboard confirmation, narrow layout, two tabs and a separate browser context, remote device revocation, and a lost sign-out response checked after reload. |
| Source HTTP | Packaged sign-in at the registered HTTPS origin, safe projections, exact Origin and CSRF, status refresh and revocation, missing operation proof, cookie cleanup after a lost response, and original receipt reconciliation. |
| Capacity | Fresh handoff and cookie required, explicit device selection at 32, same-origin selection, one replacement, and replay denial. |
| Persistence | Existing schema, handoff, identity retention, and local composition regressions. |
