import { expect, test, type APIRequestContext } from "@playwright/test";
import type { components } from "@epm/contracts/generated";
import axe from "axe-core";

type Schemas = components["schemas"];
test.use({ extraHTTPHeaders: { Origin: "http://127.0.0.1:18744" } });

async function post<T>(request: APIRequestContext, path: string, data: unknown): Promise<T> {
  const response = await request.post(path, { data });
  expect(response.ok(), await response.text()).toBe(true);
  return (await response.json()) as T;
}

async function createOverdueLeaseFixture(request: APIRequestContext) {
  await post(request, "/__test__/lease-clock", { days: 0 });
  const property = await post<Schemas["PropertyMutationResponse"]>(request, "/api/properties", {
    displayName: `FIN009 home ${crypto.randomUUID().slice(0, 8)}`,
    addressLine1: "42 Oak Avenue",
    city: "Portland",
    region: "OR",
    postalCode: "97201",
    countryCode: "US",
    propertyType: "single_family_home",
    expectedPropertyRevision: 0,
    idempotencyKey: crypto.randomUUID(),
    ownerships: [
      {
        ownerKind: "client_owner",
        inlineParty: {
          partyKind: "individual",
          displayName: `FIN009 owner ${crypto.randomUUID().slice(0, 8)}`,
        },
      },
    ],
  });
  const today = property.effectiveLocalDate;
  const start = new Date(Date.UTC(Number(today.slice(0, 4)), Number(today.slice(5, 7)) - 2, 1))
    .toISOString()
    .slice(0, 10);
  const through = new Date(Date.UTC(Number(today.slice(0, 4)), Number(today.slice(5, 7)), 0))
    .toISOString()
    .slice(0, 10);

  const tenant = await post<Schemas["TenantMutationResponse"]>(request, "/api/tenants", {
    partyKind: "individual",
    displayName: `FIN009 tenant ${crypto.randomUUID().slice(0, 8)}`,
    officialIds: [{ documentType: "passport", issuingCountry: "US", lastFour: "9009" }],
    expectedRevision: 0,
    idempotencyKey: crypto.randomUUID(),
  });

  const lease = await post<Schemas["LeaseMutationResponse"]>(request, "/api/leases", {
    expectedLeaseRevision: 0,
    idempotencyKey: crypto.randomUUID(),
    spaceId: property.spaces[0].id,
    leaseKind: "residential",
    contractStartsOn: start,
    occupancyStartsOn: today,
    initialTerm: {
      baseRentMinor: 100000,
      currencyCode: "USD",
      paymentFrequency: "monthly",
      paymentDueDay: 1,
      agreedSecurityDepositMinor: 100000,
    },
    participants: [{ tenantPartyId: tenant.id, participantRole: "primary_tenant" }],
  });

  await post(request, `/api/leases/${lease.id}/execute`, {
    expectedLeaseRevision: lease.leaseRevision,
    expectedRevision: property.spaces[0].revision,
    idempotencyKey: crypto.randomUUID(),
    confirmed: true,
    executedOn: today,
  });

  const synced = await post<Schemas["SynchronizeResponse"]>(
    request,
    `/api/leases/${lease.id}/rent-expectations/synchronize`,
    {
      expectedRevision: 0,
      idempotencyKey: crypto.randomUUID(),
      leaseTermId: lease.terms[0].id,
      throughOn: through,
      scheduleAnchorOn: start,
    },
  );

  return { property, tenant, lease, synced, today, start, through };
}

