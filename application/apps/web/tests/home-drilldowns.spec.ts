import { expect, test, type APIRequestContext } from "@playwright/test";
import type { components } from "@epm/contracts/generated";
type Schema = components["schemas"];
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
async function property(request: APIRequestContext, tokyo = false) {
  return post<Schema["PropertyMutationResponse"]>(request, "/api/properties", {
    displayName: `Drilldown ${crypto.randomUUID()}`,
    addressLine1: "10 Main Street",
    city: tokyo ? "Tokyo" : "Portland",
    countryCode: tokyo ? "JP" : "US",
    ...(tokyo ? {} : { region: "OR", postalCode: "97201" }),
    propertyType: "single_family_home",
    ownerships: [{ ownerKind: "local_operator" }],
    expectedPropertyRevision: 0,
    idempotencyKey: crypto.randomUUID(),
  });
}
async function expense(request: APIRequestContext, home: Schema["PropertyMutationResponse"]) {
  const categories = await get<
    Schema["app__modules__finance__api__expense_router__CategoryResponse"][]
  >(request, "/api/expense-categories");
  return post<Schema["ExpenseMutationResponse"]>(request, "/api/expenses", {
    expectedRevision: 0,
    idempotencyKey: crypto.randomUUID(),
    propertyId: home.id,
    categoryId: categories[0].id,
    payeeName: "Recorded merchant",
    paidByKind: "local_operator",
    paidOn: home.effectiveLocalDate,
    amount: "44.56",
    currencyCode: "USD",
    description: "Recorded paid work",
  });
}
function period(home: Schema["PropertyMutationResponse"]) {
  const day = home.effectiveLocalDate;
  return `fromOn=${day.slice(0, 7)}-01&throughOn=${new Date(Date.UTC(Number(day.slice(0, 4)), Number(day.slice(5, 7)), 0)).toISOString().slice(0, 10)}`;
}
const labels = {
  rentReceived: "Rent received",
  expensesPaid: "Expenses paid",
  expenseRefundsReceived: "Expense refunds received",
  netRecordedExpenses: "Net recorded expenses",
  operatingRemainder: "Rent less net expenses",
};

test("every Home money metric opens matching Finance contributions with its explicit period and archived scope", async ({
  page,
  request,
}) => {
  const home = await property(request),
    paid = await expense(request, home);
  await post(request, `/api/expenses/${paid.id}/refunds`, {
    expectedRevision: paid.expenseRevision,
    idempotencyKey: crypto.randomUUID(),
    receivedOn: home.effectiveLocalDate,
    amount: "4.56",
    currencyCode: "USD",
  });
  await post(request, `/api/properties/${home.id}/archive`, {
    expectedPropertyRevision: home.propertyRevision,
    idempotencyKey: crypto.randomUUID(),
    confirmed: true,
  });
  const query = `propertyId=${home.id}&${period(home)}`;
  const snapshot = await get<Schema["HomeResponse"]>(request, `/api/operator/home?${query}`);
  if (snapshot.money.status !== "available") throw new Error("Money fixture unavailable");
  expect(
    snapshot.money.metrics.find((item) => item.target.metric === "netRecordedExpenses")?.amount,
  ).toBe("40.00");
  for (const metric of snapshot.money.metrics) {
    await page.goto(`/home?${query}`);
    const region = page.getByRole("region", { name: "Recorded money", exact: true });
    await expect(region).toContainText("archived-property history");
    const response = page.waitForResponse(
      (result) => new URL(result.url()).pathname === "/api/money/sources",
    );
    await region
      .getByRole("link", {
        name: `USD ${metric.amount} — View ${labels[metric.target.metric]} sources`,
        exact: true,
      })
      .click();
    const result = await response;
    expect(result.ok(), await result.text()).toBe(true);
    const data =
      (await result.json()) as Schema["app__modules__finance__api__money_router__SourcePageResponse"];
    expect(data.total).toBe(metric.amount);
    const url = new URL(result.url());
    expect(url.searchParams.get("propertyState")).toBe("all");
    expect(url.searchParams.get("sourceRevision")).toBe(snapshot.money.capture.sourceRevision);
    expect(url.searchParams.get("fromOn")).toBe(metric.target.fromOn);
    expect(url.searchParams.get("throughOn")).toBe(metric.target.throughOn);
    expect(url.searchParams.getAll("propertyIds")).toEqual([home.id]);
    await expect(page.getByRole("region", { name: "Money reporting", exact: true })).toContainText(
      `${data.matchingTotal} source records · Total USD ${metric.amount}`,
    );
    if (data.items.length)
      await expect(
        page.getByRole("link", { name: "View source record", exact: true }).first(),
      ).toBeVisible();
    else await expect(page.getByText("No records in this reporting view.")).toBeVisible();
    await expect(page.getByText(/not profit, bank balance or amounts due to owners/)).toBeVisible();
    await page
      .getByRole("link", { name: "Return to Home collection or preview", exact: true })
      .click();
    await expect(page).toHaveURL(new RegExp(`propertyId=${home.id}`));
  }
});

