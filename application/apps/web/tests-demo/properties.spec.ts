import { expect, test, type Page } from "@playwright/test";

// End-to-end coverage for the Properties directory served from a seeded demo
// workspace (see application/demo/README.md). The suite is read-only: it never
// submits a workflow, so the seeded records stay intact for demo/verify.py.
//
// Prerequisites (from application/):
//   export EPM_PYTHON="$PWD/.venv/bin/python"
//   .venv/bin/python demo/seed.py --workspace "$HOME/Desktop/Property-Management-Data/synthetic-demo"
//   .venv/bin/python demo/serve.py
//
// Run with:
//   npx playwright test --config playwright.demo.config.ts
// or:
//   npm run test:demo
//
// Counts below describe a freshly seeded demo; dates age normally, so reseed
// into a new directory for repeatability (see demo/README.md).

test.use({ extraHTTPHeaders: { Origin: "http://127.0.0.1:8001" } });

// Seeded demo properties in directory sort order (casefolded display name).
const PROPERTY_NAMES = [
  "Alder House — Co-owned",
  "Birch Townhome — Rent Follow-up",
  "Cedar Cottage — Vacant",
  "Harbor Offices",
  "Magnolia House — Four Owners",
  "Maple House",
  "Operator Office",
  "Owner 2 Office",
  "Riverbend Condo 101",
  "Riverbend Condo 102",
  "Riverbend Condo 103",
  "Sequoia House — Ten Owners",
  "Spruce House",
  "Willow House — Prepaid",
];

function cardFor(page: Page, name: string) {
  return page.locator("ul.context-cards > li", {
    has: page.getByRole("link", { name, exact: true }),
  });
}

function statusFilters(page: Page) {
  return page.getByRole("navigation", { name: "Property status filters", exact: true });
}