test("late fees end-to-end: policy, preview invalidation, assess, partial waive, combined payment, queue, and reporting", async ({
  page,
  request,
}) => {
  const f = await createOverdueLeaseFixture(request);

  await page.goto(`/leases/${f.lease.id}/details`);
  const lateFeesSection = page.getByRole("region", { name: "Late fees", exact: true });
  await expect(lateFeesSection).toBeVisible();

  // 1. Empty policy state -> configure fixed flat policy
  await expect(lateFeesSection).toContainText("No late-fee policy configured.");
  await lateFeesSection.getByRole("button", { name: "Configure late-fee policy" }).click();

  const policyForm = lateFeesSection.getByRole("form", { name: "Configure late-fee policy" });
  await policyForm.getByLabel("Effective date (required)").fill(f.start);
  await policyForm
    .getByLabel("Contractual rule basis (required)")
    .fill("Lease Section 5(b), signed 2026-01-15");
  await policyForm.getByLabel("Grace period days (0–60, required)").fill("5");
  await policyForm.getByLabel("Flat amount USD (required)").fill("50.00");
  await policyForm
    .getByLabel("I confirm this policy matches the signed lease terms (required)")
    .check();
  await policyForm.getByRole("button", { name: "Save late-fee policy" }).click();

  await expect(lateFeesSection).toContainText("Version 1");
  await expect(lateFeesSection).toContainText("USD 50.00 flat");
  await expect(lateFeesSection).toContainText("Lease Section 5(b), signed 2026-01-15");

  // 2. Preview eligible late fees -> verify preview-only notice and invalidation on date edit
  await expect(lateFeesSection).toContainText("Preview only — not an assessed charge.");
  await lateFeesSection.getByRole("button", { name: "Preview eligible late fees" }).click();
  await expect(lateFeesSection).toContainText("Property time zone:");
  await expect(lateFeesSection).toContainText("Already assessed");

  const asOfInput = lateFeesSection.getByLabel("Review as-of date (property-local, optional)");
  await asOfInput.fill(f.start);
  await expect(lateFeesSection).not.toContainText("Property time zone:");

  // 3. Verify overdue period was automatically assessed under the confirmed policy
  const assessedSummary = lateFeesSection
    .locator('[aria-label="Assessed late fees"] summary')
    .first();
  await expect(assessedSummary).toContainText("Unpaid");
  await expect(assessedSummary).toContainText("Assessed USD 50.00");
  await expect(assessedSummary).toContainText("Remaining USD 50.00");

  // 4. Expand assessed row via keyboard Enter, verify frozen steps, and perform partial waive ($10.00)
  await assessedSummary.focus();
  await page.keyboard.press("Enter");
  await expect(
    lateFeesSection.getByRole("list", { name: "Frozen calculation steps" }),
  ).toBeVisible();

  await lateFeesSection.getByRole("button", { name: "Waive", exact: true }).click();
  const waiveForm = lateFeesSection.getByRole("form", { name: "Waive late fee" });
  await waiveForm.getByLabel("Waive amount USD (required)").fill("10.00");
  await waiveForm
    .getByLabel("Reason (required; visible to tenant and owner)")
    .fill("First-time courtesy partial waiver");
  await waiveForm.getByLabel("Confirm waiver").check();
  await waiveForm.getByRole("button", { name: "Confirm waive" }).click();

  await expect(assessedSummary).toContainText("Remaining USD 40.00");

  // 5. Record combined rent + late-fee payment for remaining $40.00 fee + open rent
  await lateFeesSection
    .getByRole("button", { name: "Record combined rent + late-fee payment" })
    .click();
  const combinedForm = lateFeesSection.getByRole("form", {
    name: "Record combined rent and late-fee payment",
  });
  await combinedForm.getByLabel("Received date (required)").fill(f.today);
  await combinedForm.getByLabel("Rent period (required)").selectOption({ index: 1 });
  await combinedForm.getByLabel("Late fee subtotal USD (required)").fill("40.00");
  await combinedForm
    .getByLabel("Masked reference (optional, e.g. Check •••• 8888)")
    .fill("Check •••• 4401");
  await combinedForm.getByRole("button", { name: "Save combined payment" }).click();

  await expect(assessedSummary).toContainText("Paid");
  await expect(assessedSummary).toContainText("Remaining USD 0.00");

  // 6. Navigate to Money -> Late fees queue and verify filtering + lease link
  await lateFeesSection.getByRole("link", { name: "Open in Money → Late fees" }).click();
  const queueSection = page.getByRole("region", { name: "Late fees queue", exact: true });
  await expect(queueSection).toBeVisible();
  await expect(queueSection).toContainText("Paid");
  await expect(queueSection).toContainText("Assessed USD 50.00");

  await queueSection.getByLabel("Settlement status").selectOption("paid");
  await expect(queueSection).toContainText("Assessed USD 50.00");
  await expect(queueSection.getByRole("link", { name: "Open Lease →" }).first()).toHaveAttribute(
    "href",
    `/leases/${f.lease.id}/details`,
  );

  // 6b. Navigate to Rent Expectation detail page and verify Late fees panel renders assessed fee + steps + pagination continuation
  const firstExpId = f.synced.items[0].id;
  let pagedIntercepted = false;
  await page.route("**/api/late-fee-assessments*", async (route) => {
    const url = new URL(route.request().url());
    if (
      url.searchParams.get("rentExpectationId") === firstExpId &&
      !url.searchParams.get("cursor")
    ) {
      const real = await route.fetch();
      const body = (await real.json()) as { items: unknown[]; nextCursor: string | null };
      pagedIntercepted = true;
      await route.fulfill({
        response: real,
        json: { ...body, nextCursor: "mock-page-2-cursor" },
      });
      return;
    }
    if (url.searchParams.get("cursor") === "mock-page-2-cursor") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        json: {
          items: [
            {
              id: "11111111-1111-4111-8111-111111111111",
              leaseId: f.lease.id,
              rentExpectationId: firstExpId,
              policyVersionId: "22222222-2222-4222-8222-222222222222",
              occurrenceNumber: 2,
              asOfDate: f.start,
              accrualStartsOn: f.start,
              accrualEndsOn: f.start,
              accrualDays: 1,
              assessedAmountMinor: 1500,
              waivedAmountMinor: 0,
              paidAmountMinor: 0,
              remainingBalanceMinor: 1500,
              currencyCode: "USD",
              settlementStatus: "unpaid",
              ruleBasisSnapshot: "Older historical fee page 2",
              sourceDriftWarning: false,
              replacesAssessmentId: null,
              replacedByAssessmentId: null,
              voidedAt: null,
              voidReason: null,
              assessedAt: new Date().toISOString(),
            },
          ],
          nextCursor: null,
        },
      });
      return;
    }
    await route.continue();
  });
  await page.goto(`/money?record=expectation&id=${firstExpId}`);
  const expLateFees = page.getByRole("region", { name: "Late fees for this rent period" });
  await expect(expLateFees).toBeVisible();
  await expect(expLateFees).toContainText("Assessed USD 50.00");
  await expect(expLateFees).toContainText("Fixed flat fee = USD 50.00");
  expect(pagedIntercepted).toBe(true);
  await expLateFees.getByRole("button", { name: "Load more late fees" }).click();
  await expect(expLateFees).toContainText("Assessed USD 15.00");
  await page.unroute("**/api/late-fee-assessments*");

  // 6c. Lease-level waiver on Lease Details waives remaining unpaid fee and pauses auto-assessment
  await page.goto(`/leases/${f.lease.id}/details`);
  await lateFeesSection.getByRole("button", { name: "Waive late fees at lease level" }).click();
  const leaseWaiveForm = lateFeesSection.getByRole("form", {
    name: "Waive late fees at lease level",
  });
  await leaseWaiveForm.getByLabel("Reason (required)").fill("Hardship lease-level waiver");
  await leaseWaiveForm
    .getByLabel("Confirm pausing automatic late-fee assessment for this lease (required)")
    .check();
  await leaseWaiveForm.getByRole("button", { name: "Confirm lease-level waiver" }).click();
  await expect(lateFeesSection).toContainText("Late fees waived at lease level.");

  // 7. Navigate to Money -> Reporting and verify Late fees received metric + drill-down
  await page.goto(
    `/money?tab=reporting&fromOn=${f.start}&throughOn=${f.today}&propertyState=all&propertyId=${f.property.id}`,
  );
  const reporting = page.getByRole("region", { name: "Money reporting", exact: true });
  await expect(reporting).toBeVisible();
  await expect(reporting).toContainText("Late fees received");
  await expect(reporting).toContainText("USD 40.00");
});

