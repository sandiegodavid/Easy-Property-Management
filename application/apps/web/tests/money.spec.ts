import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import type { components } from "@epm/contracts/generated";

type Schemas = components["schemas"];
test.use({ extraHTTPHeaders: { Origin: "http://127.0.0.1:18744" } });
async function post<T>(request: APIRequestContext, path: string, data: unknown): Promise<T> {
  const response = await request.post(path, { data });
  expect(response.ok(), await response.text()).toBe(true);
  return (await response.json()) as T;
}
async function get<T>(request: APIRequestContext, path: string): Promise<T> {
  const response = await request.get(path);
  expect(response.ok(), await response.text()).toBe(true);
  return (await response.json()) as T;
}
async function fixture(request: APIRequestContext, historicalRent = false) {
  await post(request, "/__test__/lease-clock", { days: 0 });
  const property = await post<Schemas["PropertyMutationResponse"]>(request, "/api/properties", {
    displayName: `Slice52 home ${crypto.randomUUID()}`,
    addressLine1: "10 Maple Street",
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
          displayName: `Slice52 owner ${crypto.randomUUID()}`,
        },
      },
    ],
  });
  const today = property.effectiveLocalDate,
    start = historicalRent
      ? new Date(Date.UTC(Number(today.slice(0, 4)), Number(today.slice(5, 7)) - 2, 1))
          .toISOString()
          .slice(0, 10)
      : `${today.slice(0, 7)}-01`;
  const through = new Date(Date.UTC(Number(today.slice(0, 4)), Number(today.slice(5, 7)) + 1, 0))
    .toISOString()
    .slice(0, 10);
  const tenant = await post<Schemas["TenantMutationResponse"]>(request, "/api/tenants", {
    partyKind: "individual",
    displayName: `Slice52 tenant ${crypto.randomUUID()}`,
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
  return { property, tenant, lease, today, start, through, owner: property.ownerships[0].partyId! };
}
async function schedule(request: APIRequestContext, f: Awaited<ReturnType<typeof fixture>>) {
  return post<Schemas["SynchronizeResponse"]>(
    request,
    `/api/leases/${f.lease.id}/rent-expectations/synchronize`,
    {
      expectedRevision: 0,
      idempotencyKey: crypto.randomUUID(),
      leaseTermId: f.lease.terms[0].id,
      throughOn: f.through,
      scheduleAnchorOn: f.start,
    },
  );
}
async function save(page: Page, title: string) {
  await page.getByRole("button", { name: `Save ${title.toLowerCase()}`, exact: true }).click();
  await expect(page.getByRole("region", { name: "Committed result" })).toBeVisible();
  await expect(
    page.getByText("This is the original committed response.", { exact: true }),
  ).toBeVisible();
}
async function expense(request: APIRequestContext, f: Awaited<ReturnType<typeof fixture>>) {
  const categories = await get<
    Schemas["app__modules__finance__api__expense_router__CategoryResponse"][]
  >(request, "/api/expense-categories");
  return post<Schemas["ExpenseMutationResponse"]>(request, "/api/expenses", {
    expectedRevision: 0,
    idempotencyKey: crypto.randomUUID(),
    propertyId: f.property.id,
    categoryId: categories[0].id,
    payeeName: "Plumber",
    paidByKind: "local_operator",
    paidOn: f.today,
    amount: "120.01",
    currencyCode: "USD",
    description: "Actual paid repair",
  });
}
async function ownerReport(
  request: APIRequestContext,
  f: Awaited<ReturnType<typeof fixture>>,
  amount = 40000,
) {
  return post<Schemas["OwnerRentReportMutationResponse"]>(request, "/api/owner-rent-reports", {
    expectedRevision: 0,
    idempotencyKey: crypto.randomUUID(),
    leaseId: f.lease.id,
    ownerPartyId: f.owner,
    receivedOn: f.today,
    amountMinor: amount,
    paymentMethodKind: "bank_transfer",
    reportedAtUtc: new Date().toISOString(),
  });
}
async function upload(request: APIRequestContext, entityType: string, id: string) {
  const response = await request.post("/api/files", {
    multipart: {
      entity_type: entityType,
      entity_id: id,
      purpose: "supporting_document",
      idempotency_key: crypto.randomUUID(),
      file: {
        name: "payment.txt",
        mimeType: "text/plain",
        buffer: Buffer.from("Retained payment evidence"),
      },
    },
  });
  expect(response.ok(), await response.text()).toBe(true);
}

test("rent synchronization and a partial receipt keep allocations and remaining balance visible", async ({
  page,
  request,
}) => {
  const f = await fixture(request);
  await page.goto(`/money?workflow=finance.rent_expectation.synchronize&target=${f.lease.id}`);
  await page.getByLabel("Lease term id (required)").selectOption(f.lease.terms[0].id);
  await page.getByLabel("Through on (required)").fill(f.through);
  await page.getByLabel("Schedule anchor on", { exact: true }).fill(f.start);
  await save(page, "Synchronize rent schedule");
  const expectations = await get<Schemas["ExpectationPageResponse"]>(
    request,
    `/api/rent-expectations?leaseId=${f.lease.id}`,
  );
  const expectation = expectations.items.find((item) => item.periodStartsOn === f.start)!;
  await page.goto(`/money?record=expectation&id=${expectation.id}`);
  await expect(page.getByText("USD 1000.00", { exact: true }).first()).toBeVisible();
  await page.getByText("Rent ledger actions", { exact: true }).click();
  await page.getByRole("link", { name: "Record rent receipt", exact: true }).click();
  await page.getByLabel("Received on (required)").fill(f.today);
  await page.getByLabel("Payment method kind (required)").selectOption("cash");
  await page.getByLabel("Amount minor (required)").nth(0).fill("40000");
  await page.getByLabel("Amount minor (required)").nth(1).fill("40000");
  await save(page, "Record rent receipt");
  await page.goto(`/money?record=expectation&id=${expectation.id}`);
  await expect(page.getByText("USD 600.00", { exact: true })).toBeVisible();
  const receipts = await get<Schemas["ReceiptPageResponse"]>(
    request,
    `/api/rent-receipts?leaseId=${f.lease.id}`,
  );
  expect(receipts.items).toHaveLength(1);
  expect(receipts.items[0].allocations[0].amountMinor).toBe(40000);
});

test("stale rent-ledger input is retained for explicit current-source review", async ({
  page,
  request,
}) => {
  const f = await fixture(request, true),
    synced = await schedule(request, f),
    expectation = synced.items.find((item) => item.periodEndsOn < f.today)!;
  await page.goto(
    `/money?workflow=finance.rent_expectation.timeliness_review&target=${f.lease.id}&child=${expectation.id}`,
  );
  await page.getByLabel("Decision (required)").selectOption("mark_missed");
  await page.getByLabel("Reason (required)").fill("Operator reviewed missed payment");
  await page.getByLabel("I confirm this lifecycle change", { exact: true }).check();
  await post(request, `/api/leases/${f.lease.id}/rent-expectations/synchronize`, {
    expectedRevision: 1,
    idempotencyKey: crypto.randomUUID(),
    leaseTermId: f.lease.terms[0].id,
    throughOn: f.through,
  });
  // A new receipt changes the ledger even when the schedule synchronization is a no-op.
  await post(request, "/api/rent-receipts", {
    expectedRevision: 1,
    idempotencyKey: crypto.randomUUID(),
    leaseId: f.lease.id,
    receivedOn: f.today,
    amountMinor: 100,
    currencyCode: "USD",
    paymentMethodKind: "cash",
    allocations: [
      {
        expectationId: synced.items.find((item) => item.id !== expectation.id)!.id,
        amountMinor: 100,
      },
    ],
  });
  await page.getByRole("button", { name: "Save review rent timeliness", exact: true }).click();
  await expect(page.getByRole("alert").first()).toBeVisible();
  await expect(page.getByLabel("Reason (required)")).toHaveValue(
    "Operator reviewed missed payment",
  );
  await page.getByRole("button", { name: "Review current source", exact: true }).click();
  await page.getByRole("button", { name: "Keep my edits with this reviewed revision" }).click();
  await save(page, "Review rent timeliness");
});

test("lost expense response reconciles once and evidence failure leaves spending committed", async ({
  page,
  request,
}) => {
  const f = await fixture(request),
    categories = await get<
      Schemas["app__modules__finance__api__expense_router__CategoryResponse"][]
    >(request, "/api/expense-categories");
  await page.goto(`/money?workflow=finance.expense.create&propertyId=${f.property.id}`);
  await page.getByLabel("Category id (required)").selectOption(categories[0].id);
  await page.getByLabel("Payee name", { exact: true }).fill("Receipt plumber");
  await page.getByLabel("Paid on (required)").fill(f.today);
  await page.getByLabel("Amount (required)").fill("120.01");
  await page.getByLabel("Description (required)").fill("Paid repair");
  let calls = 0;
  await page.route("**/api/expenses", async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    calls++;
    await route.fetch();
    await route.abort("failed");
  });
  await page.getByRole("button", { name: "Save record paid expense", exact: true }).click();
  await expect(page.getByRole("button", { name: "Check original result" })).toBeVisible();
  await page.goto("/settings/recovery");
  await page.getByRole("link", { name: "Resume finance.expense.create", exact: true }).click();
  await page.getByRole("button", { name: "Check original result" }).click();
  await expect(page.getByText("This is the original committed response.")).toBeVisible();
  expect(calls).toBe(1);
  const expenses = await get<Schemas["ExpensePageResponse"]>(
    request,
    `/api/expenses?propertyId=${f.property.id}`,
  );
  expect(expenses.items).toHaveLength(1);
  await page.goto(
    `/money?workflow=file.upload&entityType=expense&entityId=${expenses.items[0].id}`,
  );
  await page.getByLabel("Evidence file (required)").setInputFiles({
    name: "proof.txt",
    mimeType: "text/plain",
    buffer: Buffer.from("Paid proof"),
  });
  await page.route("**/api/files", (route) =>
    route.fulfill({
      status: 503,
      json: {
        detail: {
          code: "file_provider_unavailable",
          message: "Storage unavailable; expense is still recorded",
        },
      },
    }),
  );
  await page.getByRole("button", { name: "Save attach supporting evidence", exact: true }).click();
  await expect(page.getByRole("alert").first()).toBeVisible();
  expect(
    (
      await get<Schemas["ExpensePageResponse"]>(
        request,
        `/api/expenses?propertyId=${f.property.id}`,
      )
    ).items,
  ).toHaveLength(1);
});

