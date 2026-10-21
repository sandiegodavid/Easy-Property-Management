// Navigation coverage for shell and workspace paths the topical suites reach
// only by deep link, or not at all: the sidebar tour, the search entry and
// its shortcut, the skip link, owner workspace tabs, the property documents
// tab, Money tab clicks, owners directory search, and the settings index.
import { expect, test, type APIRequestContext } from "@playwright/test";
import type { components } from "@epm/contracts/generated";

type Schema = components["schemas"];
test.use({ extraHTTPHeaders: { Origin: "http://127.0.0.1:18744" } });

async function post<T>(request: APIRequestContext, path: string, data: unknown): Promise<T> {
  const response = await request.post(path, { data });
  expect(response.ok(), await response.text()).toBe(true);
  return (await response.json()) as T;
}

async function propertyWithOwner(
  request: APIRequestContext,
  propertyName: string,
  ownerName: string,
) {
  const property = await post<Schema["PropertyMutationResponse"]>(request, "/api/properties", {
    displayName: propertyName,
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
        inlineParty: { partyKind: "individual", displayName: ownerName },
      },
    ],
  });
  return { property, ownerId: property.ownerships[0].partyId!, ownerName };
}

test("sidebar tour opens every primary destination and Settings", async ({ page }) => {
  await page.goto("/home");
  const nav = page.getByRole("navigation", { name: "Primary navigation", exact: true });
  for (const [label, url, heading] of [
    ["Properties", "/properties", "Properties"],
    ["Owners", "/owners", "Owners"],
    ["Tenants", "/tenants", "Tenants"],
    ["Leasing", "/leasing", "Leasing"],
    ["Money", "/money", "Money"],
    ["Maintenance", "/maintenance", "Maintenance"],
    ["Providers", "/providers", "Providers"],
    ["Home", "/home", "Your day, in view"],
  ] as const) {
    await nav.getByRole("link", { name: label, exact: true }).click();
    await expect(page).toHaveURL(url);
    await expect(page.locator("#workspace-content h2").first()).toHaveText(heading);
  }
  await page.getByRole("link", { name: "Settings", exact: true }).click();
  await expect(page).toHaveURL("/settings");
  await expect(page.locator("#workspace-content h2").first()).toHaveText(
    "Appearance and navigation",
  );
});

test("search entry click reaches Search and Ctrl/Cmd+K focuses the entry", async ({ page }) => {
  await page.goto("/properties");
  await page.getByRole("link", { name: "Search (Ctrl/⌘ K)", exact: true }).click();
  await expect(page).toHaveURL("/search");
  await expect(page.locator("#workspace-content h2").first()).toHaveText("Search");
  await page.goto("/properties");
  await page.keyboard.press("Control+k");
  await expect(page.locator("#search-entry")).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL("/search");
});

test("skip link moves focus to the workspace content", async ({ page }) => {
  await page.goto("/home");
  await page.getByRole("link", { name: "Skip to content", exact: true }).focus();
  await page.keyboard.press("Enter");
  await expect(page.locator("#workspace-content")).toBeFocused();
});

test("owner workspace tabs open every section and View in Money keeps the owner", async ({
  page,
  request,
}) => {
  const token = crypto.randomUUID().slice(0, 8);
  const ownerName = `Owner Tabs ${token}`;
  const { ownerId } = await propertyWithOwner(request, `Owner tabs ${token}`, ownerName);
  await page.goto(`/owners/${ownerId}/overview`);
  await expect(page.getByText("Person · Active", { exact: true })).toBeVisible();
  await expect(page.locator("#workspace-content")).not.toContainText("Source:");
  const money = page.getByRole("button", { name: "View in Money", exact: true });
  await expect(
    page.locator(".directory-heading").getByRole("button", { name: "View in Money" }),
  ).toBeVisible();
  await expect(page.getByRole("link", { name: "View in Money", exact: true })).toHaveCount(0);
  const tabs = page.getByRole("navigation", { name: "owner sections", exact: true });
  await expect(tabs.getByRole("link")).toHaveText([
    "Overview",
    "Properties",
    "Leases",
    "Money",
    "Maintenance",
    "Conversations",
    "Details",
  ]);
  for (const [section, label] of [
    ["properties", "Properties"],
    ["leases", "Leases"],
    ["money", "Money"],
    ["maintenance", "Maintenance"],
    ["conversations", "Conversations"],
    ["details", "Details"],
    ["overview", "Overview"],
  ]) {
    await tabs.getByRole("link", { name: label, exact: true }).click();
    await expect(page).toHaveURL(new RegExp(`/owners/${ownerId}/${section}([?#]|$)`));
    await expect(tabs.getByRole("link", { name: label, exact: true })).toHaveAttribute(
      "aria-current",
      "page",
    );
    await expect(page.locator("#workspace-content")).toBeVisible();
    await expect(page.locator("#workspace-content").getByRole("heading", { level: 2 })).toHaveText([
      ownerName,
    ]);
  }
  await money.click();
  await expect(page).toHaveURL(`/money?ownerId=${ownerId}`);
});

