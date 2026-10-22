import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import type { components } from "@epm/contracts/generated";
import axe from "axe-core";
import { formatDate } from "../src/shared/presentation";

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
    officialIds: [{ documentType: "passport", issuingCountry: "US", lastFour: "TEST" }],
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

test("failed Money directory read remains unavailable until an explicit successful retry", async ({
  page,
  request,
}) => {
  const f = await fixture(request);
  await schedule(request, f);
  let unavailable = true;
  await page.route("**/api/rent-expectations?*", (route) =>
    unavailable
      ? route.fulfill({
          status: 503,
          json: { detail: { code: "finance_unavailable", message: "Temporarily unavailable" } },
        })
      : route.continue(),
  );
  await page.goto(`/money?leaseId=${f.lease.id}`);
  await expect(page.getByRole("alert")).toContainText("Money information is unavailable");
  await expect(page.getByText("No records match these filters.", { exact: true })).toHaveCount(0);
  const records = page.getByRole("region", { name: "Rent records", exact: true });
  await expect(records.getByRole("link", { name: "Rent due", exact: true })).toHaveCount(0);
  await expect(records.getByText("USD 0.00", { exact: true })).toHaveCount(0);
  unavailable = false;
  await page.getByRole("button", { name: "Restart with these filters", exact: true }).click();
  await expect(page.getByRole("alert")).toHaveCount(0);
  await expect(page.getByRole("link", { name: "Rent due", exact: true }).first()).toBeVisible();
  await expect(page.getByText("USD 1,000.00", { exact: true }).first()).toBeVisible();
  await expect(page).toHaveURL(new RegExp(`leaseId=${f.lease.id}`));
});