test("expense no-op, refunds and explicit void/replacement retain original history", async ({
  page,
  request,
}) => {
  const f = await fixture(request),
    item = await expense(request, f);
  await page.goto(`/money?workflow=finance.expense.patch&target=${item.id}`);
  // An explicit nullable notes field is a business no-op and still has an immutable receipt.
  await page.getByLabel("Clear notes", { exact: true }).check();
  await save(page, "Edit expense context");
  const noop = await get<Schemas["ExpenseResponse"]>(request, `/api/expenses/${item.id}`);
  expect(noop.expenseRevision).toBe(item.expenseRevision);
  expect(noop.updatedAt).toBe(item.updatedAt);
  await page.goto(`/money?workflow=finance.expense_refund.create&target=${item.id}`);
  await page.getByLabel("Received on (required)").fill(f.today);
  await page.getByLabel("Amount (required)").fill("20.01");
  await page.getByLabel("Currency code (required)").fill("USD");
  await save(page, "Record expense refund");
  const updated = await get<Schemas["ExpenseResponse"]>(request, `/api/expenses/${item.id}`);
  expect(updated.netAmount).toBe("100.00");
  await page.goto(
    `/money?workflow=finance.expense_refund.void&target=${item.id}&child=${updated.refunds[0].id}`,
  );
  await page.getByLabel("Reason (required)").fill("Refund correction");
  await page.getByLabel("I confirm this lifecycle change", { exact: true }).check();
  await save(page, "Void expense refund");
  await page.goto(`/money?workflow=finance.expense.void&target=${item.id}`);
  await page.getByLabel("Reason (required)").fill("Spending correction");
  await page.getByLabel("I confirm this lifecycle change", { exact: true }).check();
  await save(page, "Void expense");
  await page.goto(`/money?record=expense&id=${item.id}`);
  await expect(page.getByRole("link", { name: "Record replacement expense" })).toBeVisible();
  await expect(page.getByRole("region", { name: "Refunds", exact: true })).toContainText(
    "Refund correction",
  );
});

