import { expect, test, type Page } from "@playwright/test";

// End-to-end coverage for the Leasing workspace served from a seeded demo
// workspace (see application/demo/README.md). The suite is read-only: it never
// submits a workflow, so the seeded records stay intact for demo/verify.py.
//
// Prerequisites (from application/):
//   export EPM_PYTHON="$PWD/.venv/bin/python"
//   .venv/bin/python demo/seed.py --workspace "$HOME/Desktop/Property-Management-Data/synthetic-demo"
//   .venv/bin/python demo/serve.py
//
// Run with:
//   npx playwright test --config playwright.demo.config.ts leasing
// or:
//   npm run test:demo
//
// Counts below describe a freshly seeded demo; dates age normally, so reseed
// into a new directory for repeatability (see demo/README.md). The demo seeds
// nine executed leases: seven residential homes and two commercial offices.

test.use({ extraHTTPHeaders: { Origin: "http://127.0.0.1:8001" } });

// Seeded demo leases by leased property name.
const LEASE_PROPERTY_NAMES = [
  "Birch Townhome — Rent Follow-up",
  "Maple House",
  "Operator Office",
  "Owner 2 Office",
  "Riverbend Condo 101",
  "Riverbend Condo 102",
  "Riverbend Condo 103",
  "Spruce House",
  "Willow House — Prepaid",
];

function leaseCardFor(page: Page, name: string) {
  return page.locator("ul.lease-directory-grid > li", {
    has: page.getByRole("heading", { name, exact: true }),
  });
}

test("leasing directory lists the seeded leases", async ({ page }) => {
  await page.goto("/leasing");
  const directory = page.getByRole("region", { name: "Leasing", exact: true });
  await expect(directory.getByRole("heading", { name: "Leasing", exact: true })).toBeVisible();
  await expect(
    directory.getByRole("button", { name: "Create lease draft", exact: true }),
  ).toBeVisible();
  await expect(
    directory.getByRole("link", { name: "Manage inspection templates", exact: true }),
  ).toBeVisible();

  await expect(page.getByText("9 matching leases", { exact: true })).toBeVisible();
  const headings = await page.locator("ul.lease-directory-grid h3").allInnerTexts();
  expect(headings.map((heading) => heading.trim()).sort()).toEqual(
    [...LEASE_PROPERTY_NAMES].sort(),
  );
  const cards = page.locator("ul.lease-directory-grid > li");
  await expect(cards.getByText("Signed", { exact: true })).toHaveCount(9);
});

test("lease status filter narrows the directory", async ({ page }) => {
  await page.goto("/leasing");
  const filter = page.getByLabel("Lease status", { exact: true });
  await filter.selectOption("executed");
  await expect(page).toHaveURL(/status=executed/);
  await expect(page.getByText("9 matching leases", { exact: true })).toBeVisible();

  await filter.selectOption("draft");
  await expect(page).toHaveURL(/status=draft/);
  await expect(page.getByText("0 matching leases", { exact: true })).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "No leases match these filters", exact: true }),
  ).toBeVisible();
});

test("maple house lease shows terms and participants", async ({ page }) => {
  await page.goto("/leasing");
  const card = leaseCardFor(page, "Maple House");
  await card.getByRole("link").first().click();
  await expect(page).toHaveURL(/\/leases\/[^/]+\/details$/);
  await expect(
    page.getByRole("heading", { name: "Residential lease", exact: true }),
  ).toBeVisible();
  await expect(page.getByRole("link", { name: "← Back to Leasing", exact: true })).toBeVisible();

  const context = page.getByRole("region", { name: "Lease property", exact: true });
  await expect(context.getByRole("link", { name: "Maple House", exact: true })).toBeVisible();
  await expect(context.getByText("Whole home")).toBeVisible();

  const milestones = page.getByRole("region", { name: "Lease milestones", exact: true });
  await expect(milestones.getByText("Lease starts", { exact: true })).toBeVisible();
  await expect(milestones.getByText("Signed on", { exact: true })).toBeVisible();

  const terms = page.getByRole("region", { name: "Rent terms", exact: true });
  await expect(terms.getByText("USD 2150.00", { exact: true })).toHaveCount(2);
  await expect(
    terms.getByRole("link", { name: "View rent and deposits →", exact: true }),
  ).toBeVisible();

  const participants = page.getByRole("region", { name: "Lease participants", exact: true });
  await expect(
    participants.getByRole("link", { name: "Alex Morgan (Demo)", exact: true }),
  ).toBeVisible();
  await expect(
    participants.getByRole("link", { name: "Sam Patel (Demo)", exact: true }),
  ).toBeVisible();
  await expect(participants.getByText("primary tenant", { exact: true })).toBeVisible();
  await expect(participants.getByText("co tenant", { exact: true })).toBeVisible();
});

test("office lease cards read commercial", async ({ page }) => {
  await page.goto("/leasing");
  const card = leaseCardFor(page, "Operator Office");
  await expect(card.getByText("Whole office · Commercial", { exact: true })).toBeVisible();
});

test("lease detail links to its money records", async ({ page }) => {
  await page.goto("/leasing");
  const card = leaseCardFor(page, "Willow House — Prepaid");
  await card.getByRole("link").first().click();
  await expect(page).toHaveURL(/\/leases\/[^/]+\/details$/);
  const moneyLink = page.getByRole("link", { name: "View rent and deposits →", exact: true });
  await expect(moneyLink).toHaveAttribute("href", /\/money\?leaseId=[^&]+$/);
  await moneyLink.click();
  await expect(page).toHaveURL(/\/money\?leaseId=[^&]+$/);
  await expect(page.getByText("Showing this lease's records.", { exact: true })).toBeVisible();
  const rent = page.getByRole("region", { name: "rent records", exact: true });
  await expect(rent.getByRole("article")).toHaveCount(2);
});

test("back to leasing returns to the directory", async ({ page }) => {
  await page.goto("/leasing");
  const card = leaseCardFor(page, "Spruce House");
  await card.getByRole("link").first().click();
  await expect(page).toHaveURL(/\/leases\/[^/]+\/details$/);
  await page.getByRole("link", { name: "← Back to Leasing", exact: true }).click();
  await expect(page).toHaveURL(/\/leasing$/);
  await expect(page.getByText("9 matching leases", { exact: true })).toBeVisible();
});

test("create lease draft opens the lease workflow", async ({ page }) => {
  await page.goto("/leasing");
  await page.getByRole("button", { name: "Create lease draft", exact: true }).click();
  await expect(page).toHaveURL(/\/leasing\?workflow=lease\.create$/);
  await expect(
    page.getByRole("heading", { name: "Create lease draft", exact: true }),
  ).toBeVisible();
  await expect(page.getByLabel("Contract starts on (required)", { exact: true })).toBeVisible();
});