test("property documents tab opens the documents section", async ({ page, request }) => {
  const property = await post<Schema["PropertyMutationResponse"]>(request, "/api/properties", {
    displayName: `Documents tab ${crypto.randomUUID().slice(0, 8)}`,
    addressLine1: "10 Maple Street",
    city: "Portland",
    region: "OR",
    postalCode: "97201",
    countryCode: "US",
    propertyType: "single_family_home",
    expectedPropertyRevision: 0,
    idempotencyKey: crypto.randomUUID(),
    ownerships: [{ ownerKind: "local_operator" }],
  });
  await page.goto(`/properties/${property.id}/overview`);
  const tabs = page.getByRole("navigation", { name: "property sections", exact: true });
  await expect(tabs.getByRole("link")).toHaveText([
    "Overview",
    "Home",
    "Leases",
    "Money",
    "Maintenance",
    "Conversations",
    "Documents",
    "Property setup",
  ]);
  for (const [section, label] of [
    ["overview", "Overview"],
    ["units", "Home"],
    ["leases", "Leases"],
    ["money", "Money"],
    ["maintenance", "Maintenance"],
    ["conversations", "Conversations"],
    ["documents", "Documents"],
    ["setup", "Property setup"],
  ])
    await expect(tabs.getByRole("link", { name: label, exact: true })).toHaveAttribute(
      "href",
      new RegExp(`^/properties/${property.id}/${section}(\\?|$)`),
    );
  await tabs.getByRole("link", { name: "Documents", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/properties/${property.id}/documents([?#]|$)`));
  await expect(tabs.getByRole("link", { name: "Documents", exact: true })).toHaveAttribute(
    "aria-current",
    "page",
  );
  await expect(page.getByRole("heading", { name: "documents", exact: true })).toBeVisible();
});

test("Money views tabs switch sections by click and mark the active tab", async ({ page }) => {
  await page.goto("/money");
  const views = page.getByRole("navigation", { name: "Money views", exact: true });
  for (const [label, tab] of [
    ["Expenses", "expenses"],
    ["Deposits", "deposits"],
    ["Scheduled checks", "checks"],
    ["Owner reports", "reports"],
    ["Expense categories", "categories"],
    ["Received rent", "receipts"],
    ["Rent", "rent"],
  ] as const) {
    await views.getByRole("link", { name: label, exact: true }).click();
    await expect(page).toHaveURL(new RegExp(`[?&]tab=${tab}(&|$)`));
    await expect(page.getByRole("region", { name: `${label} records`, exact: true })).toBeVisible();
    await expect(views.getByRole("link", { name: label, exact: true })).toHaveAttribute(
      "aria-current",
      "page",
    );
  }
  await views.getByRole("link", { name: "Reporting", exact: true }).click();
  await expect(page).toHaveURL(/[?&]tab=reporting(&|$)/);
  await expect(views.getByRole("link", { name: "Reporting", exact: true })).toHaveAttribute(
    "aria-current",
    "page",
  );
});

test("owners directory search narrows to the matching owner and opens its overview", async ({
  page,
  request,
}) => {
  const token = crypto.randomUUID().slice(0, 8);
  const alpha = await propertyWithOwner(
    request,
    `Owner search ${token} Alpha`,
    `Owner Search ${token} Alpha`,
  );
  const beta = await propertyWithOwner(
    request,
    `Owner search ${token} Beta`,
    `Owner Search ${token} Beta`,
  );
  await page.goto("/owners");
  const search = page.getByLabel("Search", { exact: true });
  const alphaLink = page.getByRole("link", { name: alpha.ownerName, exact: true });
  const betaLink = page.getByRole("link", { name: beta.ownerName, exact: true });
  await search.fill(token);
  await expect(alphaLink).toBeVisible();
  await expect(betaLink).toBeVisible();
  await expect(page.locator("#workspace-content")).toContainText("Person · Active");
  await expect(page.locator("#workspace-content")).toContainText("(Current)");
  await search.fill(alpha.ownerName);
  await expect(alphaLink).toBeVisible();
  await expect(betaLink).toHaveCount(0);
  await page.getByRole("button", { name: "Clear filters", exact: true }).click();
  await expect(page).toHaveURL("/owners");
  await expect(search).toHaveValue("");
  await expect(betaLink).toBeVisible();
  await alphaLink.click();
  await expect(page).toHaveURL(new RegExp(`/owners/${alpha.ownerId}/overview([?#]|$)`));
});

test("settings index links to implemented sections and removed placeholders stay unavailable", async ({
  page,
}) => {
  await page.goto("/settings");
  await expect(page.locator("#workspace-content h2").first()).toHaveText(
    "Appearance and navigation",
  );
  await page.getByRole("link", { name: "Provider categories", exact: true }).click();
  await expect(page).toHaveURL("/settings/provider-categories");
  await expect(page.locator("#workspace-content h2").first()).toHaveText("Provider categories");
  await page.getByRole("link", { name: "← Back to Settings", exact: true }).click();
  await expect(page).toHaveURL("/settings");
  const settings = page.getByRole("navigation", { name: "Settings sections", exact: true });
  await expect(settings.getByRole("link")).toHaveText(["Provider categories", "AI assistance"]);
  await settings.getByRole("link", { name: "AI assistance", exact: true }).click();
  await expect(page).toHaveURL("/settings/ai");
  await expect(
    page.getByRole("heading", { name: "Built-in AI assistance", exact: true }),
  ).toBeVisible();
  await page.getByRole("link", { name: "← Back to Settings", exact: true }).click();
  await expect(page).toHaveURL("/settings");
  const removed = await page.goto("/settings/workspace");
  expect(removed?.status()).toBe(404);
  for (const section of ["navigation", "appearance"]) {
    await page.goto(`/settings/${section}`);
    await expect(page.locator("#workspace-content h2").first()).toHaveText(
      "Appearance and navigation",
    );
    await expect(page.getByRole("link", { name: "← Back to Settings", exact: true })).toHaveCount(
      1,
    );
  }
});