test("Expense category create, edit, archive and restore use the catalog receipts", async ({
  page,
}) => {
  const name = `Slice52 category ${crypto.randomUUID()}`;
  await page.goto("/money?workflow=finance.expense_category.create");
  await page.getByLabel("Display name (required)").fill(name);
  await save(page, "Create expense category");
  await page.getByRole("link", { name: "Open current money record", exact: true }).click();
  await page.getByText("Actions", { exact: true }).click();
  await page.getByRole("link", { name: "Edit expense category", exact: true }).click();
  await page.getByLabel("Description", { exact: true }).fill("Current category description");
  await save(page, "Edit expense category");
  await page.getByRole("link", { name: "Open current money record", exact: true }).click();
  await page.getByText("Actions", { exact: true }).click();
  await page.getByRole("link", { name: "Archive expense category", exact: true }).click();
  await page.getByLabel("Reason (required)").fill("Unused category");
  await page.getByLabel("I confirm this lifecycle change", { exact: true }).check();
  await save(page, "Archive expense category");
  await page.getByRole("link", { name: "Open current money record", exact: true }).click();
  await page.getByText("Actions", { exact: true }).click();
  await page.getByRole("link", { name: "Restore expense category", exact: true }).click();
  await page.getByLabel("Reason (required)").fill("Category needed again");
  await page.getByLabel("I confirm this lifecycle change", { exact: true }).check();
  await save(page, "Restore expense category");
});

