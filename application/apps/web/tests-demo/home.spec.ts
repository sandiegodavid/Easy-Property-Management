import { expect, test, type Page } from "@playwright/test";

// End-to-end coverage for the Home page served from a seeded demo workspace
// (see application/demo/README.md). The suite is read-only: it never submits a
// workflow, so the seeded records stay intact for demo/verify.py.
//
// Prerequisites (from application/):
//   export EPM_PYTHON="$PWD/.venv/bin/python"
//   .venv/bin/python demo/seed.py --workspace "$HOME/Desktop/Property-Management-Data/synthetic-demo"
//   .venv/bin/python demo/serve.py
//
// Run with:
//   npx playwright test --config playwright.demo.config.ts home
// or:
//   npm run test:demo
//
// Dynamic summaries below describe a freshly seeded demo; dates age normally,
// so reseed into a new directory for repeatability (see demo/README.md).

test.use({ extraHTTPHeaders: { Origin: "http://127.0.0.1:8001" } });

function homeRegion(page: Page, name: string) {
  return page.getByRole("region", { name, exact: true });
}

test("home page shows the day heading, work queue tabs and summary scope", async ({ page }) => {
  await page.goto("/home");
  await expect(page.getByRole("heading", { name: "Your day, in view", exact: true })).toBeVisible();
  const queue = page.getByRole("tablist", { name: "Work queue", exact: true });
  for (const name of ["Needs action", "Waiting", "Upcoming"]) {
    await expect(queue.getByRole("tab", { name, exact: true })).toBeVisible();
  }
  await expect(queue.getByRole("tab", { name: "Needs action", exact: true })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  const summary = homeRegion(page, "Home summary");
  await expect(summary.getByText("Scope: All properties.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Filters", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Refresh", exact: true })).toBeVisible();
});

test("day heading summarizes items needing action", async ({ page }) => {
  await page.goto("/home");
  const heading = page.locator(".home-heading");
  await expect(heading.getByText(/needs? action/)).toBeVisible();
});

test("work queue tabs switch panels", async ({ page }) => {
  await page.goto("/home");
  const queue = page.getByRole("tablist", { name: "Work queue", exact: true });

  await queue.getByRole("tab", { name: "Upcoming", exact: true }).click();
  await expect(queue.getByRole("tab", { name: "Upcoming", exact: true })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  await expect(homeRegion(page, "Upcoming")).toBeVisible();

  await queue.getByRole("tab", { name: "Waiting", exact: true }).click();
  await expect(queue.getByRole("tab", { name: "Waiting", exact: true })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  await expect(homeRegion(page, "Waiting")).toBeVisible();

  await queue.getByRole("tab", { name: "Needs action", exact: true }).click();
  await expect(homeRegion(page, "Needs action")).toBeVisible();
  await expect(homeRegion(page, "Home action list")).toBeVisible();
});

test("filters button discloses the home filter form", async ({ page }) => {
  await page.goto("/home");
  const toggle = page.getByRole("button", { name: "Filters", exact: true });
  await expect(toggle).toHaveAttribute("aria-expanded", "false");
  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-expanded", "true");
  const filters = page.locator("#home-filters");
  await expect(filters).toBeVisible();
  const property = filters.getByRole("combobox", { name: "Property", exact: true });
  await expect(property).toBeVisible();
  await expect(property).toHaveValue("");
  await expect(property.locator("option:checked")).toHaveText("All properties");
  await expect(filters.getByLabel("Upcoming horizon")).toBeVisible();
  await expect(filters.getByLabel("Money from")).toBeVisible();
  await expect(filters.getByLabel("Money through")).toBeVisible();
  await expect(filters.getByText("Money dates apply only to Recorded money.")).toBeVisible();
  await expect(filters.getByRole("button", { name: "Clear filters", exact: true })).toBeVisible();
  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-expanded", "false");
  await expect(filters).toBeHidden();
});

test("side collections link to full collection views", async ({ page }) => {
  await page.goto("/home");
  await expect(homeRegion(page, "Calendar and appointments")).toBeVisible();
  await expect(homeRegion(page, "Information review")).toBeVisible();
  const appointments = page.getByRole("link", {
    name: /View all Calendar and appointments/,
  });
  await expect(appointments).toBeVisible();
  await expect(appointments).toHaveAttribute("href", /\/home\/collections\/appointments/);
  const review = page.getByRole("link", { name: /View all Information review/ });
  await expect(review).toBeVisible();
  await expect(review).toHaveAttribute("href", /\/home\/collections\/information_review/);
});

test("inventory summary links vacant and unknown occupancy", async ({ page }) => {
  await page.goto("/home");
  const inventory = homeRegion(page, "Inventory");
  await expect(inventory.getByText("Active properties only.", { exact: true })).toBeVisible();
  await expect(inventory.getByText("Vacant rental units", { exact: true })).toBeVisible();
  await expect(inventory.getByText("Unknown occupancy", { exact: true })).toBeVisible();
  const vacant = inventory.getByRole("link", { name: /View vacant rental units/ });
  await expect(vacant).toBeVisible();
  await expect(vacant).toHaveAttribute("href", /\/home\/inventory/);
  const unknown = inventory.getByRole("link", { name: /View unknown occupancy/ });
  await expect(unknown).toBeVisible();
  await expect(unknown).toHaveAttribute("href", /\/home\/inventory/);
});

test("recorded money shows metrics and the money period", async ({ page }) => {
  await page.goto("/home");
  const money = homeRegion(page, "Recorded money");
  await expect(money.getByText("Rent received", { exact: true })).toBeVisible();
  await expect(money.getByText("Expenses paid", { exact: true })).toBeVisible();
  await expect(money.getByText(/Recorded money period: \d{4}-\d{2}-\d{2} through/)).toBeVisible();
  await expect(
    money.getByText("These totals do not establish profit or owner entitlement."),
  ).toBeVisible();
  const sources = money.getByRole("link", { name: /View Rent received sources/ });
  await expect(sources).toBeVisible();
  await expect(sources).toHaveAttribute("href", /\/money\?/);
});