test("late fees void flow, responsive reflow (390/900/1440), light/dark themes, and accessibility", async ({
  page,
  request,
}) => {
  const f = await createOverdueLeaseFixture(request);

  // Configure policy and assess via API so we can test UI void + visual/a11y checks quickly
  await post(request, `/api/leases/${f.lease.id}/late-fee-policies`, {
    expectedRevision: 1,
    idempotencyKey: crypto.randomUUID(),
    effectiveOn: f.start,
    endsOn: null,
    leaseTermId: null,
    ruleBasis: "Lease Section 5(b)",
    gracePeriodDays: 5,
    calculationBasis: "unpaid_rent_at_grace_end",
    formulaKind: "fixed_flat",
    flatAmountMinor: 5000,
    percentageBps: null,
    dailyAmountMinor: null,
    maxAccrualDays: null,
    perPeriodCapMinor: null,
    perPeriodMinMinor: null,
    minimumUnpaidThresholdMinor: 0,
    roundingMode: "half_up",
    appliesToProratedPeriods: false,
    supersedesPolicyVersionId: null,
    notes: null,
    operatorConfirmed: true,
  });

  const preview = await post<Schemas["LateFeePreviewResponse"]>(
    request,
    `/api/leases/${f.lease.id}/late-fees/preview`,
    { asOfDate: f.today, rentExpectationId: null },
  );
  const eligible = preview.items.find((item) => item.eligibilityStatus === "eligible");
  expect(eligible).toBeDefined();

  await post(request, `/api/leases/${f.lease.id}/late-fee-assessments`, {
    expectedRevision: preview.rentLedgerRevision,
    idempotencyKey: crypto.randomUUID(),
    rentExpectationId: eligible!.rentExpectationId,
    asOfDate: preview.asOfDate,
    previewFingerprint: eligible!.previewFingerprint!,
    operatorConfirmed: true,
    acknowledgeProcessingPayments: false,
    processingAcknowledgmentReason: null,
    internalNotes: null,
    replacesAssessmentId: null,
  });

  await page.goto(`/leases/${f.lease.id}/details`);
  const lateFeesSection = page.getByRole("region", { name: "Late fees", exact: true });
  await expect(lateFeesSection).toBeVisible();

  // Check responsive reflow across 1440, 900, and 390px in both light and dark themes
  for (const theme of ["light", "dark"]) {
    await page.evaluate((value) => {
      document.documentElement.dataset.theme = value;
    }, theme);
    for (const width of [1440, 900, 390]) {
      await page.setViewportSize({ width, height: 900 });
      expect(
        await lateFeesSection.evaluate((element) => element.scrollWidth <= element.clientWidth),
      ).toBe(true);
    }
  }

  // Accessibility check on Late fees section
  await page.evaluate(axe.source);
  const violations = await page.evaluate(async () => {
    const result = await window.axe.run('section[aria-label="Late fees"]', {
      runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21aa"] },
    });
    return result.violations.map((v) => v.id);
  });
  expect(violations).toEqual([]);

  // Void assessment through UI
  await page.setViewportSize({ width: 1280, height: 900 });
  const assessedSummary = lateFeesSection
    .locator('[aria-label="Assessed late fees"] summary')
    .first();
  await assessedSummary.click();
  await lateFeesSection.getByRole("button", { name: "Void assessment" }).click();
  const voidForm = lateFeesSection.getByRole("form", { name: "Void late-fee assessment" });
  await voidForm.getByLabel("Void reason (required)").fill("Assessed in error");
  await voidForm.getByLabel(/Confirm voiding/).check();
  await voidForm.getByRole("button", { name: "Confirm void" }).click();

  await expect(assessedSummary).toContainText("Voided");
});