for (const mode of ["existing", "create"] as const)
  test(`owner report ${mode} verification uses one Finance receipt and explicit allocations`, async ({
    page,
    request,
  }) => {
    const f = await fixture(request),
      synced = await schedule(request, f),
      report = await ownerReport(request, f);
    await upload(request, "owner_rent_report", report.id);
    let receipt: Schemas["app__modules__finance__api__router__ReceiptMutationResponse"] | undefined;
    if (mode === "existing")
      receipt = await post(request, "/api/rent-receipts", {
        expectedRevision: 1,
        idempotencyKey: crypto.randomUUID(),
        leaseId: f.lease.id,
        receivedOn: f.today,
        amountMinor: 40000,
        currencyCode: "USD",
        receivedByPartyId: f.owner,
        paymentMethodKind: "bank_transfer",
        allocations: [{ expectationId: synced.items[0].id, amountMinor: 40000 }],
      });
    await page.goto(`/money?workflow=owner_rent_report.verify&target=${report.id}`);
    await page
      .getByLabel(
        mode === "existing"
          ? "Adopt an existing compatible receipt"
          : "Create a receipt with explicit allocations",
      )
      .check();
    if (receipt)
      await page
        .getByRole("combobox", { name: "Existing receipt id", exact: true })
        .selectOption(receipt.id);
    else {
      await page.getByLabel("Expectation id (required)").selectOption(synced.items[0].id);
      await page.getByLabel("Amount minor (required)").fill("40000");
    }
    await page.getByLabel("Review note (required)").fill("Verified exact payment evidence");
    await page.getByLabel("I confirm this lifecycle change", { exact: true }).check();
    await save(page, "Verify owner rent report");
    const final = await get<Schemas["OwnerRentReportResponse"]>(
      request,
      `/api/owner-rent-reports/${report.id}`,
    );
    expect(final.status).toBe("verified");
    expect(final.financiallyEffective).toBe(true);
    const receipts = await get<Schemas["ReceiptPageResponse"]>(
      request,
      `/api/rent-receipts?leaseId=${f.lease.id}`,
    );
    expect(receipts.items).toHaveLength(1);
    expect(receipts.items[0].id).toBe(final.verifiedReceiptId);
  });

test("owner report creation, correction and rejection remain claims rather than income", async ({
  page,
  request,
}) => {
  const f = await fixture(request);
  await page.goto(`/money?workflow=owner_rent_report.create&leaseId=${f.lease.id}`);
  await page.getByLabel("Owner party id (required)").fill(f.owner);
  await page.getByLabel("Received on (required)").fill(f.today);
  await page.getByLabel("Amount minor (required)").fill("12345");
  await page.getByLabel("Payment method kind (required)").selectOption("cash");
  await page.getByLabel("Reported at utc (required)").fill(new Date().toISOString());
  await save(page, "Record owner rent report");
  const items = await get<Schemas["OwnerRentReportPageResponse"]>(
    request,
    `/api/owner-rent-reports?leaseId=${f.lease.id}`,
  );
  expect(items.items).toHaveLength(1);
  await page.goto(`/money?workflow=owner_rent_report.patch&target=${items.items[0].id}`);
  await page.getByLabel("Source note", { exact: true }).fill("Corrected source note");
  await save(page, "Edit owner rent report");
  await page.goto(`/money?workflow=owner_rent_report.reject&target=${items.items[0].id}`);
  await page.getByLabel("Reason (required)").fill("Owner withdrew the claim");
  await page.getByLabel("I confirm this lifecycle change", { exact: true }).check();
  await save(page, "Reject owner rent report");
  expect(
    (await get<Schemas["ReceiptPageResponse"]>(request, `/api/rent-receipts?leaseId=${f.lease.id}`))
      .items,
  ).toHaveLength(0);
});

test("prepaid check scheduling, deposit and return distinguish scheduled money from received income", async ({
  page,
  request,
}) => {
  const f = await fixture(request),
    synced = await schedule(request, f),
    expectation = synced.items.find((item) => item.periodStartsOn === f.start)!;
  await page.goto(
    `/money?workflow=finance.prepaid_check.create&target=${f.lease.id}&child=${expectation.id}`,
  );
  await page.getByLabel("Payer party id (required)").selectOption(f.tenant.id);
  const received = new Date(Date.parse(`${f.today}T12:00:00Z`) - 86400000)
    .toISOString()
    .slice(0, 10);
  await page.getByLabel("Received on (required)").fill(received);
  await page.getByLabel("Check dated on (required)").fill(f.today);
  await save(page, "Schedule prepaid check");
  const checks = await get<Schemas["PrepaidCheckPageResponse"]>(
    request,
    `/api/prepaid-checks?leaseId=${f.lease.id}`,
  );
  expect(checks.items).toHaveLength(1);
  expect(
    (await get<Schemas["ReceiptPageResponse"]>(request, `/api/rent-receipts?leaseId=${f.lease.id}`))
      .items,
  ).toHaveLength(0);
  await page.goto(
    `/money?workflow=finance.prepaid_check.deposit&target=${f.lease.id}&child=${checks.items[0].id}`,
  );
  await page.getByLabel("I confirm this lifecycle change", { exact: true }).check();
  await save(page, "Deposit prepaid check");
  expect(
    (await get<Schemas["ReceiptPageResponse"]>(request, `/api/rent-receipts?leaseId=${f.lease.id}`))
      .items,
  ).toHaveLength(1);
  await page.goto(
    `/money?workflow=finance.prepaid_check.return&target=${f.lease.id}&child=${checks.items[0].id}`,
  );
  await page.getByLabel("Reason (required)").fill("Check returned unpaid");
  await page.getByLabel("Returned on (required)").fill(f.today);
  await page.getByLabel("I confirm this lifecycle change", { exact: true }).check();
  await save(page, "Return prepaid check");
  const returned = await get<Schemas["PrepaidCheckResponse"]>(
    request,
    `/api/prepaid-checks/${checks.items[0].id}`,
  );
  expect(returned.status).toBe("returned");
  expect(returned.receipt?.voidedAt).toBeTruthy();
});