test("money editing, category details, expenses and reporting use readable responsive sections", async ({
  page,
  request,
}, testInfo) => {
  const f = await fixture(request);
  const synced = await schedule(request, f);
  const paid = await expense(request, f);
  const cases = [
    {
      key: "category-create",
      url: "/money?workflow=finance.expense_category.create",
      region: "Create expense category",
    },
    {
      key: "category-edit",
      url: `/money?workflow=finance.expense_category.patch&target=${paid.categoryId}`,
      region: "Edit expense category",
    },
    {
      key: "category-detail",
      url: `/money?record=category&id=${paid.categoryId}`,
      region: "Money record",
    },
    { key: "expense-detail", url: `/money?record=expense&id=${paid.id}`, region: "Money record" },
    {
      key: "payment-create",
      url: `/money?workflow=finance.rent_receipt.create&target=${f.lease.id}&child=${synced.items[0].id}`,
      region: "Record rent receipt",
    },
    {
      key: "reporting",
      url: `/money?tab=reporting&fromOn=${f.today}&throughOn=${f.today}&propertyState=all&propertyId=${f.property.id}`,
      region: "Money reporting",
    },
  ];
  for (const item of cases) {
    await page.goto(item.url);
    const region = page.getByRole("region", { name: item.region, exact: true });
    await expect(region).toBeVisible();
    if (item.key === "reporting")
      await expect(
        region.getByRole("region", { name: "Rent and expenses", exact: true }),
      ).toBeVisible();
    if (item.key.startsWith("category-") && item.key !== "category-detail") {
      await expect(
        region.getByRole("region", { name: "Category details", exact: true }),
      ).toBeVisible();
      await expect(
        region.getByText("Displayed source revision:", { exact: false }),
      ).not.toBeVisible();
    }
    if (item.key === "payment-create") {
      for (const title of ["Payment received", "Payment method", "Apply payment to rent"])
        await expect(region.getByRole("region", { name: title, exact: true })).toBeVisible();
      await expect(region.getByLabel("Lease id (required)")).toHaveCount(0);
      await expect(
        region.getByText("Displayed source revision:", { exact: false }),
      ).not.toBeVisible();
    }
    if (item.key === "expense-detail") {
      await expect(
        region.getByRole("region", { name: "Expense summary", exact: true }),
      ).toContainText("Actual paid repair");
      await expect(
        region.getByRole("button", { name: "Record refund", exact: true }),
      ).toBeVisible();
      await expect(region.getByText(paid.id, { exact: true })).not.toBeVisible();
    }
    if (item.key === "category-detail")
      await expect(
        region.getByRole("button", { name: "Edit expense category", exact: true }),
      ).toBeVisible();
    for (const theme of ["light", "dark"]) {
      await page.evaluate((value) => {
        document.documentElement.dataset.theme = value;
      }, theme);
      for (const width of [1280, 390]) {
        await page.setViewportSize({ width, height: 900 });
        expect(await region.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(
          true,
        );
        await region.screenshot({ path: testInfo.outputPath(`${item.key}-${theme}-${width}.png`) });
      }
    }
    await page.evaluate(axe.source);
    expect(
      await page.evaluate(
        async (name) =>
          (
            await window.axe.run(`section[aria-label="${name}"]`, {
              runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21aa"] },
            })
          ).violations.map((item) => item.id),
        item.region,
      ),
    ).toEqual([]);
  }
});
test("property-scoped Money shows a named link back to property details", async ({
  page,
  request,
}) => {
  const { property } = await fixture(request);
  await page.goto(`/money?propertyId=${property.id}`);
  const context = page.getByRole("region", { name: "Property context", exact: true });
  await expect(context).toContainText(property.addressLine1);
  const link = context.getByRole("link", {
    name: property.displayName,
    exact: true,
  });
  await expect(link).toHaveAttribute("href", `/properties/${property.id}/overview`);
  await link.click();
  await expect(
    page.getByRole("heading", { name: property.displayName, exact: true }),
  ).toBeVisible();
  await page.goto("/money");
  await expect(page.getByRole("region", { name: "Property context", exact: true })).toHaveCount(0);
});

test("lease-filtered Money shows its property even without money records", async ({
  page,
  request,
}) => {
  const f = await fixture(request);
  await page.goto(`/money?leaseId=${f.lease.id}`);
  const context = page.getByRole("region", { name: "Property context", exact: true });
  await expect(
    context.getByRole("link", { name: f.property.displayName, exact: true }),
  ).toHaveAttribute("href", `/properties/${f.property.id}/overview`);
  await expect(context).toContainText(f.property.addressLine1);
  await expect(page.getByText("Showing this lease’s records.", { exact: false })).toBeVisible();
  await expect(page.getByText(`leaseId: ${f.lease.id}`, { exact: false })).toHaveCount(0);
  await page
    .getByRole("navigation", { name: "Money views" })
    .getByRole("link", { name: "Received rent", exact: true })
    .click();
  await expect(
    context.getByRole("link", { name: f.property.displayName, exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Remove lease filter", exact: true }).click();
  await expect(context).toHaveCount(0);
});

test("lease-filtered Money can retry unavailable property context without clearing its lease", async ({
  page,
  request,
}) => {
  const f = await fixture(request);
  let unavailable = true;
  await page.route("**/api/money/property-contexts?*", (route) =>
    unavailable
      ? route.fulfill({
          status: 503,
          contentType: "application/json",
          body: JSON.stringify({ detail: "Unavailable" }),
        })
      : route.continue(),
  );
  await page.goto(`/money?leaseId=${f.lease.id}`);
  const context = page.getByRole("region", { name: "Property context", exact: true });
  await expect(context.getByRole("alert")).toContainText("could not be loaded");
  unavailable = false;
  await context.getByRole("button", { name: "Retry", exact: true }).click();
  await expect(
    context.getByRole("link", { name: f.property.displayName, exact: true }),
  ).toBeVisible();
  await expect(page).toHaveURL(new RegExp(`leaseId=${f.lease.id}`));
});

async function save(page: Page, title: string) {
  await test.step(title, async () => {
    await page
      .getByRole("group", { name: "Form actions", exact: true })
      .locator('button[type="submit"]')
      .click();
  });
  await expect(page.locator('.saved-item, section[aria-label="Committed result"]')).toBeVisible();
  if (await page.locator(".saved-item").count()) return;
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
test("Money actions are visible buttons and open the selected workflow", async ({ page }) => {
  for (const [tab, label, formKey] of [
    ["expenses", "Record paid expense", "finance.expense.create"],
    ["categories", "Create expense category", "finance.expense_category.create"],
  ]) {
    await page.goto(`/money?tab=${tab}`);
    const actions = page.getByRole("navigation", { name: "Money actions", exact: true });
    await expect(actions).toBeVisible();
    await expect(actions.locator("xpath=ancestor::details")).toHaveCount(0);
    const button = actions.getByRole("button", { name: label, exact: true });
    await expect(button).toBeVisible();
    await button.click();
    await expect(page).toHaveURL(new RegExp(`workflow=${formKey.replaceAll(".", "\\.")}`));
  }
});

test("rent payment detail shows named context, exact allocations and retained void history", async ({
  page,
  request,
}, testInfo) => {
  const f = await fixture(request, true);
  const synced = await schedule(request, f);
  const receipt = await post<
    Schemas["app__modules__finance__api__router__ReceiptMutationResponse"]
  >(request, "/api/rent-receipts", {
    leaseId: f.lease.id,
    expectedRevision: synced.rentLedgerRevision,
    idempotencyKey: crypto.randomUUID(),
    receivedOn: f.today,
    amountMinor: 65000,
    currencyCode: "USD",
    paymentMethodKind: "bank_transfer",
    maskedReference: "Transfer **** 9876",
    notes: "Payment covers two rent periods",
    allocations: synced.items
      .slice(0, 2)
      .map((item, index) => ({ expectationId: item.id, amountMinor: index ? 30000 : 35000 })),
  });
  await page.goto(`/money?record=receipt&id=${receipt.id}`);
  const detail = page.getByRole("region", { name: "Money record", exact: true });
  await expect(detail.getByRole("heading", { name: "Rent payment", exact: true })).toBeVisible();
  await expect(
    detail.getByRole("link", { name: f.property.displayName, exact: true }),
  ).toBeVisible();
  const summary = detail.getByRole("region", { name: "Payment summary", exact: true });
  await expect(summary).toContainText("USD 650.00");
  await expect(summary).toContainText("Transfer **** 9876");
  await expect(summary).toContainText("Payment covers two rent periods");
  const table = detail.getByRole("table", { name: "Rent allocations", exact: true });
  await expect(table.getByRole("row")).toHaveCount(3);
  await expect(table).toContainText("USD 350.00");
  await expect(table).toContainText("USD 300.00");
  await expect(detail.getByRole("button", { name: "Void payment", exact: true })).toBeVisible();
  await expect(detail.getByText(f.lease.id, { exact: true })).toHaveCount(0);
  for (const theme of ["light", "dark"]) {
    await page.evaluate((value) => (document.documentElement.dataset.theme = value), theme);
    for (const width of [1280, 390]) {
      await page.setViewportSize({ width, height: 900 });
      await expect
        .poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth))
        .toBe(true);
      await page.screenshot({
        path: testInfo.outputPath(`rent-payment-${theme}-${width}.png`),
        fullPage: true,
      });
      await page.evaluate(axe.source);
      expect(
        await page.evaluate(
          async () =>
            (
              await window.axe.run(".rent-detail", {
                runOnly: { type: "tag", values: ["wcag2a", "wcag2aa"] },
              })
            ).violations,
        ),
      ).toEqual([]);
    }
  }
  await post(request, `/api/rent-receipts/${receipt.id}/void`, {
    expectedRevision: receipt.rentLedgerRevision,
    idempotencyKey: crypto.randomUUID(),
    confirmed: true,
    voidReason: "Duplicate transfer entry",
  });
  await page.reload();
  await expect(summary).toContainText("This payment was voided.");
  await expect(summary).toContainText("Duplicate transfer entry");
  await expect(
    detail.getByRole("table", { name: "Original rent allocations", exact: true }),
  ).toBeVisible();
  await expect(detail.getByRole("button", { name: "Void payment", exact: true })).toHaveCount(0);
  await expect(detail.getByRole("link", { name: "Record replacement rent receipt" })).toBeVisible();
  await detail
    .getByRole("link", {
      name: `${formatDate(synced.items[0].periodStartsOn)} – ${formatDate(synced.items[0].periodEndsOn)}`,
      exact: true,
    })
    .click();
  await expect(page).toHaveURL(new RegExp(`record=expectation&id=${synced.items[0].id}`));
});

test("Money lists present rent and expenses as readable cards", async ({ page, request }) => {
  const f = await fixture(request);
  await schedule(request, f);
  const paidExpense = await expense(request, f);
  await page.goto(`/money?tab=rent&leaseId=${f.lease.id}`);
  await expect(
    page
      .getByRole("navigation", { name: "Money views" })
      .getByRole("link", { name: "Rent", exact: true }),
  ).toHaveAttribute("aria-current", "page");
  const rent = page
    .getByRole("region", { name: "Rent records", exact: true })
    .getByRole("article")
    .first();
  await expect(rent.getByRole("heading", { name: "Rent due" })).toBeVisible();
  await expect(rent.getByText("Expected", { exact: true })).toBeVisible();
  await expect(rent.getByText("Payment timing", { exact: true })).toBeVisible();
  await expect(rent.getByText("USD 1,000.00", { exact: true }).first()).toBeVisible();
  await expect(
    rent.getByRole("link", { name: "Review amounts and receipt allocations" }),
  ).toBeVisible();
  await page.goto(`/money?tab=expenses&propertyId=${f.property.id}`);
  const card = page
    .getByRole("region", { name: "Expenses records", exact: true })
    .getByRole("article");
  await expect(card.getByRole("heading", { name: "Plumber" })).toBeVisible();
  await expect(card).toContainText(f.property.displayName);
  await expect(card.getByText("USD 120.01", { exact: true }).first()).toBeVisible();
  await expect(card.getByRole("link", { name: "Plumber", exact: true })).toHaveAttribute(
    "href",
    `/money?record=expense&id=${paidExpense.id}`,
  );
});

test("Money groups the current page by named properties with one batch lookup", async ({
  page,
  request,
}) => {
  const first = await fixture(request),
    second = await fixture(request);
  for (const f of [first, second]) {
    const synced = await schedule(request, f);
    await expense(request, f);
    await post(request, "/api/rent-receipts", {
      expectedRevision: synced.rentLedgerRevision,
      idempotencyKey: crypto.randomUUID(),
      leaseId: f.lease.id,
      receivedOn: f.today,
      amountMinor: 100,
      currencyCode: "USD",
      paymentMethodKind: "cash",
      allocations: [{ expectationId: synced.items[0].id, amountMinor: 100 }],
    });
  }
  const lookups: string[] = [],
    individualReads: string[] = [];
  page.on("request", (entry) => {
    const path = new URL(entry.url()).pathname;
    if (path === "/api/money/property-contexts") lookups.push(entry.url());
    if (/^\/api\/(properties|leases)\/[^/]+$/.test(path)) individualReads.push(entry.url());
  });
  for (const tab of ["rent", "expenses", "receipts"]) {
    await page.goto(`/money?tab=${tab}`);
    for (const f of [first, second]) {
      const group = page.getByRole("region", { name: f.property.displayName, exact: true });
      await expect(
        group.getByRole("heading", { name: f.property.displayName, exact: true }),
      ).toBeVisible();
      await expect(group.getByRole("article").first()).toBeVisible();
      await expect(
        group.getByRole("link", { name: f.property.displayName, exact: true }),
      ).toHaveAttribute("href", `/properties/${f.property.id}/overview`);
    }
    expect(lookups).toHaveLength(["rent", "expenses", "receipts"].indexOf(tab) + 1);
    expect(individualReads).toHaveLength(0);
  }
  await page.goto("/money?tab=categories");
  await expect(
    page.getByRole("heading", { name: "Shared expense categories", exact: true }),
  ).toBeVisible();
  expect(lookups).toHaveLength(3);
});

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

test("paid Expense creation selects Property Space Provider and a Party payer without duplicating spending", async ({
  page,
  request,
}) => {
  const f = await fixture(request);
  const provider = await post<Schemas["ProviderMutationResponse"]>(request, "/api/providers", {
    party: { partyKind: "organization", displayName: `Expense Provider ${f.property.id}` },
    expectedRevision: 0,
    idempotencyKey: crypto.randomUUID(),
  });
  const categories = await get<
    Schemas["app__modules__finance__api__expense_router__CategoryResponse"][]
  >(request, "/api/expense-categories");
  await page.goto("/money?workflow=finance.expense.create");
  await page
    .getByRole("combobox", { name: "Select Property", exact: true })
    .selectOption(f.property.id);
  await expect(page.getByRole("region", { name: "Expense context", exact: true })).toContainText(
    "America/Los_Angeles",
  );
  await page
    .getByRole("combobox", { name: "Space within selected Property", exact: true })
    .selectOption(f.property.spaces[0].id);
  await page.getByLabel("Provider search", { exact: true }).fill(provider.party.displayName);
  await page.getByRole("button", { name: "Search saved Providers", exact: true }).click();
  await page
    .getByRole("button", { name: `Use Provider ${provider.party.displayName}`, exact: true })
    .click();
  await page.getByLabel("Category id (required)").selectOption(categories[0].id);
  await page.getByLabel("Paid on (required)").fill(f.today);
  await page.getByLabel("Amount (required)").fill("101.03");
  await page.getByLabel("Description (required)").fill("Already paid provider repair");
  await page.getByLabel("Paid by kind (required)").selectOption("party");
  await page.getByLabel("Paid by party id", { exact: true }).fill(f.owner);
  await save(page, "Record paid expense");
  await expect(page.getByRole("link", { name: "Add expense evidence", exact: true })).toBeVisible();
  await page.getByRole("link", { name: "Back to expense", exact: true }).click();
  const items = (
    await get<Schemas["ExpensePageResponse"]>(request, `/api/expenses?propertyId=${f.property.id}`)
  ).items;
  expect(items).toHaveLength(1);
  expect(items[0].providerPartyId).toBe(provider.party.id);
  expect(items[0].paidByPartyId).toBe(f.owner);
  expect(items[0].spaceId).toBe(f.property.spaces[0].id);
  await page.goto(`/money?tab=expenses&propertyId=${f.property.id}`);
  await page.getByLabel("Provider", { exact: true }).fill(provider.party.id);
  await page.getByLabel("Payer", { exact: true }).fill(f.owner);
  await page.getByRole("combobox", { name: "Paid by", exact: true }).selectOption("party");
  await page.getByLabel("Date paid from", { exact: true }).fill(f.today);
  await page.getByLabel("Date paid to", { exact: true }).fill(f.today);
  await page.getByRole("combobox", { name: "Evidence", exact: true }).selectOption("false");
  const directory = page.getByRole("region", { name: "Expenses records", exact: true });
  await expect(directory).toContainText("USD 101.03");
  await expect(directory).toContainText(f.property.displayName);
});

test("likely duplicate Expenses require explicit separate-payment review", async ({
  page,
  request,
}) => {
  const f = await fixture(request),
    item = await expense(request, f);
  let creates = 0;
  page.on("request", (request) => {
    if (request.method() === "POST" && new URL(request.url()).pathname === "/api/expenses")
      creates++;
  });
  await page.goto(`/money?workflow=finance.expense.create&propertyId=${f.property.id}`);
  await page.getByLabel("Category id (required)").selectOption(item.categoryId);
  await page.getByLabel("Paid on (required)").fill(item.paidOn);
  await page.getByLabel("Amount (required)").fill(item.amount);
  await page.getByLabel("Payee name", { exact: true }).fill(item.payeeName);
  await page.getByLabel("Description (required)").fill(item.description);
  await page.getByRole("button", { name: "Record paid expense", exact: true }).click();
  const candidates = page.getByRole("region", { name: "Possible duplicate expenses", exact: true });
  await expect(
    candidates.getByRole("link", { name: "Open existing expense", exact: true }),
  ).toHaveAttribute("href", `/money?record=expense&id=${item.id}`);
  expect(
    (
      await get<Schemas["ExpensePageResponse"]>(
        request,
        `/api/expenses?propertyId=${f.property.id}`,
      )
    ).items,
  ).toHaveLength(1);
  expect(creates).toBe(0);
  await candidates.getByRole("button", { name: "Record separately", exact: true }).click();
  await save(page, "Record paid expense");
  expect(
    (
      await get<Schemas["ExpensePageResponse"]>(
        request,
        `/api/expenses?propertyId=${f.property.id}`,
      )
    ).items,
  ).toHaveLength(2);
  expect(creates).toBe(1);
});

test("Expense category correction evidence archival and refund replacement preserve contextual history", async ({
  page,
  request,
}) => {
  const f = await fixture(request),
    item = await expense(request, f);
  const categories = await get<
    Schemas["app__modules__finance__api__expense_router__CategoryResponse"][]
  >(request, "/api/expense-categories");
  const category = categories.find(
    (category) => category.id !== item.categoryId && !category.archivedAt,
  )!;
  await page.goto(`/money?workflow=finance.expense.patch&target=${item.id}`);
  await page.getByRole("combobox", { name: "Category id", exact: true }).selectOption(category.id);
  await page
    .getByRole("textbox", { name: "Category change reason", exact: true })
    .fill("Correct recorded classification");
  await save(page, "Edit expense context");
  await upload(request, "expense", item.id);
  await page.goto(`/money?record=expense&id=${item.id}`);
  await page.getByRole("link", { name: "Archive evidence association", exact: true }).click();
  await page.getByLabel("Reason (required)").fill("Incorrect expense association");
  await page.getByLabel("I confirm this lifecycle change", { exact: true }).check();
  await page.getByRole("button", { name: "Save archive evidence link", exact: true }).click();
  await expect(page.locator('.saved-item, section[aria-label="Committed result"]')).toBeVisible();
  const current = await get<Schemas["ExpenseResponse"]>(request, `/api/expenses/${item.id}`);
  expect(current.categoryId).toBe(category.id);
  expect(current.activeEvidence).toHaveLength(0);
  expect(current.archivedEvidence[0].archiveReason).toBe("Incorrect expense association");
  await page.goto(`/money?record=expense&id=${item.id}`);
  await page.getByText("Archived evidence history", { exact: true }).click();
  await expect(page.getByRole("region", { name: "Money record", exact: true })).toContainText(
    "Incorrect expense association",
  );
  const refund = await post<
    Schemas["app__modules__finance__api__expense_router__RefundMutationResponse"]
  >(request, `/api/expenses/${item.id}/refunds`, {
    expectedRevision: current.expenseRevision,
    idempotencyKey: crypto.randomUUID(),
    receivedOn: f.today,
    amount: "20.00",
    currencyCode: "USD",
  });
  await page.goto(
    `/money?workflow=finance.expense_refund.void&target=${item.id}&child=${refund.id}`,
  );
  await page.getByLabel("Reason (required)").fill("Correct refund amount");
  await page.getByLabel("I confirm this lifecycle change", { exact: true }).check();
  await save(page, "Void expense refund");
  await page.goto(`/money?record=expense&id=${item.id}`);
  await page.getByRole("link", { name: "Record replacement refund", exact: true }).click();
  await expect(page.getByLabel("Amount (required)")).toHaveValue("20.00");
  await page.getByLabel("Amount (required)").fill("21.00");
  await save(page, "Record expense refund");
  const final = await get<Schemas["ExpenseResponse"]>(request, `/api/expenses/${item.id}`);
  expect(final.refunds.find((row) => !row.voidedAt)?.replacesRefundId).toBe(refund.id);
  expect(final.activeRefundedAmount).toBe("21.00");
});

test("archived Expense categories require a visible historical entry confirmation and reason", async ({
  page,
  request,
}) => {
  const f = await fixture(request);
  const category = await post<
    Schemas["app__modules__finance__api__expense_router__CategoryMutationResponse"]
  >(request, "/api/expense-categories", {
    expectedRevision: 0,
    idempotencyKey: crypto.randomUUID(),
    displayName: `Historical ${f.property.id}`,
  });
  await post(request, `/api/expense-categories/${category.id}/archive`, {
    expectedRevision: category.revision,
    idempotencyKey: crypto.randomUUID(),
    confirmed: true,
    reason: "Retired classification",
  });
  await page.goto(`/money?workflow=finance.expense.create&propertyId=${f.property.id}`);
  await expect(
    page.getByLabel("Category id (required)").locator(`option[value="${category.id}"]`),
  ).toHaveCount(0);
  await page.getByLabel("Paid on (required)").fill(f.today);
  await page.getByLabel("Amount (required)").fill("12.34");
  await page.getByLabel("Payee name", { exact: true }).fill("Historical merchant");
  await page.getByLabel("Description (required)").fill("Entered from retained receipt");
  await page.getByLabel("Historical entry confirmed", { exact: true }).check();
  await page
    .getByLabel("Historical entry reason", { exact: true })
    .fill("Retained receipt used an archived category");
  await page.getByLabel("Category id (required)").selectOption(category.id);
  await expect(page.getByRole("region", { name: "Expense context", exact: true })).toContainText(
    "Historical entry is exceptional",
  );
  await save(page, "Record paid expense");
  expect(
    (
      await get<Schemas["ExpensePageResponse"]>(
        request,
        `/api/expenses?propertyId=${f.property.id}`,
      )
    ).items[0].categoryId,
  ).toBe(category.id);
});

test("rent synchronization and a partial receipt keep allocations and remaining balance visible", async ({
  page,
  request,
}, testInfo) => {
  const f = await fixture(request);
  await page.goto(`/money?workflow=finance.rent_expectation.synchronize&target=${f.lease.id}`);
  await page.getByLabel("Lease term id (required)").selectOption(f.lease.terms[0].id);
  await page.getByLabel("Through on (required)").fill(f.through);
  await page.getByLabel("Schedule anchor on", { exact: true }).fill(f.start);
  await page.getByRole("button", { name: "Preview rent schedule", exact: true }).click();
  await expect(
    page.getByRole("region", { name: "Rent schedule preview", exact: true }),
  ).toContainText("America/Los_Angeles");
  await page
    .getByLabel("I confirm this anchor and every previewed period", { exact: true })
    .check();
  await save(page, "Synchronize rent schedule");
  const expectations = await get<Schemas["ExpectationPageResponse"]>(
    request,
    `/api/rent-expectations?leaseId=${f.lease.id}`,
  );
  const expectation = expectations.items.find((item) => item.periodStartsOn === f.start)!;
  await page.goto(`/money?record=expectation&id=${expectation.id}`);
  await expect(page.getByText("USD 1,000.00", { exact: true }).first()).toBeVisible();
  await expect(page.getByRole("heading", { name: "Rent due", exact: true })).toBeVisible();
  await expect(page.getByRole("region", { name: "Rent balance", exact: true })).toContainText(
    "Still due",
  );
  await expect(page.getByRole("region", { name: "Money record", exact: true })).not.toContainText(
    expectation.id,
  );
  for (const theme of ["light", "dark"]) {
    await page.evaluate((value) => (document.documentElement.dataset.theme = value), theme);
    for (const width of [1280, 390]) {
      await page.setViewportSize({ width, height: 900 });
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
        true,
      );
      await page
        .locator(".rent-detail")
        .screenshot({ path: testInfo.outputPath(`rent-${theme}-${width}.png`) });
    }
  }
  await page.evaluate(axe.source);
  expect(
    await page.evaluate(async () =>
      (
        await window.axe.run(".rent-detail", {
          runOnly: { type: "tag", values: ["wcag2a", "wcag2aa"] },
        })
      ).violations.map((item) => item.id),
    ),
  ).toEqual([]);
  await page.getByRole("button", { name: "Record payment", exact: true }).click();
  await page.getByLabel("Received on (required)").fill(f.today);
  await page.getByLabel("Payment method kind (required)").selectOption("cash");
  await page.getByLabel("Amount (USD cents) (required)").nth(0).fill("40000");
  await page.getByLabel("Amount (USD cents) (required)").nth(1).fill("40000");
  await save(page, "Record rent receipt");
  await page.goto(`/money?record=expectation&id=${expectation.id}`);
  await expect(page.getByText("USD 600.00", { exact: true })).toBeVisible();
  const receipts = await get<Schemas["ReceiptPageResponse"]>(
    request,
    `/api/rent-receipts?leaseId=${f.lease.id}`,
  );
  expect(receipts.items).toHaveLength(1);
  expect(receipts.items[0].allocations[0].amountMinor).toBe(40000);
  const allocations = page.getByRole("region", { name: "Allocation summaries", exact: true });
  await expect(allocations.getByText("Amount applied", { exact: true })).toBeVisible();
  await expect(allocations.getByText("USD 400.00", { exact: true })).toBeVisible();
  await expect(allocations.getByText("Payment status", { exact: true })).toHaveCount(1);
  await expect(allocations).not.toContainText("Amount minor");
  await expect(allocations).not.toContainText(receipts.items[0].id);
  await expect(
    allocations.getByRole("link", { name: "Recorded receipt for this allocation", exact: true }),
  ).toHaveAttribute("href", `/money?record=receipt&id=${receipts.items[0].id}`);
  await page.goto(
    `/money?workflow=finance.rent_receipt.create&target=${f.lease.id}&child=${expectation.id}`,
  );
  await expect(
    page.getByRole("combobox", { name: "Payment method kind (required)", exact: true }),
  ).toHaveValue("cash");
});

test("rent preview requires a separately confirmed responsibility override and renewed approval after input changes", async ({
  page,
  request,
}) => {
  const f = await fixture(request);
  await page.goto(`/money?workflow=finance.rent_expectation.synchronize&target=${f.lease.id}`);
  await page.getByLabel("Lease term id (required)").selectOption(f.lease.terms[0].id);
  await page.getByLabel("Through on (required)").fill(f.through);
  await page.getByRole("button", { name: "Use suggested anchor", exact: true }).click();
  await page
    .getByLabel("Responsibility ends on override", { exact: true })
    .fill(`${f.start.slice(0, 8)}15`);
  await page
    .getByLabel("Override reason", { exact: true })
    .fill("Explicit responsibility agreement");
  await page.getByRole("button", { name: "Preview rent schedule", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("Explicit override confirmation is required");
  await page.getByLabel("Override confirmed", { exact: true }).check();
  await page.getByRole("button", { name: "Preview rent schedule", exact: true }).click();
  await expect(
    page.getByRole("region", { name: "Rent schedule preview", exact: true }),
  ).toContainText("Prorated: 15/");
  await page
    .getByLabel("I confirm this anchor and every previewed period", { exact: true })
    .check();
  await page.getByLabel("Through on (required)").fill(f.today);
  await expect(
    page.getByRole("button", { name: "Save synchronize rent schedule", exact: true }),
  ).toBeDisabled();
  await page.getByLabel("Through on (required)").fill(f.through);
  await page.getByRole("button", { name: "Preview rent schedule", exact: true }).click();
  await page
    .getByLabel("I confirm this anchor and every previewed period", { exact: true })
    .check();
  await save(page, "Synchronize rent schedule");
  const result = await get<Schemas["ExpectationPageResponse"]>(
    request,
    `/api/rent-expectations?leaseId=${f.lease.id}`,
  );
  expect(result.items).toHaveLength(1);
  expect(result.items[0].isProrated).toBe(true);
  expect(result.items[0].prorationNumeratorDays).toBe(15);
});

for (const method of [
  "automatic_bank_payment",
  "bank_transfer",
  "check",
  "cash",
  "online_payment",
  "other",
] as const) {
  test(`actual rent method ${method} is retained without payment initiation`, async ({
    page,
    request,
  }) => {
    const f = await fixture(request),
      synced = await schedule(request, f);
    await page.goto(
      `/money?workflow=finance.rent_receipt.create&target=${f.lease.id}&child=${synced.items[0].id}`,
    );
    const review = page.getByRole("region", { name: "Actual payment method review", exact: true });
    await expect(review).toContainText("does not collect, initiate, schedule or authorize");
    await expect(review).toContainText("No prior method is suggested");
    await page.getByLabel("Received on (required)").fill(f.today);
    await page.getByLabel("Payment method kind (required)").selectOption(method);
    await page.getByLabel("Payment method label", { exact: true }).fill(`Actual ${method}`);
    if (method !== "cash")
      await page.getByLabel("Masked reference", { exact: true }).fill("Check •••• 4321");
    if (method === "other") {
      await expect(
        page.getByRole("button", { name: "Record rent receipt", exact: true }),
      ).toBeDisabled();
      await page
        .getByLabel("Other payment method note", { exact: true })
        .fill("Confirmed money order received");
    }
    await save(page, "Record rent receipt");
    const receipts = await get<Schemas["ReceiptPageResponse"]>(
      request,
      `/api/rent-receipts?leaseId=${f.lease.id}`,
    );
    expect(receipts.items).toHaveLength(1);
    expect(receipts.items[0]).toMatchObject({
      paymentMethodKind: method,
      paymentMethodLabel: `Actual ${method}`,
      maskedReference: method === "cash" ? null : "Check •••• 4321",
      otherPaymentMethodNote: method === "other" ? "Confirmed money order received" : null,
    });
    await page.goto(`/money?record=receipt&id=${receipts.items[0].id}`);
    await expect(page.getByRole("region", { name: "Money record", exact: true })).toContainText(
      `Actual ${method}`,
    );
    if (method === "other")
      await expect(page.getByRole("region", { name: "Money record", exact: true })).toContainText(
        "Confirmed money order received",
      );
  });
}

test("prior actual method remains editable and replacement keeps its own original snapshot", async ({
  page,
  request,
}) => {
  const f = await fixture(request),
    synced = await schedule(request, f),
    expectation = synced.items[0];
  const prior = await post<Schemas["app__modules__finance__api__router__ReceiptMutationResponse"]>(
    request,
    "/api/rent-receipts",
    {
      expectedRevision: synced.rentLedgerRevision,
      idempotencyKey: crypto.randomUUID(),
      leaseId: f.lease.id,
      receivedOn: f.today,
      amountMinor: 40000,
      currencyCode: "USD",
      allocations: [{ expectationId: expectation.id, amountMinor: 40000 }],
      paymentMethodKind: "other",
      paymentMethodLabel: "Original money order",
      maskedReference: "Order ** 1234",
      otherPaymentMethodNote: "Confirmed original money order",
    },
  );
  await page.goto(
    `/money?workflow=finance.rent_receipt.create&target=${f.lease.id}&child=${expectation.id}`,
  );
  await expect(page.getByLabel("Payment method kind (required)")).toHaveValue("other");
  await expect(
    page.getByRole("region", { name: "Actual payment method review", exact: true }),
  ).toContainText("Editable suggestion from the latest non-voided receipt");
  await page.getByLabel("Received on (required)").fill(f.today);
  await page.getByLabel("Payment method kind (required)").selectOption("bank_transfer");
  await expect(page.getByLabel("Other payment method note", { exact: true })).toHaveCount(0);
  await expect(page.getByLabel("Masked reference", { exact: true })).toHaveValue("");
  await expect(page.getByLabel("Payment method label", { exact: true })).toHaveValue("");
  await page.getByLabel("Masked reference", { exact: true }).fill("4111111111111111");
  await expect(
    page.getByRole("button", { name: "Record rent receipt", exact: true }),
  ).toBeDisabled();
  await page.getByLabel("Masked reference", { exact: true }).fill("Transfer **** 9876");
  await page.getByLabel("Payment method label", { exact: true }).fill("Current transfer");
  await save(page, "Record rent receipt");
  const receipts = await get<Schemas["ReceiptPageResponse"]>(
    request,
    `/api/rent-receipts?leaseId=${f.lease.id}`,
  );
  const changed = receipts.items.find((item) => item.id !== prior.id)!;
  expect(changed).toMatchObject({
    paymentMethodKind: "bank_transfer",
    maskedReference: "Transfer **** 9876",
    otherPaymentMethodNote: null,
  });
  await page.goto(
    `/money?workflow=finance.rent_receipt.void&target=${f.lease.id}&child=${changed.id}`,
  );
  await page.getByLabel("Void reason (required)").fill("Corrected actual method snapshot");
  await page.getByLabel("I confirm this lifecycle change", { exact: true }).check();
  await save(page, "Void rent receipt");
  await page.goto(
    `/money?workflow=finance.rent_receipt.create&target=${f.lease.id}&child=${expectation.id}&replacesReceiptId=${changed.id}`,
  );
  await expect(page.getByLabel("Payment method kind (required)")).toHaveValue("bank_transfer");
  await expect(page.getByLabel("Masked reference", { exact: true })).toHaveValue(
    "Transfer **** 9876",
  );
  await expect(
    page.getByRole("region", { name: "Actual payment method review", exact: true }),
  ).toContainText("Replacement starts with the voided receipt's method");
  await page.getByLabel("Payment method kind (required)").selectOption("cash");
  await save(page, "Record rent receipt");
  const original = await get<Schemas["app__modules__finance__api__router__ReceiptResponse"]>(
    request,
    `/api/rent-receipts/${changed.id}`,
  );
  expect(original.paymentMethodKind).toBe("bank_transfer");
  expect(original.maskedReference).toBe("Transfer **** 9876");
  const current = await get<Schemas["ReceiptPageResponse"]>(
    request,
    `/api/rent-receipts?leaseId=${f.lease.id}`,
  );
  expect(
    current.items.find((item) => item.replacesReceiptId === changed.id)?.paymentMethodKind,
  ).toBe("cash");
});

test("receipt totals prevent unmatched money and allocate one payment across two rent periods", async ({
  page,
  request,
}) => {
  const f = await fixture(request, true),
    synced = await schedule(request, f);
  const [first, second] = synced.items;
  await page.goto(
    `/money?workflow=finance.rent_receipt.create&target=${f.lease.id}&child=${first.id}`,
  );
  await page.getByLabel("Received on (required)").fill(f.today);
  await page.getByLabel("Payment method kind (required)").selectOption("cash");
  await page
    .getByRole("region", { name: "Payment received", exact: true })
    .getByLabel("Amount (USD cents) (required)")
    .fill("150000");
  await page
    .getByRole("region", { name: "Apply payment to rent", exact: true })
    .getByLabel("Amount (USD cents) (required)")
    .fill("100000");
  const totals = page.getByRole("region", { name: "Receipt allocation totals", exact: true });
  await expect(totals).toContainText("USD 500.00");
  await expect(
    page.getByRole("button", { name: "Record rent receipt", exact: true }),
  ).toBeDisabled();
  expect(
    (await get<Schemas["ReceiptPageResponse"]>(request, `/api/rent-receipts?leaseId=${f.lease.id}`))
      .items,
  ).toHaveLength(0);
  await page.getByRole("button", { name: "Add allocations entry", exact: true }).click();
  await page
    .getByRole("combobox", { name: "Rent period (required)", exact: true })
    .nth(1)
    .selectOption(second.id);
  await page
    .getByRole("region", { name: "Apply payment to rent", exact: true })
    .getByLabel("Amount (USD cents) (required)")
    .nth(1)
    .fill("50000");
  await expect(totals).toContainText("USD 0.00");
  await save(page, "Record rent receipt");
  const receipts = await get<Schemas["ReceiptPageResponse"]>(
    request,
    `/api/rent-receipts?leaseId=${f.lease.id}`,
  );
  expect(receipts.items).toHaveLength(1);
  expect(receipts.items[0].allocations).toHaveLength(2);
  await page.goto(`/money?tab=rent&leaseId=${f.lease.id}`);
  await page.getByRole("combobox", { name: "Settlement", exact: true }).selectOption("partial");
  await expect(
    page
      .getByRole("region", { name: "Rent records", exact: true })
      .getByText("Still due", { exact: true }),
  ).toHaveCount(1);
  await page
    .getByRole("link", { name: "Review amounts and receipt allocations", exact: true })
    .click();
  await page
    .getByRole("link", { name: "Recorded receipt for this allocation", exact: true })
    .click();
  await expect(page.getByRole("region", { name: "Money record", exact: true })).toContainText(
    "USD 1,500.00",
  );
  await page.setViewportSize({ width: 390, height: 900 });
  for (const theme of ["light", "dark"]) {
    await page.goto("/settings");
    await page
      .getByRole("radio", { name: theme === "dark" ? "Dark" : "Light", exact: true })
      .check();
    await page.getByRole("button", { name: "Save preferences", exact: true }).click();
    await expect(page.getByText("Preferences saved.")).toBeVisible();
    await page.goto(`/money?record=receipt&id=${receipts.items[0].id}`);
    await expect(page.getByRole("region", { name: "Money record", exact: true })).toContainText(
      "USD 1,500.00",
    );
    await page.evaluate(axe.source);
    expect(
      await page.evaluate(async () =>
        (
          await window.axe.run(document, {
            runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21aa"] },
          })
        ).violations.map((item) => item.id),
      ),
    ).toEqual([]);
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
    ).toBe(true);
  }
});

test("rent timeliness requires an explicit missed decision and retains its cleared history", async ({
  page,
  request,
}) => {
  const f = await fixture(request, true),
    synced = await schedule(request, f);
  const expectation = synced.items.find((item) => item.periodEndsOn < f.today)!;
  await page.goto(
    `/money?workflow=finance.rent_expectation.timeliness_review&target=${f.lease.id}&child=${expectation.id}`,
  );
  await page.getByLabel("Decision (required)").selectOption("mark_missed");
  await page.getByLabel("Reason (required)").fill("Reviewed ended unpaid period");
  await page.getByLabel("I confirm this lifecycle change", { exact: true }).check();
  await save(page, "Review rent timeliness");
  await page.goto(`/money?record=expectation&id=${expectation.id}`);
  await expect(page.getByRole("region", { name: "Timeliness reviews", exact: true })).toContainText(
    "Reviewed ended unpaid period",
  );
  await expect(page.getByRole("region", { name: "Money record", exact: true })).toContainText(
    "not a legal determination",
  );
  await page.goto(
    `/money?workflow=finance.rent_expectation.timeliness_review&target=${f.lease.id}&child=${expectation.id}`,
  );
  await page.getByLabel("Decision (required)").selectOption("clear_missed");
  await page.getByLabel("Reason (required)").fill("Reopened operational review");
  await page.getByLabel("I confirm this lifecycle change", { exact: true }).check();
  await save(page, "Review rent timeliness");
  const current = await get<Schemas["ExpectationResponse"]>(
    request,
    `/api/rent-expectations/${expectation.id}`,
  );
  expect(current.timelinessStatus).toBe("late");
  expect(current.timelinessReviews.map((item) => item.decision)).toEqual([
    "mark_missed",
    "clear_missed",
  ]);
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
  let recoveryId: string | undefined;
  page.on("request", (request) => {
    if (request.method() === "PUT" && request.url().includes("/api/operator/recovery/")) {
      const body = request.postDataJSON() as { payload?: { propertyId?: string } };
      if (body.payload?.propertyId === f.property.id) recoveryId = request.url().split("/").at(-1);
    }
  });
  await page.route("**/api/expenses", async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    calls++;
    await route.fetch();
    await route.abort("failed");
  });
  await page.getByRole("button", { name: "Record paid expense", exact: true }).click();
  await expect(page.getByRole("button", { name: "Check original result" })).toBeVisible();
  await page.goto("/settings/recovery");
  expect(recoveryId).toBeTruthy();
  await page
    .getByRole("link", { name: "Resume: Record paid expense", exact: true })
    .and(page.locator(`a[href*="resume=${recoveryId}"]`))
    .click();
  await page.getByRole("button", { name: "Check original result" }).click();
  const savedExpense = page.getByRole("region", { name: "Expense saved", exact: true });
  await expect(
    savedExpense.getByRole("heading", { name: "Expense saved", exact: true }),
  ).toBeVisible();
  await expect(savedExpense).toContainText("Receipt plumber");
  await expect(savedExpense).toContainText("Paid repair");
  await expect(savedExpense).toContainText("120.01");
  expect(calls).toBe(1);
  const expenses = await get<Schemas["ExpensePageResponse"]>(
    request,
    `/api/expenses?propertyId=${f.property.id}`,
  );
  expect(expenses.items).toHaveLength(1);
  await expect(
    savedExpense.getByRole("link", { name: "Back to expense", exact: true }),
  ).toHaveAttribute("href", `/money?record=expense&id=${expenses.items[0].id}`);
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
  await page.getByRole("button", { name: "Attach supporting evidence", exact: true }).click();
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
  await page
    .getByRole("link", {
      name: /^(Open current money record|Back to (expense|deposit account|rent receipt|prepaid check|owner rent report|expense category))$/,
      exact: true,
    })
    .click();
  await page.getByRole("button", { name: "Edit expense category", exact: true }).click();
  await page.getByLabel("Description", { exact: true }).fill("Current category description");
  await save(page, "Edit expense category");
  await page
    .getByRole("link", {
      name: /^(Open current money record|Back to (expense|deposit account|rent receipt|prepaid check|owner rent report|expense category))$/,
      exact: true,
    })
    .click();
  await page.getByRole("button", { name: "Edit expense category", exact: true }).click();
  await page.getByText("Clear or keep description", { exact: true }).click();
  await page.getByLabel("Clear description", { exact: true }).check();
  await save(page, "Clear expense category description");
  await page.getByRole("link", { name: "Back to expense category", exact: true }).click();
  await expect(
    page.getByRole("region", { name: "Expense category details", exact: true }),
  ).toContainText("No description recorded.");
  await page.getByRole("button", { name: "Archive expense category", exact: true }).click();
  await page.getByLabel("Reason (required)").fill("Unused category");
  await page.getByLabel("I confirm this lifecycle change", { exact: true }).check();
  await save(page, "Archive expense category");
  await page
    .getByRole("link", {
      name: /^(Open current money record|Back to (expense|deposit account|rent receipt|prepaid check|owner rent report|expense category))$/,
      exact: true,
    })
    .click();
  await page.getByRole("button", { name: "Restore expense category", exact: true }).click();
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
    await page.goto(`/money?record=report&id=${report.id}`);
    await expect(
      page.getByRole("button", { name: "Edit owner rent report", exact: true }),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Reject owner rent report", exact: true }),
    ).toBeVisible();
    await page.getByRole("button", { name: "Verify owner rent report", exact: true }).click();
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
  await expect(page.getByLabel("Reported at utc (required)", { exact: true })).toHaveCount(0);
  await save(page, "Record owner rent report");
  const items = await get<Schemas["OwnerRentReportPageResponse"]>(
    request,
    `/api/owner-rent-reports?leaseId=${f.lease.id}`,
  );
  expect(items.items).toHaveLength(1);
  expect(items.items[0].reportedAtUtc).toBe(items.items[0].createdAt);
  expect(items.items[0].receivedOn).toBe(f.today);
  await page.goto(`/money?workflow=owner_rent_report.patch&target=${items.items[0].id}`);
  await expect(page.getByLabel("Reported at utc", { exact: true })).toHaveCount(0);
  await page.getByLabel("Source note", { exact: true }).fill("Corrected source note");
  await save(page, "Edit owner rent report");
  const edited = await get<Schemas["OwnerRentReportResponse"]>(
    request,
    `/api/owner-rent-reports/${items.items[0].id}`,
  );
  expect(edited.reportedAtUtc).toBe(items.items[0].reportedAtUtc);
  await page.goto(`/money?workflow=owner_rent_report.reject&target=${items.items[0].id}`);
  await page.getByLabel("Reason (required)").fill("Owner withdrew the claim");
  await page.getByLabel("I confirm this lifecycle change", { exact: true }).check();
  await save(page, "Reject owner rent report");
  expect(
    (await get<Schemas["ReceiptPageResponse"]>(request, `/api/rent-receipts?leaseId=${f.lease.id}`))
      .items,
  ).toHaveLength(0);
  await page.goto(`/money?record=report&id=${items.items[0].id}`);
  await page.getByRole("link", { name: "Record correction report", exact: true }).click();
  await expect(page.getByLabel("Owner party id (required)")).toHaveValue(f.owner);
  await expect(page.getByLabel("Received on (required)")).toHaveValue(f.today);
  await page.getByLabel("Amount minor (required)").fill("12300");
  await expect(page.getByLabel("Reported at utc (required)", { exact: true })).toHaveCount(0);
  await save(page, "Record owner rent report");
  const replacement = (
    await get<Schemas["OwnerRentReportPageResponse"]>(
      request,
      `/api/owner-rent-reports?leaseId=${f.lease.id}`,
    )
  ).items.find((item) => item.replacesReportId === items.items[0].id)!;
  expect(replacement.status).toBe("pending");
  expect(replacement.reportedAtUtc).toBe(replacement.createdAt);
  await page.goto(`/money?record=report&id=${replacement.id}`);
  await expect(
    page.getByRole("link", { name: "Review report history", exact: true }),
  ).toBeVisible();
});

test("Owner duplicate creation cannot add income; explicit adoption recovers its original response", async ({
  page,
  request,
}) => {
  const f = await fixture(request),
    synced = await schedule(request, f),
    report = await ownerReport(request, f);
  await upload(request, "owner_rent_report", report.id);
  const receipt = await post<
    Schemas["app__modules__finance__api__router__ReceiptMutationResponse"]
  >(request, "/api/rent-receipts", {
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
  await page.getByLabel("Create a receipt with explicit allocations").check();
  await page.getByLabel("Expectation id (required)").selectOption(synced.items[0].id);
  await page.getByLabel("Amount minor (required)").fill("39999");
  await expect(
    page.getByRole("button", { name: "Save verify owner rent report", exact: true }),
  ).toBeDisabled();
  await page.getByLabel("Amount minor (required)").fill("40000");
  await page.getByLabel("Review note (required)").fill("Reviewed duplicate evidence");
  await page.getByLabel("I confirm this lifecycle change", { exact: true }).check();
  await page.getByRole("button", { name: "Save verify owner rent report", exact: true }).click();
  await expect(
    page.getByRole("region", { name: "Possible duplicate rent receipts", exact: true }),
  ).toBeVisible();
  expect(
    (await get<Schemas["OwnerRentReportResponse"]>(request, `/api/owner-rent-reports/${report.id}`))
      .status,
  ).toBe("pending");
  await page.getByRole("link", { name: "Start explicit adoption review", exact: true }).click();
  const discard = page.getByRole("button", { name: "Discard changes", exact: true });
  if (await discard.isVisible()) await discard.click();
  await page
    .getByRole("combobox", { name: "Existing receipt id", exact: true })
    .selectOption(receipt.id);
  await page.getByLabel("Review note (required)").fill("Explicit adoption of matching receipt");
  await page.getByLabel("I confirm this lifecycle change", { exact: true }).check();
  let calls = 0;
  await page.route(`**/api/owner-rent-reports/${report.id}/verify`, async (route) => {
    calls++;
    await route.fetch();
    await route.abort("failed");
  });
  await page.getByRole("button", { name: "Save verify owner rent report", exact: true }).click();
  await page.getByRole("button", { name: "Check original result", exact: true }).click();
  await expect(page.locator('.saved-item, section[aria-label="Committed result"]')).toBeVisible();
  expect(calls).toBe(1);
  const final = await get<Schemas["OwnerRentReportResponse"]>(
    request,
    `/api/owner-rent-reports/${report.id}`,
  );
  expect(final.verifiedReceiptId).toBe(receipt.id);
  expect(
    (await get<Schemas["ReceiptPageResponse"]>(request, `/api/rent-receipts?leaseId=${f.lease.id}`))
      .items,
  ).toHaveLength(1);
});

test("Owner report evidence archival retains history but cannot remove the last verified evidence", async ({
  page,
  request,
}) => {
  const f = await fixture(request),
    synced = await schedule(request, f),
    report = await ownerReport(request, f);
  await upload(request, "owner_rent_report", report.id);
  await upload(request, "owner_rent_report", report.id);
  await post(request, `/api/owner-rent-reports/${report.id}/verify`, {
    confirmed: true,
    reviewNote: "Available evidence reviewed",
    expectedRevision: 1,
    expectedRentLedgerRevision: 1,
    idempotencyKey: crypto.randomUUID(),
    receiptIdempotencyKey: crypto.randomUUID(),
    allocations: [{ expectationId: synced.items[0].id, amountMinor: 40000 }],
  });
  await page.goto(`/money?record=report&id=${report.id}`);
  await page
    .getByRole("link", { name: "Archive evidence association", exact: true })
    .first()
    .click();
  await page.getByLabel("Reason (required)").fill("Keep one document in historical context");
  await page.getByLabel("I confirm this lifecycle change").check();
  await page.getByRole("button", { name: "Save archive evidence link", exact: true }).click();
  await expect(page.locator('.saved-item, section[aria-label="Committed result"]')).toBeVisible();
  await page.goto(`/money?record=report&id=${report.id}`);
  await page.getByText("Archived evidence history", { exact: true }).click();
  await expect(
    page.getByText("Keep one document in historical context", { exact: false }),
  ).toBeVisible();
  await page.getByRole("link", { name: "Archive evidence association", exact: true }).click();
  await page.getByLabel("Reason (required)").fill("Attempt to archive last available document");
  await page.getByLabel("I confirm this lifecycle change").check();
  await page.getByRole("button", { name: "Save archive evidence link", exact: true }).click();
  await expect(page.getByRole("alert").first()).toBeVisible();
  const after = await get<Schemas["OwnerRentReportResponse"]>(
    request,
    `/api/owner-rent-reports/${report.id}`,
  );
  expect(after.evidenceCount).toBe(1);
  expect(after.financiallyEffective).toBe(true);
  await page.goto(`/money?tab=reports&leaseId=${f.lease.id}`);
  await page.getByRole("combobox", { name: "Report status", exact: true }).selectOption("verified");
  await page.getByRole("combobox", { name: "Report evidence", exact: true }).selectOption("false");
  await page
    .getByRole("combobox", { name: "Linked receipt lifecycle", exact: true })
    .selectOption("active");
  await expect(page.getByText("No records match these filters.", { exact: true })).toBeVisible();
  await page.getByRole("combobox", { name: "Report evidence", exact: true }).selectOption("true");
  await expect(
    page.getByText("No records match these filters.", { exact: true }),
  ).not.toBeVisible();
});

test("Archived historical client owner can report a past payment without creating income", async ({
  page,
  request,
}) => {
  const property = await post<Schemas["PropertyMutationResponse"]>(
    request,
    "/__test__/historical-owner",
    {},
  );
  const ownerId = property.ownerships[0].partyId!;
  const today = new Intl.DateTimeFormat("en-CA", {
    timeZone: "America/Los_Angeles",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date());
  const tenant = await post<Schemas["TenantMutationResponse"]>(request, "/api/tenants", {
    partyKind: "individual",
    displayName: `Historical report tenant ${crypto.randomUUID()}`,
    officialIds: [{ documentType: "passport", issuingCountry: "US", lastFour: "TEST" }],
    expectedRevision: 0,
    idempotencyKey: crypto.randomUUID(),
  });
  const lease = await post<Schemas["LeaseMutationResponse"]>(request, "/api/leases", {
    spaceId: property.spaces[0].id,
    leaseKind: "residential",
    contractStartsOn: property.effectiveLocalDate,
    occupancyStartsOn: today,
    initialTerm: {
      baseRentMinor: 100000,
      currencyCode: "USD",
      paymentFrequency: "monthly",
      paymentDueDay: 1,
      agreedSecurityDepositMinor: 0,
    },
    participants: [{ tenantPartyId: tenant.id, participantRole: "primary_tenant" }],
    expectedLeaseRevision: 0,
    idempotencyKey: crypto.randomUUID(),
  });
  await post(request, `/api/leases/${lease.id}/execute`, {
    confirmed: true,
    executedOn: today,
    expectedLeaseRevision: lease.leaseRevision,
    expectedRevision: property.spaces[0].revision,
    idempotencyKey: crypto.randomUUID(),
  });
  const ended = await request.put(`/api/properties/${property.id}/ownerships`, {
    data: {
      ownerships: [{ ownerKind: "local_operator" }],
      effectiveOn: today,
      expectedPropertyRevision: property.propertyRevision,
      idempotencyKey: crypto.randomUUID(),
    },
  });
  expect(ended.ok(), await ended.text()).toBe(true);
  const party = await get<Schemas["app__modules__parties__api__router__PartyResponse"]>(
    request,
    `/api/parties/${ownerId}`,
  );
  await post(request, `/api/parties/${ownerId}/archive`, {
    confirmed: true,
    expectedRevision: party.revision,
    idempotencyKey: crypto.randomUUID(),
  });
  await page.goto(`/money?workflow=owner_rent_report.create&leaseId=${lease.id}`);
  await page.getByLabel("Received on (required)").fill(property.effectiveLocalDate);
  await page.getByLabel("Owner party id (required)").fill(ownerId);
  await expect(
    page.getByRole("region", { name: "Owner report review", exact: true }),
  ).toContainText("Archived identity — historical selection only");
  await page.getByLabel("Amount minor (required)").fill("12300");
  await page.getByLabel("Payment method kind (required)").selectOption("cash");
  await expect(page.getByLabel("Reported at utc (required)", { exact: true })).toHaveCount(0);
  await save(page, "Record owner rent report");
  const reports = await get<Schemas["OwnerRentReportPageResponse"]>(
    request,
    `/api/owner-rent-reports?leaseId=${lease.id}`,
  );
  expect(reports.items[0].currentOwnerState).toBe("archived");
  expect(reports.items[0].financiallyEffective).toBe(false);
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
  await page.goto(`/money?record=check&id=${checks.items[0].id}`);
  await page.getByRole("button", { name: "Deposit prepaid check", exact: true }).click();
  await page.getByLabel("I confirm this lifecycle change", { exact: true }).check();
  await save(page, "Deposit prepaid check");
  expect(
    (await get<Schemas["ReceiptPageResponse"]>(request, `/api/rent-receipts?leaseId=${f.lease.id}`))
      .items,
  ).toHaveLength(1);
  await page.goto(`/money?record=check&id=${checks.items[0].id}`);
  await page.getByRole("button", { name: "Return prepaid check", exact: true }).click();
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

async function depositFixture(request: APIRequestContext, f: Awaited<ReturnType<typeof fixture>>) {
  const account = await post<Schemas["DepositMutationResponse"]>(
    request,
    `/api/leases/${f.lease.id}/security-deposit`,
    {
      expectedRevision: 0,
      idempotencyKey: crypto.randomUUID(),
      leaseTermId: f.lease.terms[0].id,
    },
  );
  const receipt = await post<
    Schemas["app__modules__finance__api__deposit_router__ReceiptMutationResponse"]
  >(request, `/api/security-deposits/${account.id}/receipts`, {
    expectedRevision: account.depositAccountRevision,
    idempotencyKey: crypto.randomUUID(),
    receivedOn: f.today,
    amount: "400.00",
    currencyCode: "USD",
    receivedByKind: "local_operator",
    receivedFromPartyId: f.tenant.id,
  });
  return { account, receipt };
}

test("deposit interest review uses exact cents and requires renewed approval for an override", async ({
  page,
  request,
}) => {
  const f = await fixture(request),
    { account, receipt } = await depositFixture(request, f);
  const settlement = await post<Schemas["SettlementMutationResponse"]>(
    request,
    `/api/security-deposits/${account.id}/settlements`,
    {
      expectedRevision: receipt.depositAccountRevision,
      idempotencyKey: crypto.randomUUID(),
      settlementDueOn: f.through,
      legalRuleReference: "Operator-entered test rule, not legal advice",
      eligibilityOverrideConfirmed: true,
      eligibilityOverrideReason: "Operator requested early review",
    },
  );
  await page.goto(
    `/money?workflow=finance.deposit_credit.create&target=${account.id}&child=${settlement.id}`,
  );
  await page.getByLabel("Kind (required)").selectOption("interest");
  await page.getByLabel("Amount (required)").fill("1.00");
  await page.getByLabel("Description (required)").fill("Reviewed simple interest");
  await page.getByLabel("Calculator principal", { exact: true }).fill("1000.00");
  await page.getByLabel("Annual rate basis points", { exact: true }).fill("500");
  await page.getByLabel("Starts on", { exact: true }).fill("2025-01-01");
  await page.getByLabel("Ends on", { exact: true }).fill("2025-01-31");
  const review = page.getByRole("region", { name: "Simple interest review", exact: true });
  await expect(review).toContainText("30 days · Calculated interest: USD 4.11");
  await expect(
    page.getByRole("button", { name: "Add settlement credit", exact: true }),
  ).toBeDisabled();
  await review.getByRole("button", { name: "Use calculated interest", exact: true }).click();
  await review
    .getByRole("button", { name: "Confirm interest calculation and applied credit", exact: true })
    .click();
  await page.getByLabel("Annual rate basis points", { exact: true }).fill("600");
  await expect(
    page.getByRole("button", { name: "Add settlement credit", exact: true }),
  ).toBeDisabled();
  await expect(review).toContainText("USD 4.93");
  await page.getByLabel("Amount (required)").fill("5.00");
  await page.getByLabel("Override reason", { exact: true }).fill("Documented applied adjustment");
  await review
    .getByRole("button", { name: "Confirm interest calculation and applied credit", exact: true })
    .click();
  await save(page, "Add settlement credit");
  const current = await get<Schemas["SettlementResponse"]>(
    request,
    `/api/security-deposit-settlements/${settlement.id}`,
  );
  expect(current.credits[0]).toMatchObject({
    amount: "5.00",
    calculatedAmount: "4.93",
    dayCount: 30,
    calculatorPrincipal: "1000.00",
    annualRateBasisPoints: 600,
    overrideReason: "Documented applied adjustment",
  });
  await page.goto(`/money?record=settlement&id=${settlement.id}`);
  await page.getByText("Interest calculation", { exact: true }).click();
  await expect(page.getByRole("region", { name: "Credits", exact: true })).toContainText(
    "Annual interest rate",
  );
  await expect(page.getByRole("region", { name: "Credits", exact: true })).toContainText("6%");
  await expect(page.getByRole("region", { name: "Credits", exact: true })).toContainText(
    "USD 4.93",
  );
  await expect(page.getByRole("region", { name: "Money record", exact: true })).toContainText(
    "Operator-entered test rule",
  );
  await page.setViewportSize({ width: 390, height: 900 });
  for (const theme of ["light", "dark"]) {
    await page.goto("/settings");
    await page
      .getByRole("radio", { name: theme === "dark" ? "Dark" : "Light", exact: true })
      .check();
    await page.getByRole("button", { name: "Save preferences", exact: true }).click();
    await expect(page.getByText("Preferences saved.")).toBeVisible();
    await page.goto(`/money?record=settlement&id=${settlement.id}`);
    await page.getByText("Interest calculation", { exact: true }).click();
    await expect(page.getByRole("region", { name: "Credits", exact: true })).toContainText(
      "USD 4.93",
    );
    await page.evaluate(axe.source);
    expect(
      await page.evaluate(async () =>
        (
          await window.axe.run(document, {
            runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21aa"] },
          })
        ).violations.map((item) => item.id),
      ),
    ).toEqual([]);
  }
});

test("deposit Party selection reviews duplicate receipts and retains void replacement history", async ({
  page,
  request,
}) => {
  const f = await fixture(request),
    { account, receipt } = await depositFixture(request, f);
  await page.goto(`/money?workflow=finance.deposit_receipt.create&target=${account.id}`);
  await page.getByLabel("Party search", { exact: true }).fill(f.tenant.displayName);
  await page.getByRole("button", { name: "Search deposit Parties", exact: true }).click();
  await page
    .getByRole("button", { name: `Use Party ${f.tenant.displayName}`, exact: true })
    .click();
  await page.getByLabel("Received on (required)").fill(f.today);
  await page.getByLabel("Amount (required)").fill("400.00");
  const duplicate = page.getByRole("region", {
    name: "Possible duplicate deposit payments",
    exact: true,
  });
  await expect(duplicate).toContainText("USD 400.00");
  await expect(
    page.getByRole("button", { name: "Record deposit receipt", exact: true }),
  ).toBeDisabled();
  await duplicate
    .getByRole("button", { name: "Record separate deposit payment", exact: true })
    .click();
  await save(page, "Record deposit receipt");
  await page.goto(
    `/money?workflow=finance.deposit_receipt.void&target=${account.id}&child=${receipt.id}`,
  );
  await page.getByLabel("I confirm this lifecycle change", { exact: true }).check();
  await page.getByLabel("Reason (required)").fill("Receipt correction preserves history");
  await save(page, "Void deposit receipt");
  await page.goto(`/money?record=deposit&id=${account.id}`);
  await page.getByRole("link", { name: "Record replacement deposit receipt", exact: true }).click();
  await expect(page.getByLabel("Amount (required)")).toHaveValue("400.00");
  await page.getByRole("button", { name: "Record separate deposit payment", exact: true }).click();
  await save(page, "Record deposit receipt");
  const receipts = await get<
    Schemas["app__modules__finance__api__deposit_router__ReceiptResponse"][]
  >(request, `/api/security-deposits/${account.id}/receipts`);
  expect(receipts).toHaveLength(3);
  expect(receipts.find((item) => item.replacesReceiptId === receipt.id)?.lifecycleStatus).toBe(
    "active",
  );
});

test("deposit duplicate refunds require separate-payment review and preserve replacement lineage", async ({
  page,
  request,
}) => {
  const f = await fixture(request),
    { account, receipt } = await depositFixture(request, f);
  const draft = await post<Schemas["SettlementMutationResponse"]>(
    request,
    `/api/security-deposits/${account.id}/settlements`,
    {
      expectedRevision: receipt.depositAccountRevision,
      idempotencyKey: crypto.randomUUID(),
      settlementDueOn: f.through,
      eligibilityOverrideConfirmed: true,
      eligibilityOverrideReason: "Early settlement requested by operator",
    },
  );
  const approved = await post<Schemas["SettlementMutationResponse"]>(
    request,
    `/api/security-deposit-settlements/${draft.id}/approve`,
    {
      expectedRevision: draft.depositAccountRevision,
      idempotencyKey: crypto.randomUUID(),
      confirmed: true,
    },
  );
  const first = await post<
    Schemas["app__modules__finance__api__deposit_router__RefundMutationResponse"]
  >(request, `/api/security-deposit-settlements/${draft.id}/refunds`, {
    expectedRevision: approved.depositAccountRevision,
    idempotencyKey: crypto.randomUUID(),
    paidOn: f.today,
    amount: "100.00",
    currencyCode: "USD",
    recipientPartyId: f.tenant.id,
  });
  await page.goto(
    `/money?workflow=finance.deposit_refund.create&target=${account.id}&child=${draft.id}`,
  );
  await page.getByLabel("Recipient party id (required)").fill(f.tenant.id);
  await page.getByLabel("Paid on (required)").fill(f.today);
  await page.getByLabel("Amount (required)").fill("100.00");
  const duplicate = page.getByRole("region", {
    name: "Possible duplicate deposit payments",
    exact: true,
  });
  await expect(
    page.getByRole("button", { name: "Record deposit refund", exact: true }),
  ).toBeDisabled();
  await duplicate
    .getByRole("button", { name: "Record separate deposit payment", exact: true })
    .click();
  await save(page, "Record deposit refund");
  await page.goto(
    `/money?workflow=finance.deposit_refund.void&target=${account.id}&child=${first.id}`,
  );
  await page.getByLabel("I confirm this lifecycle change", { exact: true }).check();
  await page.getByLabel("Reason (required)").fill("Correct recipient payment evidence");
  await save(page, "Void deposit refund");
  await page.goto(`/money?record=settlement&id=${draft.id}`);
  await page.getByRole("link", { name: "Record replacement deposit refund", exact: true }).click();
  await expect(page.getByLabel("Amount (required)")).toHaveValue("100.00");
  // Another identical active refund still requires explicit separate-payment confirmation.
  await page.getByRole("button", { name: "Record separate deposit payment", exact: true }).click();
  await save(page, "Record deposit refund");
  const current = await get<Schemas["SettlementResponse"]>(
    request,
    `/api/security-deposit-settlements/${draft.id}`,
  );
  expect(current.refunds).toHaveLength(3);
  expect(current.refunds.find((item) => item.replacesRefundId === first.id)?.voidedAt).toBeNull();
  await page.goto(`/money?tab=deposits&propertyId=${f.property.id}`);
  await page
    .getByRole("combobox", { name: "Settlement state", exact: true })
    .selectOption("approved");
  await page
    .getByRole("combobox", { name: "Unresolved deposit balance", exact: true })
    .selectOption("true");
  await expect(page.getByRole("region", { name: "Deposits records", exact: true })).toContainText(
    "USD 400.00",
  );
});

test("draft deposit evidence can be archived without losing its file or deduction history", async ({
  page,
  request,
}) => {
  const f = await fixture(request),
    { account, receipt } = await depositFixture(request, f);
  const draft = await post<Schemas["SettlementMutationResponse"]>(
    request,
    `/api/security-deposits/${account.id}/settlements`,
    {
      expectedRevision: receipt.depositAccountRevision,
      idempotencyKey: crypto.randomUUID(),
      settlementDueOn: f.through,
      eligibilityOverrideConfirmed: true,
      eligibilityOverrideReason: "Review retained evidence",
    },
  );
  const deduction = await post<Schemas["DeductionLineMutationResponse"]>(
    request,
    `/api/security-deposit-settlements/${draft.id}/deductions`,
    {
      expectedRevision: draft.depositAccountRevision,
      idempotencyKey: crypto.randomUUID(),
      category: "damage",
      amount: "3.00",
      description: "Explicit operator deduction",
      rationale: "Review attachment before approval",
    },
  );
  await page.goto(
    `/money?workflow=file.upload&entityType=security_deposit_deduction&entityId=${deduction.id}&accountId=${account.id}`,
  );
  await page.getByLabel("Evidence file (required)").setInputFiles({
    name: "deduction-proof.txt",
    mimeType: "text/plain",
    buffer: Buffer.from("Operator-reviewed evidence"),
  });
  await save(page, "Attach supporting evidence");
  await page.goto(`/money?record=settlement&id=${draft.id}`);
  await page
    .getByRole("link", { name: "Archive deposit evidence association", exact: true })
    .click();
  await page.getByLabel("I confirm this lifecycle change", { exact: true }).check();
  await page.getByLabel("Reason (required)").fill("Wrong association, keep the retained file");
  await page.getByRole("button", { name: "Save archive evidence link", exact: true }).click();
  await expect(page.locator('.saved-item, section[aria-label="Committed result"]')).toBeVisible();
  const current = await get<Schemas["SettlementResponse"]>(
    request,
    `/api/security-deposit-settlements/${draft.id}`,
  );
  const evidence = current.deductions[0].evidence[0];
  expect(evidence).toMatchObject({
    originalName: "deduction-proof.txt",
    available: true,
    archiveReason: "Wrong association, keep the retained file",
  });
  expect(evidence.archivedAt).not.toBeNull();
  await page.goto(`/money?record=settlement&id=${draft.id}`);
  await expect(
    page.getByRole("link", { name: "Archive deposit evidence association", exact: true }),
  ).toHaveCount(0);
  await page.getByText("Archived deduction evidence history", { exact: true }).click();
  await expect(
    page.locator("details").filter({ hasText: "Archived deduction evidence history" }),
  ).toContainText("deduction-proof.txt");
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
  await page.goto(`/money?record=deposit&id=${account.id}`);
  await expect(
    page.getByRole("button", { name: "Record deposit receipt", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Prepare deposit settlement", exact: true }).click();
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
  await page.goto(`/money?record=settlement&id=${updated.settlementId}`);
  await page.getByRole("button", { name: "Approve deposit settlement", exact: true }).click();
  await page.getByLabel("I confirm this lifecycle change", { exact: true }).check();
  await page.getByLabel("Zero dollar closure confirmed", { exact: true }).check();
  await save(page, "Approve deposit settlement");
  await page.goto(`/money?record=settlement&id=${updated.settlementId}`);
  await expect(
    page.getByRole("button", { name: "Record deposit refund", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Complete deposit settlement", exact: true }).click();
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
  await page.getByRole("button", { name: "Preview deduction source", exact: true }).click();
  await expect(
    page.getByRole("region", { name: "Deduction source review", exact: true }),
  ).toContainText("Active source");
  await page
    .getByRole("button", { name: "Confirm reviewed deduction source", exact: true })
    .click();
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
  await page.getByRole("link", { name: "Resume: Delete settlement credit", exact: true }).click();
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
  await expect(page.getByLabel("Expectation id (required)")).toHaveValue(check.expectationId);
  await expect(page.getByLabel("Payer party id (required)")).toHaveValue(f.tenant.id);
  await expect(page.getByLabel("Received on (required)")).toHaveValue(f.today);
  await expect(page.getByLabel("Check dated on (required)")).toHaveValue(checkOn);
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

test("future check queue filters preserve eligibility and reminder context without income", async ({
  page,
  request,
}) => {
  const f = await fixture(request),
    synced = await schedule(request, f);
  const checkOn = new Date(Date.parse(`${f.today}T12:00:00Z`) + 86400000)
    .toISOString()
    .slice(0, 10);
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
      maskedReference: "Check •••• 9182",
    },
  );
  expect(check.depositEligibility).toBe("not_yet_eligible");
  await page.goto(`/money?record=check&id=${check.id}`);
  const review = page.getByRole("region", { name: "Prepaid check review" });
  await expect(review.getByText(/Not yet eligible:/)).toBeVisible();
  await expect(review.getByText("America/Los_Angeles", { exact: true })).toBeVisible();
  await expect(review.getByRole("link", { name: "Deposit reminder Task" })).toHaveAttribute(
    "href",
    `/tasks/${check.reminderTaskId}`,
  );
  await expect(page.getByRole("link", { name: "Deposit prepaid check", exact: true })).toHaveCount(
    0,
  );
  await page.goto(`/money?tab=checks&leaseId=${f.lease.id}`);
  await page
    .getByRole("combobox", { name: "Check lifecycle", exact: true })
    .selectOption("scheduled");
  await page
    .getByRole("combobox", { name: "Deposit eligibility", exact: true })
    .selectOption("not_yet_eligible");
  await expect(page.locator(`a[href*="id=${check.id}"]`)).toBeVisible();
  await page
    .getByRole("combobox", { name: "Deposit eligibility", exact: true })
    .selectOption("eligible");
  await expect(page.locator(`a[href*="id=${check.id}"]`)).toHaveCount(0);
  expect(
    (await get<Schemas["ReceiptPageResponse"]>(request, `/api/rent-receipts?leaseId=${f.lease.id}`))
      .items,
  ).toHaveLength(0);
});

test("lost check deposit response recovers the original correlated receipt without another dispatch", async ({
  page,
  request,
}) => {
  const f = await fixture(request),
    synced = await schedule(request, f);
  const receivedOn = new Date(Date.parse(`${f.today}T12:00:00Z`) - 86400000)
    .toISOString()
    .slice(0, 10);
  const check = await post<Schemas["PrepaidCheckMutationResponse"]>(
    request,
    "/api/prepaid-checks",
    {
      expectedRevision: 1,
      idempotencyKey: crypto.randomUUID(),
      expectationId: synced.items[0].id,
      payerPartyId: f.tenant.id,
      receivedOn,
      checkDatedOn: f.today,
    },
  );
  await page.goto(
    `/money?workflow=finance.prepaid_check.deposit&target=${f.lease.id}&child=${check.id}`,
  );
  await page.getByLabel("I confirm this lifecycle change", { exact: true }).check();
  let calls = 0;
  let original: Schemas["PrepaidCheckMutationResponse"] | undefined;
  await page.route(`**/api/prepaid-checks/${check.id}/deposit`, async (route) => {
    calls++;
    original = (await (await route.fetch()).json()) as Schemas["PrepaidCheckMutationResponse"];
    await route.abort("failed");
  });
  await page.getByRole("button", { name: "Save deposit prepaid check", exact: true }).click();
  await page.getByRole("button", { name: "Check original result" }).click();
  await expect(
    page.getByText("This is the original committed response.", { exact: true }),
  ).toBeVisible();
  expect(calls).toBe(1);
  const receipts = await get<Schemas["ReceiptPageResponse"]>(
    request,
    `/api/rent-receipts?leaseId=${f.lease.id}`,
  );
  expect(receipts.items).toHaveLength(1);
  expect(receipts.items[0].id).toBe(original?.receiptId);
  expect(receipts.items[0].allocations).toHaveLength(1);
  expect(receipts.items[0].paymentMethodKind).toBe("check");
  expect(
    (await get<Schemas["PrepaidCheckResponse"]>(request, `/api/prepaid-checks/${check.id}`))
      .reminderStatus,
  ).toBe("dismissed");
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
  await page.getByLabel("Amount (USD cents) (required)").nth(0).fill("20000");
  await page.getByLabel("Amount (USD cents) (required)").nth(1).fill("20000");
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
  await expect(page.getByText(/^Unfinished form saved/)).toBeVisible();
  const saved = (await (await savedResponse).json()) as Schemas["RecoveryResponse"];
  await page.goto("/settings/recovery");
  await page
    .getByRole("link", { name: "Resume: Attach supporting evidence", exact: true })
    .and(page.locator(`[href*="resume=${saved.id}"]`))
    .click();
  await page.getByLabel("Evidence file (required)").setInputFiles(bytes);
  await save(page, "Attach supporting evidence");
  await page.getByRole("link", { name: "Back to evidence", exact: true }).click();
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
  await expect(page.getByRole("region", { name: "Rent and expenses", exact: true })).toContainText(
    "USD 120.01",
  );
  expect(summaries).toBe(1);
  await expect(page.getByRole("region", { name: "Rent and expenses", exact: true })).toContainText(
    "Rent less net expenses",
  );
  expect(details).toBe(0);
  await page.getByText("Explore the records behind these totals", { exact: true }).click();
  await page.getByRole("link", { name: "View expenses paid records", exact: true }).click();
  await expect(page.getByText("Total USD 120.01", { exact: false })).toBeVisible();
  await expect(page.locator(".reporting-source-row .reporting-contribution")).toContainText(
    "USD 120.01",
  );
  await page.getByRole("link", { name: "View source record", exact: true }).click();
  await expect(page.getByRole("region", { name: "Money record", exact: true })).toContainText(
    "Actual paid repair",
  );
  expect(details).toBe(1);
});

test("reporting drill-down retains its period and scope without reusing another collection cursor", async ({
  page,
  request,
}) => {
  const f = await fixture(request);
  await expense(request, f);
  const filters = new URLSearchParams({
    fromOn: f.today,
    throughOn: f.today,
    propertyState: "all",
    propertyIds: f.property.id,
  });
  const response = await request.get(`/api/money/properties?${filters}`);
  expect(response.ok(), await response.text()).toBe(true);
  const summary =
    (await response.json()) as Schemas["app__modules__finance__api__money_router__PropertyPageResponse"];
  await page.route("**/api/money/properties?**", (route) => route.fulfill({ json: summary }));
  await page.goto(
    `/money?tab=reporting&propertyId=${f.property.id}&fromOn=${f.today}&throughOn=${f.today}&propertyState=all&cursor=property-page-cursor`,
  );
  const reporting = page.getByRole("region", { name: "Money reporting", exact: true });
  const propertyLink = reporting.getByRole("link", {
    name: f.property.displayName,
    exact: true,
  });
  await expect(propertyLink).toBeVisible();
  await expect(
    reporting
      .getByRole("article")
      .filter({
        has: page.getByRole("link", { name: f.property.displayName, exact: true }),
      })
      .locator(".record-pill"),
  ).toHaveText("Active");
  const propertyHref = new URL((await propertyLink.getAttribute("href"))!, page.url());
  expect(propertyHref.searchParams.get("propertyId")).toBe(f.property.id);
  expect(propertyHref.searchParams.get("fromOn")).toBe(f.today);
  expect(propertyHref.searchParams.get("throughOn")).toBe(f.today);
  expect(propertyHref.searchParams.has("cursor")).toBe(false);
  const obligation = reporting.getByRole("link", {
    name: "Current recorded deposit obligation",
    exact: true,
  });
  await reporting.getByText("Explore the records behind these totals", { exact: true }).click();
  const href = new URL((await obligation.getAttribute("href"))!, page.url());
  expect(href.searchParams.has("cursor")).toBe(false);
  expect(href.searchParams.get("sourceRevision")).toBe(summary.summary.sourceRevision);
  const accountsRequest = page.waitForRequest((item) =>
    item.url().includes("/api/money/deposit-accounts?"),
  );
  await obligation.click();
  const url = new URL((await accountsRequest).url());
  expect(url.searchParams.has("cursor")).toBe(false);
  expect(url.searchParams.get("fromOn")).toBe(f.today);
  expect(url.searchParams.get("propertyIds")).toBe(f.property.id);
  await expect(reporting.getByText(/deposit accounts/)).toBeVisible();
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
  await expect(page.getByRole("region", { name: "Rent and expenses", exact: true })).toBeVisible();
});