test("late fees review regressions: dropped-response reload recovery, void-and-replace assessment, receipt void/replace, and Record rent receipt combined split", async ({
  page,
  request,
}) => {
  const f = await createOverdueLeaseFixture(request);

  // Configure policy via API
  await post(request, `/api/leases/${f.lease.id}/late-fee-policies`, {
    expectedRevision: 1,
    idempotencyKey: crypto.randomUUID(),
    effectiveOn: f.start,
    endsOn: null,
    leaseTermId: null,
    ruleBasis: "Lease Section 5(b)",
    gracePeriodDays: 5,
    calculationBasis: "unpaid_rent_at_grace_end",
    formulaKind: "fixed_flat",
    flatAmountMinor: 5000,
    percentageBps: null,
    dailyAmountMinor: null,
    maxAccrualDays: null,
    perPeriodCapMinor: null,
    perPeriodMinMinor: null,
    minimumUnpaidThresholdMinor: 0,
    roundingMode: "half_up",
    appliesToProratedPeriods: false,
    supersedesPolicyVersionId: null,
    notes: null,
    operatorConfirmed: true,
  });

  // Pause auto-assessment via lease-level waiver so manual assess recovery can be exercised directly
  await post(request, `/api/leases/${f.lease.id}/late-fee-waiver`, {
    expectedRevision: 2,
    idempotencyKey: crypto.randomUUID(),
    reason: "Manual assessment test setup",
    waiveOpenAssessments: false,
    internalNotes: null,
    confirmed: true,
  });

  await page.goto(`/leases/${f.lease.id}/details`);
  const lateFeesSection = page.getByRole("region", { name: "Late fees", exact: true });
  await expect(lateFeesSection).toBeVisible();

  // 1. Finding 7: Drop committed assess response -> reload page -> recover via Pending operation recovery
  let droppedOnce = false;
  await page.route(`**/api/leases/${f.lease.id}/late-fee-assessments`, async (route) => {
    if (route.request().method() === "POST" && !droppedOnce) {
      droppedOnce = true;
      await route.fetch();
      await route.abort("failed");
      return;
    }
    await route.continue();
  });

  await lateFeesSection.getByRole("button", { name: "Preview eligible late fees" }).click();
  await lateFeesSection.locator("summary", { hasText: "Eligible" }).first().click();
  await lateFeesSection
    .getByRole("button", { name: /Assess late fee/ })
    .first()
    .click();
  const assessForm = lateFeesSection.getByRole("form", { name: "Confirm late-fee assessment" });
  await assessForm.getByLabel("Confirm assessing this late fee (required)").check();
  await assessForm.getByRole("button", { name: "Confirm assess late fee" }).click();

  await expect(lateFeesSection).toContainText("Check committed outcome");

  // Reload page and confirm recovery banner persists and reconciles committed operation
  await page.reload();
  const recoveryBanner = lateFeesSection.getByRole("alert", {
    name: "Pending operation recovery",
  });
  await expect(recoveryBanner).toBeVisible();
  await recoveryBanner.getByRole("button", { name: "Check committed outcome" }).click();
  await expect(recoveryBanner).toHaveCount(0);

  // 2. Finding 9: Void and replace assessment -> fresh preview -> linked replacement
  const assessedSummary = lateFeesSection
    .locator('[aria-label="Assessed late fees"] summary')
    .first();
  await expect(assessedSummary).toContainText("Unpaid");
  await assessedSummary.click();
  await lateFeesSection.getByRole("button", { name: "Void and replace" }).click();
  const voidReplaceForm = lateFeesSection.getByRole("form", {
    name: "Void late-fee assessment",
  });
  await voidReplaceForm.getByLabel("Void reason (required)").fill("Recalculating replacement");
  await voidReplaceForm.getByLabel(/Confirm voiding/).check();
  await voidReplaceForm
    .getByRole("button", { name: "Confirm void and preview replacement" })
    .click();

  // Fresh replacement preview opens automatically with Confirm assess form
  await expect(lateFeesSection).toContainText("Replacing voided assessment");
  const replaceAssessForm = lateFeesSection.getByRole("form", {
    name: "Confirm late-fee assessment",
  });
  await replaceAssessForm.getByLabel("Confirm assessing this late fee (required)").check();
  await replaceAssessForm.getByRole("button", { name: "Confirm assess late fee" }).click();
  await expect(lateFeesSection).toContainText("Replaces voided assessment");

  // Finding 9: Assessment correction history links are navigable in both directions
  const replacementSummary = lateFeesSection
    .locator('[aria-label="Assessed late fees"] summary', { hasText: "Unpaid" })
    .first();
  await replacementSummary.click();
  const prevAssessmentLink = lateFeesSection.getByRole("link", { name: "Previous assessment" });
  await expect(prevAssessmentLink).toBeVisible();
  await prevAssessmentLink.click();
  await expect(page.getByRole("heading", { name: "Late-fee assessment" })).toBeVisible();
  const nextAssessmentLink = page.getByRole("link", { name: "Replacement assessment" });
  await expect(nextAssessmentLink).toBeVisible();
  await nextAssessmentLink.click();
  await expect(page.getByRole("link", { name: "Previous assessment" })).toBeVisible();

  // Navigate back to Lease Detail for receipt void/replace
  await page.goto(`/leases/${f.lease.id}/details`);
  await expect(lateFeesSection).toBeVisible();

  // 3. Finding 8: Standalone fee payment -> open receipt detail -> Void -> Record replacement -> verify links
  const activeSummary = lateFeesSection
    .locator('[aria-label="Assessed late fees"] summary', { hasText: "Unpaid" })
    .first();
  await activeSummary.click();
  await lateFeesSection.getByRole("button", { name: "Record late-fee payment" }).click();
  const payForm = lateFeesSection.getByRole("form", { name: "Record late-fee payment" });
  await payForm.getByLabel("Received date (required)").fill(f.today);
  await payForm.getByLabel("Amount USD (required)").fill("20.00");
  await payForm.getByRole("button", { name: "Save late-fee payment" }).click();

  await expect(lateFeesSection.locator('[aria-label="Assessed late fees"]')).toContainText(
    "Partially paid",
  );
  const receiptLink = lateFeesSection
    .locator('[aria-label="Assessed late fees"] a[href*="record=late_fee_receipt"]')
    .first();
  await receiptLink.click();

  const receiptActions = page.getByRole("region", { name: "Late-fee payment actions" });
  await expect(receiptActions).toBeVisible();
  await receiptActions.getByRole("button", { name: "Void late-fee payment" }).click();
  const voidReceiptForm = receiptActions.getByRole("form", { name: "Void late-fee payment" });
  await voidReceiptForm.getByLabel("Void reason (required)").fill("Wrong amount recorded");
  await voidReceiptForm.getByLabel("Confirm voiding this late-fee payment").check();
  await voidReceiptForm.getByRole("button", { name: "Confirm void payment" }).click();

  await receiptActions.getByRole("button", { name: "Record replacement late-fee payment" }).click();
  const replaceReceiptForm = receiptActions.getByRole("form", { name: "Record late-fee payment" });
  await replaceReceiptForm.getByLabel("Received date (required)").fill(f.today);
  await replaceReceiptForm.getByLabel("Amount USD (required)").fill("25.00");
  await replaceReceiptForm.getByRole("button", { name: "Save late-fee payment" }).click();

  await expect(page.getByRole("link", { name: "Previous late-fee payment" })).toBeVisible();

  // 4. Findings 10 & 11: Record rent receipt workflow includes "Include assessed late fees"
  // Assert exactly 1 combined request and 0 rent-only requests!
  let combinedPosts = 0;
  let rentOnlyPosts = 0;
  await page.route(`**/api/leases/${f.lease.id}/combined-receipts`, async (route) => {
    if (route.request().method() === "POST") combinedPosts += 1;
    await route.continue();
  });
  await page.route("**/api/rent-receipts", async (route) => {
    if (route.request().method() === "POST") rentOnlyPosts += 1;
    await route.continue();
  });

  await page.goto(
    `/money?workflow=finance.rent_receipt.create&target=${f.lease.id}&child=${f.synced.items[0].id}`,
  );
  const includeSection = page.getByRole("region", { name: "Include assessed late fees" });
  await expect(includeSection).toBeVisible();
  await includeSection.getByLabel(/Include assessed late fees/).check();

  const combinedForm = page.getByRole("form", {
    name: "Record combined rent and late-fee payment",
  });
  await combinedForm.getByLabel("Received date (required)").fill(f.today);
  await combinedForm.getByLabel("Payment method (required)").selectOption("other");
  await combinedForm.getByLabel("Other payment method note (required)").fill("Money order #77");
  await combinedForm.getByRole("button", { name: "Save combined payment" }).click();
  await expect(combinedForm).toHaveCount(0);
  expect(combinedPosts).toBe(1);
  expect(rentOnlyPosts).toBe(0);
});