test("deposit account receipt and zero-dollar settlement approval/completion are separate actions", async ({
  page,
  request,
}) => {
  const f = await fixture(request);
  await page.goto(`/money?workflow=finance.deposit_account.create&leaseId=${f.lease.id}`);
  await page.getByLabel("Lease term id (required)").selectOption(f.lease.terms[0].id);
  await save(page, "Create deposit account");
  const account = await get<Schemas["DepositResponse"]>(
    request,
    `/api/leases/${f.lease.id}/security-deposit`,
  );
  await page.goto(`/money?workflow=finance.deposit_settlement.create&target=${account.id}`);
  await page.getByLabel("Settlement due on (required)").fill(f.through);
  await page.getByLabel("Eligibility override confirmed", { exact: true }).check();
  await page
    .getByLabel("Eligibility override reason", { exact: true })
    .fill("Explicit test settlement before move-out");
  await save(page, "Prepare deposit settlement");
  const updated = await get<Schemas["DepositResponse"]>(
    request,
    `/api/security-deposits/${account.id}`,
  );
  expect(updated.settlementId).toBeTruthy();
  await page.goto(
    `/money?workflow=finance.deposit_settlement.approve&target=${account.id}&child=${updated.settlementId}`,
  );
  await page.getByLabel("I confirm this lifecycle change", { exact: true }).check();
  await page.getByLabel("Zero dollar closure confirmed", { exact: true }).check();
  await save(page, "Approve deposit settlement");
  await page.goto(
    `/money?workflow=finance.deposit_settlement.complete&target=${account.id}&child=${updated.settlementId}`,
  );
  await page.getByLabel("I confirm this lifecycle change", { exact: true }).check();
  await save(page, "Complete deposit settlement");
  expect(
    (
      await get<Schemas["SettlementResponse"]>(
        request,
        `/api/security-deposit-settlements/${updated.settlementId}`,
      )
    ).status,
  ).toBe("completed");
});