test("changed money sources require restart rather than substituting a new total or zero", async ({
  page,
  request,
}) => {
  const home = await property(request);
  await page.goto(`/home?propertyId=${home.id}&${period(home)}`);
  const region = page.getByRole("region", { name: "Recorded money", exact: true });
  const link = region.getByRole("link", {
    name: "USD 0.00 — View Expenses paid sources",
    exact: true,
  });
  await expect(link).toBeVisible();
  await expense(request, home);
  await link.click();
  await expect(page.getByRole("alert")).toContainText("amounts have not been replaced with zero");
  await page
    .getByRole("button", { name: "Restart reporting with these filters", exact: true })
    .click();
  await expect(page.getByRole("region", { name: "Money reporting", exact: true })).toContainText(
    "44.56",
  );
  expect(new URL(page.url()).searchParams.get("propertyId")).toBe(home.id);
  expect(new URL(page.url()).searchParams.get("fromOn")).toBe(
    `${home.effectiveLocalDate.slice(0, 7)}-01`,
  );
});

test("vacant and unknown totals open exact active-space views with frozen pages and current source return", async ({
  page,
  request,
}) => {
  const vacant = await property(request),
    unknown = await property(request);
  const classified = await request.put(`/api/spaces/${vacant.spaces[0].id}/classification`, {
    data: {
      expectedRevision: vacant.spaces[0].revision,
      idempotencyKey: crypto.randomUUID(),
      occupancy: { occupancyStatus: "vacant", effectiveOn: vacant.effectiveLocalDate },
    },
  });
  expect(classified.ok(), await classified.text()).toBe(true);
  for (const [home, kind, label] of [
    [vacant, "vacant", "View vacant rental units"],
    [unknown, "unknown", "View unknown occupancy"],
  ] as const) {
    await page.goto(`/home?propertyId=${home.id}`);
    const region = page.getByRole("region", { name: "Inventory", exact: true });
    await region.getByRole("link", { name: `1 — ${label}`, exact: true }).click();
    const inventory = page.getByRole("region", { name: "Home rental-unit inventory", exact: true });
    await expect(inventory).toContainText(`1 matching ${kind} rental units`);
    await expect(inventory).toContainText("Active properties and rental units only.");
    await expect(inventory).toContainText(home.displayName);
    await expect(inventory.locator(".inventory-result-card .record-pill")).toHaveText(
      kind === "unknown" ? "Needs occupancy classification" : "Vacant",
    );
    await expect(inventory.locator(".inventory-result-card h3")).toHaveText(home.displayName);
    const back = page.url();
    await inventory
      .getByRole("link", { name: "Review occupancy and leasing status", exact: true })
      .click();
    await expect(page).toHaveURL(new RegExp(`/properties/${home.id}/units`));
    await page
      .getByRole("link", { name: "Return to Home collection or preview", exact: true })
      .click();
    await expect(page).toHaveURL(back);
  }
  await page.goto(`/home/inventory?occupancy=unknown&limit=1`);
  const seen: string[] = [];
  while (true) {
    const inventory = page.getByRole("region", { name: "Home rental-unit inventory", exact: true });
    const current = inventory.getByRole("link", {
      name: "Review occupancy and leasing status",
      exact: true,
    });
    await expect(current).toHaveCount(1);
    seen.push((await current.getAttribute("href"))!);
    const next = page.getByRole("link", { name: "Next inventory page", exact: true });
    if (!(await next.count())) break;
    const loaded = page.waitForResponse(
      (result) => new URL(result.url()).pathname === "/api/operator/home/inventory",
    );
    await next.click();
    await loaded;
  }
  expect(new Set(seen).size).toBe(seen.length);
  expect(seen).toContain(`/properties/${unknown.id}/units`);
  expect(seen).not.toContain(`/properties/${vacant.id}/units`);
});