test("re-review regressions: duplicate-confirm edit/drop-reload recovery and preview pagination revision fence", async ({
  page,
  request,
}) => {
  const f = await createOverdueLeaseFixture(request);

  // Configure policy & assess two fees (exp1 and exp2) via API
  const pol = await post<Schemas["LateFeePolicyMutationResponse"]>(
    request,
    `/api/leases/${f.lease.id}/late-fee-policies`,
    {
      expectedRevision: 1,
      idempotencyKey: crypto.randomUUID(),
      effectiveOn: f.start,
      endsOn: null,
      leaseTermId: null,
      ruleBasis: "Lease Section 5(b)",
      gracePeriodDays: 5,
      calculationBasis: "unpaid_rent_at_grace_end",
      formulaKind: "fixed_flat",
      flatAmountMinor: 5000,
      percentageBps: null,
      dailyAmountMinor: null,
      maxAccrualDays: null,
      perPeriodCapMinor: null,
      perPeriodMinMinor: null,
      minimumUnpaidThresholdMinor: 0,
      roundingMode: "half_up",
      appliesToProratedPeriods: false,
      supersedesPolicyVersionId: null,
      notes: null,
      operatorConfirmed: true,
    },
  );
  const prev = await post<Schemas["LateFeePreviewResponse"]>(
    request,
    `/api/leases/${f.lease.id}/late-fees/preview`,
    { asOfDate: f.today, rentExpectationId: null, cursor: null },
  );
  const elig = prev.items.find((i) => i.eligibilityStatus === "eligible")!;
  const ass = await post<Schemas["LateFeeAssessmentMutationResponse"]>(
    request,
    `/api/leases/${f.lease.id}/late-fee-assessments`,
    {
      expectedRevision: pol.rentLedgerRevision,
      idempotencyKey: crypto.randomUUID(),
      rentExpectationId: elig.rentExpectationId,
      asOfDate: prev.asOfDate,
      previewFingerprint: elig.previewFingerprint!,
      operatorConfirmed: true,
      acknowledgeProcessingPayments: false,
      processingAcknowledgmentReason: null,
      internalNotes: null,
      replacesAssessmentId: null,
    },
  );

  // Record a $100.00 partial rent receipt on f.today so a second $100.00 combined rent payment triggers duplicate review!
  await post(request, "/api/rent-receipts", {
    leaseId: f.lease.id,
    expectedRevision: ass.rentLedgerRevision,
    idempotencyKey: crypto.randomUUID(),
    receivedOn: f.today,
    amountMinor: 10000,
    currencyCode: "USD",
    allocations: [{ expectationId: elig.rentExpectationId, amountMinor: 10000 }],
    paymentMethodKind: "check",
    paymentMethodLabel: null,
    maskedReference: null,
    otherPaymentMethodNote: null,
    receivedByPartyId: null,
    replacesReceiptId: null,
    notes: null,
    duplicateConfirmed: false,
    duplicateReason: null,
  });

  await page.goto(`/leases/${f.lease.id}/details`);
  const lateFeesSection = page.getByRole("region", { name: "Late fees", exact: true });
  await lateFeesSection
    .getByRole("button", { name: "Record combined rent + late-fee payment" })
    .click();
  const combinedForm = lateFeesSection.getByRole("form", {
    name: "Record combined rent and late-fee payment",
  });
  await combinedForm.getByLabel("Received date (required)").fill(f.today);
  await combinedForm.getByLabel("Rent period (required)").selectOption(elig.rentExpectationId);
  await combinedForm.getByLabel("Rent subtotal USD (required)").fill("100.00");
  await combinedForm.getByLabel("Late fee subtotal USD (required)").fill("20.00");
  await combinedForm.getByRole("button", { name: "Save combined payment" }).click();

  // Duplicate review panel appears!
  const dupPanel = combinedForm.getByRole("region", { name: "Duplicate payment review" });
  await expect(dupPanel).toBeVisible();

  // Finding 10 (edit away): changing rent subtotal to $150.00 clears duplicate review and succeeds without duplicateConfirmed!
  await combinedForm.getByLabel("Rent subtotal USD (required)").fill("150.00");
  await expect(dupPanel).toHaveCount(0);
  await combinedForm.getByRole("button", { name: "Save combined payment" }).click();
  await expect(combinedForm).toHaveCount(0);

  // Finding 7 & 10 (confirm real match + dropped response + reload recovery via OPS-001):
  await lateFeesSection
    .getByRole("button", { name: "Record combined rent + late-fee payment" })
    .click();
  const combinedForm2 = lateFeesSection.getByRole("form", {
    name: "Record combined rent and late-fee payment",
  });
  await combinedForm2.getByLabel("Received date (required)").fill(f.today);
  await combinedForm2.getByLabel("Rent period (required)").selectOption(elig.rentExpectationId);
  await combinedForm2.getByLabel("Rent subtotal USD (required)").fill("100.00");
  await combinedForm2.getByLabel("Late fee subtotal USD (required)").fill("10.00");
  await combinedForm2.getByRole("button", { name: "Save combined payment" }).click();

  const dupPanel2 = combinedForm2.getByRole("region", { name: "Duplicate payment review" });
  await expect(dupPanel2).toBeVisible();
  await dupPanel2.getByLabel("Confirm recording a separate rent payment").check();
  await dupPanel2.getByLabel("Duplicate confirmation reason (required)").fill("Second check today");

  // Drop the committed duplicate-confirmed combined payment response!
  let droppedDup = false;
  await page.route(`**/api/leases/${f.lease.id}/combined-receipts`, async (route) => {
    if (route.request().method() === "POST" && !droppedDup) {
      droppedDup = true;
      await route.fetch();
      await route.abort("failed");
      return;
    }
    await route.continue();
  });
  await combinedForm2.getByRole("button", { name: "Save combined payment" }).click();
  await expect(combinedForm2).toContainText("Check committed outcome");

  // Reload page and recover the EXACT duplicate-confirmed attempt from OPS-001!
  await page.reload();
  const banner = lateFeesSection.getByRole("alert", { name: "Pending operation recovery" });
  await expect(banner).toBeVisible();
  await banner.getByRole("button", { name: "Check committed outcome" }).click();
  await expect(banner).toHaveCount(0);
  // Balance should be $50 - $20 - $10 = $20.00 remaining!
  await expect(lateFeesSection.locator('[aria-label="Assessed late fees"]')).toContainText(
    "Remaining USD 20.00",
  );

  // Finding 12: Loading next preview page after a ledger revision change discards stale rows!
  let previewCalls = 0;
  await page.route(`**/api/leases/${f.lease.id}/late-fees/preview`, async (route) => {
    previewCalls += 1;
    const response = await route.fetch();
    const json = (await response.json()) as Schemas["LateFeePreviewResponse"];
    if (previewCalls === 1) {
      json.nextCursor = `${elig.dueOn}|${elig.rentExpectationId}`;
      await route.fulfill({ response, json });
      return;
    }
    json.rentLedgerRevision = json.rentLedgerRevision + 1;
    await route.fulfill({ response, json });
  });
  await lateFeesSection.getByRole("button", { name: "Preview eligible late fees" }).click();
  const loadMoreBtn = lateFeesSection.getByRole("button", { name: "Load next preview periods" });
  await expect(loadMoreBtn).toBeVisible();
  await loadMoreBtn.click();
  await expect(lateFeesSection).toContainText(
    "The rent ledger changed while loading more preview periods.",
  );
  await expect(loadMoreBtn).toHaveCount(0);
});