test("settlement evidence, child deletion recovery and partial refunds preserve held-money arithmetic", async ({
  page,
  request,
}) => {
  const f = await fixture(request),
    paid = await expense(request, f);
  const account = await post<Schemas["DepositMutationResponse"]>(
    request,
    `/api/leases/${f.lease.id}/security-deposit`,
    { expectedRevision: 0, idempotencyKey: crypto.randomUUID(), leaseTermId: f.lease.terms[0].id },
  );
  await page.goto(`/money?workflow=finance.deposit_receipt.create&target=${account.id}`);
  await page.getByLabel("Amount (required)").fill("1000.00");
  await page.getByLabel("Received on (required)").fill(f.today);
  await page.getByLabel("Received from party id", { exact: true }).fill(f.tenant.id);
  await save(page, "Record deposit receipt");
  await page.goto(`/money?workflow=finance.deposit_settlement.create&target=${account.id}`);
  await page.getByLabel("Settlement due on (required)").fill(f.through);
  await page.getByLabel("Eligibility override confirmed", { exact: true }).check();
  await page
    .getByLabel("Eligibility override reason", { exact: true })
    .fill("Operator requested early settlement review");
  await save(page, "Prepare deposit settlement");
  const updated = await get<Schemas["DepositResponse"]>(
      request,
      `/api/security-deposits/${account.id}`,
    ),
    settlementId = updated.settlementId!;
  await page.goto(
    `/money?workflow=finance.deposit_deduction.create&target=${account.id}&child=${settlementId}`,
  );
  await page.getByLabel("Category (required)").selectOption("damage");
  await page.getByLabel("Amount (required)").fill("10.00");
  await page.getByLabel("Description (required)").fill("Repair deduction");
  await page
    .getByLabel("Rationale (required)")
    .fill("Operator-selected liability supported by paid repair");
  await save(page, "Add settlement deduction");
  let settlement = await get<Schemas["SettlementResponse"]>(
    request,
    `/api/security-deposit-settlements/${settlementId}`,
  );
  await page.goto(
    `/money?workflow=finance.deposit_deduction_source.add&target=${account.id}&child=${settlement.deductions[0].id}`,
  );
  await page.getByLabel("Source kind (required)").selectOption("expense");
  await page.getByLabel("Source id (required)").fill(paid.id);
  await save(page, "Add deduction source");
  await page.goto(
    `/money?workflow=finance.deposit_credit.create&target=${account.id}&child=${settlementId}`,
  );
  await page.getByLabel("Kind (required)").selectOption("other");
  await page.getByLabel("Amount (required)").fill("5.00");
  await page.getByLabel("Description (required)").fill("Draft adjustment");
  await save(page, "Add settlement credit");
  settlement = await get(request, `/api/security-deposit-settlements/${settlementId}`);
  const creditId = settlement.credits[0].id;
  await page.goto(
    `/money?workflow=finance.deposit_credit.update&target=${account.id}&child=${creditId}`,
  );
  await page.getByLabel("Amount (required)").fill("6.00");
  await save(page, "Edit settlement credit");
  await page.goto(
    `/money?workflow=finance.deposit_credit.delete&target=${account.id}&child=${creditId}`,
  );
  await page.getByLabel("I confirm deletion of this draft settlement child").check();
  let calls = 0;
  await page.route(`**/api/security-deposit-credits/${creditId}`, async (route) => {
    calls++;
    await route.fetch();
    await route.abort("failed");
  });
  await page.getByRole("button", { name: "Save delete settlement credit", exact: true }).click();
  await expect(page.getByRole("button", { name: "Check original result" })).toBeVisible();
  await page.goto("/settings/recovery");
  await page
    .getByRole("link", { name: "Resume finance.deposit_credit.delete", exact: true })
    .click();
  await page.getByRole("button", { name: "Check original result" }).click();
  await expect(page.getByText("This is the original committed response.")).toBeVisible();
  expect(calls).toBe(1);
  await page.goto(
    `/money?workflow=finance.deposit_settlement.approve&target=${account.id}&child=${settlementId}`,
  );
  await page.getByLabel("I confirm this lifecycle change", { exact: true }).check();
  await save(page, "Approve deposit settlement");
  settlement = await get(request, `/api/security-deposit-settlements/${settlementId}`);
  expect(settlement.refundDue).toBe("990.00");
  for (const amount of ["400.00", "590.00"]) {
    await page.goto(
      `/money?workflow=finance.deposit_refund.create&target=${account.id}&child=${settlementId}`,
    );
    await page.getByLabel("Recipient party id (required)").fill(f.tenant.id);
    await page.getByLabel("Paid on (required)").fill(f.today);
    await page.getByLabel("Amount (required)").fill(amount);
    await save(page, "Record deposit refund");
  }
  await page.goto(
    `/money?workflow=finance.deposit_settlement.complete&target=${account.id}&child=${settlementId}`,
  );
  await page.getByLabel("I confirm this lifecycle change", { exact: true }).check();
  await save(page, "Complete deposit settlement");
  settlement = await get(request, `/api/security-deposit-settlements/${settlementId}`);
  expect(settlement.status).toBe("completed");
  expect(settlement.refunds.map((item) => item.amount).sort()).toEqual(["400.00", "590.00"]);
});

test("scheduled check replacement and void preserve lineage without creating income", async ({
  page,
  request,
}) => {
  const f = await fixture(request),
    synced = await schedule(request, f),
    checkOn = new Date(Date.parse(`${f.today}T12:00:00Z`) + 86400000).toISOString().slice(0, 10);
  const check = await post<Schemas["PrepaidCheckMutationResponse"]>(
    request,
    "/api/prepaid-checks",
    {
      expectedRevision: 1,
      idempotencyKey: crypto.randomUUID(),
      expectationId: synced.items[0].id,
      payerPartyId: f.tenant.id,
      receivedOn: f.today,
      checkDatedOn: checkOn,
    },
  );
  await page.goto(
    `/money?workflow=finance.prepaid_check.void&target=${f.lease.id}&child=${check.id}`,
  );
  await page.getByLabel("Reason (required)").fill("Original paper check withdrawn");
  await page.getByLabel("I confirm this lifecycle change", { exact: true }).check();
  await save(page, "Void prepaid check");
  await page.goto(
    `/money?workflow=finance.prepaid_check.replace&target=${f.lease.id}&child=${check.id}`,
  );
  await page.getByLabel("Expectation id (required)").selectOption(check.expectationId);
  await page.getByLabel("Payer party id (required)").selectOption(f.tenant.id);
  await page.getByLabel("Received on (required)").fill(f.today);
  await page.getByLabel("Check dated on (required)").fill(checkOn);
  await page.getByLabel("Masked reference", { exact: true }).fill("****1234");
  await page.getByLabel("Reason (required)").fill("Replacement paper check");
  await page.getByLabel("I confirm this lifecycle change", { exact: true }).check();
  await save(page, "Replace prepaid check");
  const original = await get<Schemas["PrepaidCheckResponse"]>(
    request,
    `/api/prepaid-checks/${check.id}`,
  );
  expect(original.status).toBe("replaced");
  await page.goto(
    `/money?workflow=finance.prepaid_check.void&target=${f.lease.id}&child=${original.replacedByPrepaidCheckId}`,
  );
  await page.getByLabel("Reason (required)").fill("Never deposited");
  await page.getByLabel("I confirm this lifecycle change", { exact: true }).check();
  await save(page, "Void prepaid check");
  expect(
    (await get<Schemas["ReceiptPageResponse"]>(request, `/api/rent-receipts?leaseId=${f.lease.id}`))
      .items,
  ).toHaveLength(0);
});