test("inventory conflicts and provider failure never look empty, while a successful zero does", async ({
  page,
  request,
}) => {
  const home = await property(request);
  await page.goto(`/home?propertyId=${home.id}`);
  const link = page.getByRole("link", { name: "1 — View unknown occupancy", exact: true });
  await expect(link).toBeVisible();
  await expense(request, home);
  await link.click();
  await expect(page.getByRole("alert")).toContainText("Inventory changed");
  await page
    .getByRole("button", { name: "Restart inventory with current filters", exact: true })
    .click();
  await expect(
    page.getByRole("region", { name: "Home rental-unit inventory", exact: true }),
  ).toContainText("1 matching unknown rental units");
  await page.route("**/api/operator/home/inventory?*", (route) =>
    route.fulfill({
      status: 503,
      json: { detail: { code: "source_unavailable", message: "Storage unavailable" } },
    }),
  );
  await page.goto(`/home/inventory?occupancy=vacant&propertyId=${home.id}`);
  await expect(page.getByRole("alert")).toContainText("No count can be inferred");
  await expect(page.getByText("No matching rental units at this capture.")).toHaveCount(0);
  await page.unroute("**/api/operator/home/inventory?*");
  await page
    .getByRole("button", { name: "Restart inventory with current filters", exact: true })
    .click();
  await expect(page.getByText("No matching rental units at this capture.")).toBeVisible();
});

test("coverage resolves through the actual Space source and acknowledging review does not fill gaps", async ({
  page,
  request,
}) => {
  const home = await property(request);
  await page.goto(`/home/collections/information_review?propertyId=${home.id}`);
  await page.getByRole("button", { name: /occupancy information/ }).click();
  await page.getByRole("link", { name: "Review information", exact: true }).click();
  await expect(page.getByText(/Review occupancy and leasing status\. If either/)).toBeVisible();
  const source = page.getByRole("link", {
    name: "Set occupancy and leasing status",
    exact: true,
  });
  const classificationUrl = `/properties?workflow=portfolio.space.classify&target=${home.spaces[0].id}`;
  await expect(source).toHaveAttribute("href", classificationUrl);
  await page.getByRole("button", { name: "Add review note", exact: true }).click();
  await page.getByLabel("Review reason").fill("Acknowledged missing recorded classification");
  await page.getByRole("button", { name: "Record review", exact: true }).click();
  await expect(page.getByText(/Original review .*missing required information/)).toBeVisible();
  await expect(
    page.getByRole("region", { name: "occupancy information review", exact: true }),
  ).toContainText("missing required information");
  await source.click();
  await expect(page).toHaveURL(classificationUrl);
  await expect(page.getByRole("heading", { name: "Classify home", exact: true })).toBeVisible();
  await expect(page.getByText(home.displayName, { exact: true })).toBeVisible();
});

test("cross-zone agenda uses operator local time and retains source time-zone context", async ({
  page,
  request,
}) => {
  const homes = [await property(request), await property(request, true)];
  const starts = new Date(Date.now() + 3600000).toISOString();
  for (const home of homes) {
    const issue = await post<Schema["IssueCommandResponse"]>(request, "/api/maintenance-issues", {
      propertyId: home.id,
      summary: `Cross-zone ${home.id}`,
      description: "Review appointment context",
      category: "plumbing",
      priority: "normal",
      reportedAtUtc: new Date(Date.now() - 60000).toISOString(),
      reporter: { role: "manager", subjectKind: "local_operator" },
      expectedRevision: 0,
      idempotencyKey: crypto.randomUUID(),
    });
    await post(request, `/api/maintenance-issues/${issue.id}/appointments`, {
      startsAtUtc: starts,
      endsAtUtc: new Date(Date.now() + 7200000).toISOString(),
      purpose: "Cross-zone inspection",
      expectedRevision: issue.revision,
      idempotencyKey: crypto.randomUUID(),
    });
  }
  await page.goto("/home/collections/appointments");
  const agenda = page.getByRole("region", { name: "Calendar and appointments", exact: true });
  for (const home of homes) {
    const row = agenda.getByRole("button", { name: new RegExp(`Cross-zone ${home.id}`) });
    const local = await page.evaluate(
      (instant) =>
        new Intl.DateTimeFormat(undefined, {
          dateStyle: "medium",
          timeStyle: "short",
        }).format(new Date(instant)),
      starts,
    );
    await expect(row).toContainText(local);
    await expect(row).toContainText(home.timeZone);
    await row.click();
  }
  await expect(agenda.getByRole("link", { name: "View", exact: true })).toHaveCount(2);
});
