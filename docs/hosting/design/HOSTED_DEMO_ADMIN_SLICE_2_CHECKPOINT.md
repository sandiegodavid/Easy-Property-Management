# Hosted Admin Slice 2 — completion checkpoint

Updated October 28, 2026. Repository implementation is complete on `Admin_UI_Workflow`; changes are saved and uncommitted. No host, service, invitation, provider configuration or live workspace was changed.

The [private authority runbook](../operations/HOSTED_ADMIN_AUTHORITY.md) is the implementation/installation reference and validation matrix. The [design](HOSTED_DEMO_ADMIN_DESIGN.md#ordered-implementation-slices) records Slice 2 as repository delivered. Continue with the named later slices rather than repeating the former in-progress checklist.

Delivered: separate native private sign-in and loopback listener; hash-only single-use grants; session/CSRF/Origin/peer checks; action-bound authorization; generation revocation and private restoration; immutable command admission/results; bounded source status; fixed inventory-bound target-user dispatch; atomic source mutation/audit/receipts and retained-history checks; source configuration/restore fencing; safe original-receipt reconciliation; launcher and separate unit templates. Onboarding enable remains blocked without Slice 6 recovery/acceptance evidence.

Validation: **386 passed, 1 skipped** across focused Admin/access, audit actor and affected private-tool suites. The skip is the existing `test_linux_storage_qualification.py:29`, requiring an explicitly provisioned disposable Linux quota volume. Ruff check and format --check passed for all 22 changed Python files; Python 3.12 syntax, shell syntax, frontend lint/format/typecheck and whitespace checks passed. All **3 private Admin Playwright tests passed**. No full application suite was run.

Real Linux peer/runuser/sandbox, installed release/profile, IAP/hostname/cookie and live A/B acceptance remain deployment qualification; mock or macOS tests do not claim those gates. Host-control recovery, orchestration resume after authority fencing, management UI, provisioning, renewal and onboarding recovery remain their later design slices.

User usage guard remains: save and stop at weekly remaining <=2% or five-hour remaining <=5%. Recheck usage before further implementation.