test("rent receipt correction voids the predecessor and preserves one current received payment", async ({
  page,
  request,
}) => {
  const f = await fixture(request),
    synced = await schedule(request, f),
    expectation = synced.items[0];
  const receipt = await post<
    Schemas["app__modules__finance__api__router__ReceiptMutationResponse"]
  >(request, "/api/rent-receipts", {
    expectedRevision: 1,
    idempotencyKey: crypto.randomUUID(),
    leaseId: f.lease.id,
    receivedOn: f.today,
    amountMinor: 10000,
    currencyCode: "USD",
    paymentMethodKind: "cash",
    allocations: [{ expectationId: expectation.id, amountMinor: 10000 }],
  });
  await page.goto(
    `/money?workflow=finance.rent_receipt.void&target=${f.lease.id}&child=${receipt.id}`,
  );
  await page.getByLabel("Void reason (required)").fill("Incorrect recorded amount");
  await page.getByLabel("I confirm this lifecycle change", { exact: true }).check();
  await save(page, "Void rent receipt");
  await page.goto(
    `/money?workflow=finance.rent_receipt.create&target=${f.lease.id}&child=${expectation.id}&replacesReceiptId=${receipt.id}`,
  );
  await page.getByLabel("Received on (required)").fill(f.today);
  await page.getByLabel("Payment method kind (required)").selectOption("cash");
  await page.getByLabel("Amount minor (required)").nth(0).fill("20000");
  await page.getByLabel("Amount minor (required)").nth(1).fill("20000");
  await save(page, "Record rent receipt");
  const current = await get<Schemas["ReceiptPageResponse"]>(
    request,
    `/api/rent-receipts?leaseId=${f.lease.id}`,
  );
  expect(current.items).toHaveLength(1);
  expect(current.items[0].replacesReceiptId).toBe(receipt.id);
  const prior = await get<Schemas["app__modules__finance__api__router__ReceiptResponse"]>(
    request,
    `/api/rent-receipts/${receipt.id}`,
  );
  expect(prior.voidedAt).toBeTruthy();
});

test("owner verification refreshes both revisions after a stale ledger without losing the review note", async ({
  page,
  request,
}) => {
  const f = await fixture(request),
    synced = await schedule(request, f),
    report = await ownerReport(request, f);
  await upload(request, "owner_rent_report", report.id);
  await page.goto(`/money?workflow=owner_rent_report.verify&target=${report.id}`);
  await page.getByLabel("Create a receipt with explicit allocations").check();
  await page.getByLabel("Expectation id (required)").selectOption(synced.items[0].id);
  await page.getByLabel("Amount minor (required)").fill("40000");
  await page.getByLabel("Review note (required)").fill("Reviewed original report");
  await page.getByLabel("I confirm this lifecycle change", { exact: true }).check();
  await post(request, "/api/rent-receipts", {
    expectedRevision: 1,
    idempotencyKey: crypto.randomUUID(),
    leaseId: f.lease.id,
    receivedOn: f.today,
    amountMinor: 100,
    currencyCode: "USD",
    paymentMethodKind: "cash",
    allocations: [{ expectationId: synced.items[0].id, amountMinor: 100 }],
  });
  await page.getByRole("button", { name: "Save verify owner rent report", exact: true }).click();
  await expect(page.getByRole("alert").first()).toBeVisible();
  await expect(page.getByLabel("Review note (required)")).toHaveValue("Reviewed original report");
  await page.getByRole("button", { name: "Review current source", exact: true }).click();
  await page.getByRole("button", { name: "Keep my edits with this reviewed revision" }).click();
  await save(page, "Verify owner rent report");
  const final = await get<Schemas["OwnerRentReportResponse"]>(
    request,
    `/api/owner-rent-reports/${report.id}`,
  );
  expect(final.status).toBe("verified");
  expect(
    (await get<Schemas["ReceiptPageResponse"]>(request, `/api/rent-receipts?leaseId=${f.lease.id}`))
      .items,
  ).toHaveLength(2);
});