test("re-review 716f99a regressions: Money reload blocks duplicate combined submission before reconciliation and locks inputs during in-flight duplicate check", async ({
  page,
  request,
}) => {
  const f = await createOverdueLeaseFixture(request);

  const pol = await post<Schemas["LateFeePolicyMutationResponse"]>(
    request,
    `/api/leases/${f.lease.id}/late-fee-policies`,
    {
      expectedRevision: 1,
      idempotencyKey: crypto.randomUUID(),
      effectiveOn: f.start,
      endsOn: null,
      leaseTermId: null,
      ruleBasis: "Lease Section 5(b)",
      gracePeriodDays: 5,
      calculationBasis: "unpaid_rent_at_grace_end",
      formulaKind: "fixed_flat",
      flatAmountMinor: 5000,
      percentageBps: null,
      dailyAmountMinor: null,
      maxAccrualDays: null,
      perPeriodCapMinor: null,
      perPeriodMinMinor: null,
      minimumUnpaidThresholdMinor: 0,
      roundingMode: "half_up",
      appliesToProratedPeriods: false,
      supersedesPolicyVersionId: null,
      notes: null,
      operatorConfirmed: true,
    },
  );
  const prev = await post<Schemas["LateFeePreviewResponse"]>(
    request,
    `/api/leases/${f.lease.id}/late-fees/preview`,
    { asOfDate: f.today, rentExpectationId: null, cursor: null },
  );
  const elig = prev.items.find((i) => i.eligibilityStatus === "eligible")!;
  const ass = await post<Schemas["LateFeeAssessmentMutationResponse"]>(
    request,
    `/api/leases/${f.lease.id}/late-fee-assessments`,
    {
      expectedRevision: pol.rentLedgerRevision,
      idempotencyKey: crypto.randomUUID(),
      rentExpectationId: elig.rentExpectationId,
      asOfDate: prev.asOfDate,
      previewFingerprint: elig.previewFingerprint!,
      operatorConfirmed: true,
      acknowledgeProcessingPayments: false,
      processingAcknowledgmentReason: null,
      internalNotes: null,
      replacesAssessmentId: null,
    },
  );

  // Record a $100.00 partial rent receipt on f.today so $100.00 triggers a duplicate check.
  await post(request, "/api/rent-receipts", {
    leaseId: f.lease.id,
    expectedRevision: ass.rentLedgerRevision,
    idempotencyKey: crypto.randomUUID(),
    receivedOn: f.today,
    amountMinor: 10000,
    currencyCode: "USD",
    allocations: [{ expectationId: elig.rentExpectationId, amountMinor: 10000 }],
    paymentMethodKind: "check",
    paymentMethodLabel: null,
    maskedReference: null,
    otherPaymentMethodNote: null,
    receivedByPartyId: null,
    replacesReceiptId: null,
    notes: null,
    duplicateConfirmed: false,
    duplicateReason: null,
  });

  // Open Money -> Record rent receipt workflow
  const moneyUrl = `/money?workflow=finance.rent_receipt.create&target=${f.lease.id}&child=${elig.rentExpectationId}`;
  await page.goto(moneyUrl);
  await page.getByRole("checkbox", { name: /Include assessed late fees/ }).check();
  const combinedForm = page.getByRole("form", {
    name: "Record combined rent and late-fee payment",
  });

  // Finding 10: Hold the 409 duplicate response in flight and verify inputs are locked!
  let releaseDuplicate!: () => void;
  const dupHeld = new Promise<void>((resolve) => {
    releaseDuplicate = resolve;
  });
  let dupIntercepted = false;
  let combinedPostCount = 0;
  let dropCommitted = false;

  await page.route(`**/api/leases/${f.lease.id}/combined-receipts`, async (route) => {
    if (route.request().method() !== "POST") {
      await route.continue();
      return;
    }
    combinedPostCount += 1;
    if (!dupIntercepted) {
      dupIntercepted = true;
      await dupHeld;
      await route.continue();
      return;
    }
    if (dropCommitted) {
      dropCommitted = false;
      await route.fetch();
      await route.abort("failed");
      return;
    }
    await route.continue();
  });

  await combinedForm.getByLabel("Received date (required)").fill(f.today);
  await combinedForm.getByLabel("Rent subtotal USD (required)").fill("100.00");
  await combinedForm.getByLabel("Late fee subtotal USD (required)").fill("20.00");
  await combinedForm.getByRole("button", { name: "Save combined payment" }).click();

  // While duplicate check is in flight, matching inputs MUST be disabled!
  await expect(combinedForm.getByLabel("Rent subtotal USD (required)")).toBeDisabled();
  await expect(combinedForm.getByLabel("Received date (required)")).toBeDisabled();
  await expect(combinedForm.getByLabel("Rent period (required)")).toBeDisabled();

  // Release the 409 duplicate response -> duplicate panel appears -> edit away clears it
  releaseDuplicate();
  const dupPanel = combinedForm.getByRole("region", { name: "Duplicate payment review" });
  await expect(dupPanel).toBeVisible();
  await expect(combinedForm.getByLabel("Rent subtotal USD (required)")).toBeEnabled();
  await combinedForm.getByLabel("Rent subtotal USD (required)").fill("150.00");
  await expect(dupPanel).toHaveCount(0);

  // Finding 7: Now drop the committed combined payment response from Money, push it beyond page 1
  // with 52 newer OPS-001 drafts, reload Money, and verify resubmission is STILL blocked until reconciled!
  dropCommitted = true;
  await combinedForm.getByRole("button", { name: "Save combined payment" }).click();
  await expect(combinedForm).toContainText("Check committed outcome");
  expect(combinedPostCount).toBe(2);

  // Create 52 newer OPS-001 drafts so the unresolved combined payment is pushed onto page 2 (> 50 records)!
  for (let i = 0; i < 52; i += 1) {
    const resp = await request.put(`/api/operator/recovery/${crypto.randomUUID()}`, {
      data: {
        formKey: "task.create",
        schemaVersion: 1,
        sourceKind: null,
        sourceId: null,
        baseSourceRevision: null,
        expectedRevision: 0,
        idempotencyKey: crypto.randomUUID(),
        payload: { title: `Draft ${i + 1}` },
      },
    });
    expect(resp.ok(), await resp.text()).toBe(true);
  }

  // First verify a failed OPS-001 lookup fails closed and blocks submission!
  let failRecoveryLookup = true;
  await page.route("**/api/operator/recovery*", async (route) => {
    if (route.request().method() === "GET" && failRecoveryLookup) {
      await route.fulfill({
        status: 503,
        json: { detail: { code: "operator_unavailable", message: "Recovery list unavailable" } },
      });
      return;
    }
    await route.continue();
  });

  await page.reload();
  const unavailableBanner = page.getByRole("alert", { name: "Pending operation recovery" });
  await expect(unavailableBanner).toContainText("could not be verified");
  await page.getByRole("checkbox", { name: /Include assessed late fees/ }).check();
  const blockedForm = page.getByRole("form", {
    name: "Record combined rent and late-fee payment",
  });
  await expect(blockedForm.getByRole("button", { name: "Save combined payment" })).toBeDisabled();

  // Restore OPS-001 lookup -> exhausts page 1 + page 2 -> finds the unresolved combined payment on page 2!
  failRecoveryLookup = false;
  await unavailableBanner.getByRole("button", { name: "Retry recovery check" }).click();
  await expect(unavailableBanner).toContainText("finance.combined_receipt.create");
  await expect(blockedForm.getByRole("button", { name: "Save combined payment" })).toBeDisabled();
  await expect(blockedForm).toContainText("Check committed outcome");

  // Reconcile the original page-2 attempt via OPS-001 -> no duplicate POST is dispatched!
  await blockedForm.getByRole("button", { name: "Check committed outcome" }).click();
  await expect(unavailableBanner).toHaveCount(0);
  expect(combinedPostCount).toBe(2);
});