test("properties directory lists the seeded demo portfolio", async ({ page }) => {
  await page.goto("/properties");
  await expect(page.getByRole("heading", { name: "Properties", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Create property", exact: true })).toBeVisible();

  const setup = page.getByRole("region", { name: "Property setup", exact: true });
  const summary = setup.getByRole("region", {
    name: "Portfolio occupancy and leasing status",
    exact: true,
  });
  await expect(
    summary.getByText("14 active properties · 15 active rental units.", { exact: true }),
  ).toBeVisible();
  const filters = statusFilters(page);
  await expect(filters.getByRole("link", { name: "Occupied: 9", exact: true })).toBeVisible();
  await expect(filters.getByRole("link", { name: "Vacant: 6", exact: true })).toBeVisible();
  await expect(
    filters.getByRole("link", { name: "Needs occupancy classification: 0", exact: true }),
  ).toBeVisible();
  await expect(
    filters.getByRole("link", { name: "Open for leasing now: 5", exact: true }),
  ).toBeVisible();
  await expect(
    filters.getByRole("link", { name: "Open for leasing later: 2", exact: true }),
  ).toBeVisible();
  await expect(filters.getByRole("link", { name: "Review status: 1", exact: true })).toBeVisible();
  await expect(summary.getByText(/Next leasing opening date: \d{4}-\d{2}-\d{2}/)).toBeVisible();

  await expect(page.getByText("14 matching properties", { exact: true })).toBeVisible();
  const headings = await page.locator("ul.context-cards > li > h3").allInnerTexts();
  expect(headings.map((heading) => heading.trim())).toEqual(PROPERTY_NAMES);
});

test("property search filters by name and address", async ({ page }) => {
  await page.goto("/properties");
  const search = page.getByRole("textbox", { name: "Property name or address", exact: true });

  await search.fill("Cedar");
  await expect(page.getByText("1 matching properties", { exact: true })).toBeVisible();
  await expect(
    page.getByRole("link", { name: "Cedar Cottage — Vacant", exact: true }),
  ).toBeVisible();
  await expect(page.getByRole("link", { name: "Maple House", exact: true })).toHaveCount(0);
  await expect(page).toHaveURL(/q=Cedar/);

  await search.fill("Riverbend");
  await expect(page.getByText("3 matching properties", { exact: true })).toBeVisible();
  for (const name of ["Riverbend Condo 101", "Riverbend Condo 102", "Riverbend Condo 103"]) {
    await expect(page.getByRole("link", { name, exact: true })).toBeVisible();
  }
  await expect(page).toHaveURL(/q=Riverbend/);
});

test("portfolio status counts link to matching property filters", async ({ page }) => {
  await page.goto("/properties");
  const filters = statusFilters(page);

  await filters.getByRole("link", { name: "Vacant: 6", exact: true }).click();
  await expect(page).toHaveURL(/occupancy=vacant/);
  await expect(page.getByText("5 matching properties", { exact: true })).toBeVisible();
  for (const name of [
    "Alder House — Co-owned",
    "Cedar Cottage — Vacant",
    "Harbor Offices",
    "Magnolia House — Four Owners",
    "Sequoia House — Ten Owners",
  ]) {
    await expect(page.getByRole("link", { name, exact: true })).toBeVisible();
  }

  await filters.getByRole("link", { name: "Open for leasing now: 5", exact: true }).click();
  await expect(page).toHaveURL(/availability=available_now/);
  await expect(page.getByText("4 matching properties", { exact: true })).toBeVisible();
  for (const name of [
    "Cedar Cottage — Vacant",
    "Harbor Offices",
    "Magnolia House — Four Owners",
    "Sequoia House — Ten Owners",
  ]) {
    await expect(page.getByRole("link", { name, exact: true })).toBeVisible();
  }
  await expect(
    page.getByRole("link", { name: "Alder House — Co-owned", exact: true }),
  ).toHaveCount(0);
});

test("review status filter isolates the property needing status review", async ({ page }) => {
  await page.goto("/properties");
  await statusFilters(page)
    .getByRole("link", { name: "Review status: 1", exact: true })
    .click();
  await expect(page).toHaveURL(/needsAttention=true/);
  await expect(page.getByText("1 matching properties", { exact: true })).toBeVisible();

  const card = cardFor(page, "Alder House — Co-owned");
  await expect(
    card.getByText("Occupancy or leasing status needs review", { exact: true }),
  ).toBeVisible();
  const review = card.getByRole("link", {
    name: "Review status for Alder House — Co-owned",
    exact: true,
  });
  await expect(review).toHaveAttribute("href", /\/properties\/[^/]+\/units$/);

  await review.click();
  await expect(page).toHaveURL(/\/properties\/[^/]+\/units$/);
  await expect(page.getByRole("region", { name: "Property home", exact: true })).toBeVisible();
});

test("property cards disclose ownership shares and rental units", async ({ page }) => {
  await page.goto("/properties");

  const sequoia = cardFor(page, "Sequoia House — Ten Owners");
  await expect(sequoia.getByText("10 owners")).toBeVisible();
  await expect(sequoia.getByRole("link", { name: "+5 more owners" })).toBeVisible();
  await expect(sequoia.getByText("10%").first()).toBeVisible();

  const harbor = cardFor(page, "Harbor Offices");
  await expect(harbor.getByText("2 rental units")).toBeVisible();
  await expect(harbor.getByText("1 owner")).toBeVisible();

  const maple = cardFor(page, "Maple House");
  await expect(maple.getByText("1 owner")).toBeVisible();
  await expect(maple.getByText("1 rental unit")).toBeVisible();

  const alder = cardFor(page, "Alder House — Co-owned");
  await expect(alder.getByText("3 owners")).toBeVisible();
  await expect(alder.getByText("50%")).toBeVisible();
  await expect(alder.getByText("25%").first()).toBeVisible();
});

test("archived filter shows the empty directory state", async ({ page }) => {
  await page.goto("/properties");
  await page.getByLabel("State", { exact: true }).selectOption("archived");
  await expect(page).toHaveURL(/state=archived/);
  await expect(page.getByText("0 matching properties", { exact: true })).toBeVisible();
  await expect(page.getByText("No matching records on this page.", { exact: true })).toBeVisible();

  await page.getByRole("button", { name: "Clear filters", exact: true }).click();
  await expect(page).toHaveURL(/\/properties$/);
  await expect(page.getByText("14 matching properties", { exact: true })).toBeVisible();
});

test("opening a property and returning to the directory", async ({ page }) => {
  await page.goto("/properties");
  await page.getByRole("link", { name: "Maple House", exact: true }).click();
  await expect(page).toHaveURL(/\/properties\/[^/]+\/overview$/);
  const title = page.locator(".property-workspace-title");
  await expect(title.getByRole("heading", { name: "Maple House", exact: true })).toBeVisible();

  await page.getByRole("link", { name: "← Back to Properties", exact: true }).click();
  await expect(page).toHaveURL(/\/properties$/);
  await expect(page.getByText("14 matching properties", { exact: true })).toBeVisible();
});

test("create property opens the portfolio create workflow", async ({ page }) => {
  await page.goto("/properties");
  await page.getByRole("button", { name: "Create property", exact: true }).click();
  await expect(page).toHaveURL(/\/properties\?workflow=portfolio\.property\.create$/);
  await expect(
    page.getByText(
      "Start with the property name and address, choose its rental layout, and confirm the owners. Occupancy, leasing status and lease records can be added afterward.",
      { exact: true },
    ),
  ).toBeVisible();
  await expect(page.getByRole("group", { name: "Property name", exact: true })).toBeVisible();
  await expect(
    page.getByRole("combobox", { name: "Property type (required)", exact: true }),
  ).toBeVisible();
});