test("supporting evidence can be reselected after restart and metadata retains verified history", async ({
  page,
  request,
}) => {
  const f = await fixture(request),
    item = await expense(request, f);
  await page.goto(`/money?workflow=file.upload&entityType=expense&entityId=${item.id}`);
  const bytes = {
    name: "expense-proof.txt",
    mimeType: "text/plain",
    buffer: Buffer.from("Paid expense proof"),
  };
  await page.getByLabel("Evidence file (required)").setInputFiles(bytes);
  const savedResponse = page.waitForResponse(
    (response) =>
      response.request().method() === "PUT" &&
      response.url().includes("/api/operator/recovery/") &&
      response.ok(),
  );
  await page.getByRole("button", { name: "Save unfinished form" }).click();
  await expect(page.getByText("Draft saved · Command editing", { exact: true })).toBeVisible();
  const saved = (await (await savedResponse).json()) as Schemas["RecoveryResponse"];
  await page.goto("/settings/recovery");
  await page
    .getByRole("link", { name: "Resume file.upload", exact: true })
    .and(page.locator(`[href*="resume=${saved.id}"]`))
    .click();
  await page.getByLabel("Evidence file (required)").setInputFiles(bytes);
  await save(page, "Attach supporting evidence");
  await page.getByRole("link", { name: "Open current money record", exact: true }).click();
  await expect(page.getByRole("region", { name: "Evidence metadata", exact: true })).toContainText(
    "Verified at",
  );
  await expect(
    page.getByRole("link", { name: "Download expense-proof.txt", exact: true }),
  ).toBeVisible();
  const fileId = new URL(page.url()).searchParams.get("file")!;
  const metadata = await get<Schemas["FileMetadataResponse"]>(request, `/api/files/${fileId}`);
  await page.goto(`/money?record=expense&id=${item.id}`);
  await expect(page.getByRole("link", { name: "Download evidence", exact: true })).toBeVisible();
  await post(request, `/api/file-links/${metadata.links[0].id}/archive`, {
    expectedRevision: metadata.links[0].revision,
    idempotencyKey: crypto.randomUUID(),
    confirmed: true,
    reason: "Duplicate supporting evidence",
  });
  await page.goto(`/money?record=expense&id=${item.id}`);
  await expect(page.getByRole("link", { name: "Download evidence", exact: true })).toHaveCount(0);
  await page.getByText("Archived evidence history", { exact: true }).click();
  await expect(page.getByText(/Archived association: Duplicate supporting evidence/)).toBeVisible();
});

test("explicit-period reporting uses backend totals and source drill-down without row fan-out", async ({
  page,
  request,
}) => {
  const f = await fixture(request),
    item = await expense(request, f);
  let summaries = 0,
    details = 0;
  page.on("request", (request) => {
    if (request.url().includes("/api/money/properties")) summaries++;
    if (request.url().includes(`/api/expenses/${item.id}`)) details++;
  });
  await page.goto(`/money?tab=reporting&propertyId=${f.property.id}`);
  await expect(
    page.getByText("Choose an explicit inclusive date range to load reporting."),
  ).toBeVisible();
  expect(summaries).toBe(0);
  await page.getByLabel("Reporting from (required)").fill(f.today);
  await page.getByLabel("Reporting through (required)").fill(f.today);
  await page.getByRole("button", { name: "Show recorded totals" }).click();
  await expect(page.getByRole("region", { name: "operating", exact: true })).toContainText(
    "USD 120.01",
  );
  expect(summaries).toBe(1);
  expect(details).toBe(0);
  await page.getByRole("link", { name: "expensesPaid · USD 120.01", exact: true }).click();
  await expect(page.getByText("Backend total USD 120.01", { exact: false })).toBeVisible();
  await page.getByRole("link", { name: "Open contribution source", exact: true }).click();
  await expect(page.getByRole("region", { name: "Money record", exact: true })).toContainText(
    "Actual paid repair",
  );
  expect(details).toBe(1);
});

test("independent money read failure is explicit and reporting restart retains period and Property", async ({
  page,
  request,
}) => {
  const f = await fixture(request);
  await page.route("**/api/money/properties?**", (route) =>
    route.fulfill({
      status: 409,
      json: { detail: { code: "money_view_changed", message: "Money view changed" } },
    }),
  );
  await page.goto(
    `/money?tab=reporting&propertyId=${f.property.id}&fromOn=${f.today}&throughOn=${f.today}&cursor=obsolete`,
  );
  await expect(page.getByRole("alert")).toContainText("amounts have not been replaced with zero");
  await page.unroute("**/api/money/properties?**");
  await page.getByRole("button", { name: "Restart reporting with these filters" }).click();
  await expect(page).not.toHaveURL(/cursor=/);
  await expect(page).toHaveURL(new RegExp(`propertyId=${f.property.id}`));
  await expect(page).toHaveURL(new RegExp(`fromOn=${f.today}`));
  await expect(page.getByRole("region", { name: "operating", exact: true })).toBeVisible();
});
