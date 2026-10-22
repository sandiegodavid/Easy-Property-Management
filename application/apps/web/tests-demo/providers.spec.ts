import { expect, test, type Page } from "@playwright/test";

// End-to-end coverage for the Providers directory served from a seeded demo
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

// Seeded demo providers (application/demo/dataset.json). Every provider has
// one category, one service and the "Portland metro" service area; indexes
// 0, 4, 8, 12 and 16 are marked preferred.
const PROVIDER_NAMES = [
  "Clearwater Plumbing (Demo)",
  "North Star Pipeworks (Demo)",
  "Cedar Flow Services (Demo)",
  "Cascade Climate (Demo)",
  "Evergreen Heating (Demo)",
  "Rose City HVAC (Demo)",
  "Bright Circuit (Demo)",
  "Beacon Electric (Demo)",
  "Pacific Panel Services (Demo)",
  "Juniper Grounds (Demo)",
  "Maple Garden Care (Demo)",
  "Greenway Landscaping (Demo)",
  "Homeworks Appliance (Demo)",
  "Reliable Appliance Lab (Demo)",
  "Metro Repair Co (Demo)",
  "Cedar Handyman (Demo)",
  "Summit Building Care (Demo)",
  "Harbor Property Services (Demo)",
  "Oakridge Housing Counsel (Demo)",
  "Westbank Lease Counsel (Demo)",
];

function section(page: Page) {
  return page.getByRole("region", { name: "Providers", exact: true });
}

function directory(page: Page) {
  return page.getByRole("region", { name: "Provider directory", exact: true });
}

function cardFor(page: Page, name: string) {
  return page.locator("a.provider-directory-card", {
    has: page.getByRole("heading", { name, exact: true }),
  });
}

test("providers directory lists the seeded demo providers", async ({ page }) => {
  await page.goto("/providers");
  const sec = section(page);
  await expect(sec.getByRole("heading", { name: "Providers", exact: true })).toBeVisible();
  await expect(sec.getByRole("button", { name: "Create provider", exact: true })).toBeVisible();

  const dir = directory(page);
  await expect(dir.getByText("20 providers on this page", { exact: true })).toBeVisible();
  for (const name of PROVIDER_NAMES) {
    await expect(dir.getByRole("heading", { name, exact: true })).toBeVisible();
  }
  await expect(
    sec.getByRole("link", { name: "Manage provider categories", exact: true }),
  ).toBeVisible();
});

test("provider search filters by name", async ({ page }) => {
  await page.goto("/providers");
  const dir = directory(page);
  await dir.getByRole("searchbox", { name: "Search providers", exact: true }).fill("Clearwater");
  await expect(dir.getByText("1 provider on this page", { exact: true })).toBeVisible();
  await expect(
    dir.getByRole("heading", { name: "Clearwater Plumbing (Demo)", exact: true }),
  ).toBeVisible();
  await expect(page).toHaveURL(/q=Clearwater/);
});

test("category filter shows the plumbing providers", async ({ page }) => {
  await page.goto("/providers");
  const dir = directory(page);
  // Select by visible label: the category UUIDs are server-seeded and not
  // part of the demo dataset, so the suite must not hardcode them.
  await dir
    .getByRole("combobox", { name: "Category", exact: true })
    .selectOption({ label: "Plumbing" });
  await expect(page).toHaveURL(/categoryId=[0-9a-f-]{36}/);
  await expect(dir.getByText("3 providers on this page", { exact: true })).toBeVisible();
  for (const name of [
    "Clearwater Plumbing (Demo)",
    "North Star Pipeworks (Demo)",
    "Cedar Flow Services (Demo)",
  ]) {
    await expect(dir.getByRole("heading", { name, exact: true })).toBeVisible();
  }
  await expect(
    dir.getByRole("heading", { name: "Cascade Climate (Demo)", exact: true }),
  ).toHaveCount(0);
});

test("provider cards show categories, services, areas and preference", async ({ page }) => {
  await page.goto("/providers");

  const card = cardFor(page, "Clearwater Plumbing (Demo)");
  await expect(card.getByText("Plumbing", { exact: true })).toBeVisible();
  await expect(card.getByText("Leak detection and fixture repair", { exact: true })).toBeVisible();
  await expect(card.getByText("Portland metro", { exact: true })).toBeVisible();
  await expect(card.getByText("Preferred", { exact: true })).toBeVisible();

  const neutral = cardFor(page, "North Star Pipeworks (Demo)");
  await expect(neutral.getByText("Preferred", { exact: true })).toHaveCount(0);
});

test("empty search shows the no-providers state", async ({ page }) => {
  await page.goto("/providers");
  const dir = directory(page);
  await dir
    .getByRole("searchbox", { name: "Search providers", exact: true })
    .fill("NoSuchProvider");
  await expect(dir.getByRole("heading", { name: "No providers found", exact: true })).toBeVisible();
  await expect(
    dir.getByText("Try another search or clear the filters.", { exact: true }),
  ).toBeVisible();

  await dir.getByRole("button", { name: "Clear filters", exact: true }).click();
  await expect(dir.getByText("20 providers on this page", { exact: true })).toBeVisible();
});

test("opening a provider and returning to the directory", async ({ page }) => {
  await page.goto("/providers");
  await cardFor(page, "Clearwater Plumbing (Demo)").click();
  await expect(page).toHaveURL(/\/providers\/[^/]+\/details$/);

  const record = page.getByRole("region", { name: "Provider record", exact: true });
  await expect(
    record.getByRole("heading", { name: "Clearwater Plumbing (Demo)", exact: true }),
  ).toBeVisible();
  await expect(record.getByText("Active provider · Business", { exact: true })).toBeVisible();
  // The Categories panel is an unnamed <section> (not an accessible region),
  // so scope to its heading instead.
  await expect(record.getByRole("heading", { name: "Categories", exact: true })).toBeVisible();
  await expect(record.getByText("Plumbing", { exact: true })).toBeVisible();

  const back = record.getByRole("link", { name: "← Back to Providers", exact: true });
  await expect(back).toHaveAttribute("href", "/providers");
  await back.click();
  await expect(page).toHaveURL(/\/providers$/);
  await expect(
    directory(page).getByText("20 providers on this page", { exact: true }),
  ).toBeVisible();
});

test("provider categories link opens the catalog", async ({ page }) => {
  await page.goto("/providers");
  await section(page)
    .getByRole("link", { name: "Manage provider categories", exact: true })
    .click();
  await expect(page).toHaveURL(/\/settings\/provider-categories$/);
  await expect(
    page.getByRole("heading", { name: "Provider categories", exact: true }),
  ).toBeVisible();
  const active = page.getByRole("region", { name: "Active Provider categories", exact: true });
  await expect(active.getByRole("heading", { name: "Plumbing", exact: true })).toBeVisible();
  await expect(
    active.getByRole("heading", { name: "Legal / Attorney", exact: true }),
  ).toBeVisible();
});
