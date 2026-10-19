import { expect, test } from "@playwright/test";

// End-to-end coverage for the Tenants directory served from a seeded demo
// workspace (see application/demo/README.md). The suite is read-only: it never
// submits a workflow, so the seeded records stay intact for demo/verify.py.
//
// Prerequisites (from application/):
//   export EPM_PYTHON="$PWD/.venv/bin/python"
//   .venv/bin/python demo/seed.py --workspace "$HOME/Desktop/Property-Management-Data/synthetic-demo"
//   .venv/bin/python demo/serve.py
//
// Run with:
//   npx playwright test --config playwright.demo.config.ts tenants
//
// Counts below describe a freshly seeded demo; dates age normally, so reseed
// into a new directory for repeatability (see demo/README.md).

test.use({ extraHTTPHeaders: { Origin: "http://127.0.0.1:8001" } });

test("tenant directory prompts for search or browse", async ({ page }) => {
  await page.goto("/tenants");
  const directory = page.getByRole("region", { name: "Tenant directory", exact: true });
  await expect(directory.getByRole("heading", { name: "Tenants", exact: true })).toBeVisible();
  await expect(directory.getByRole("button", { name: "Create tenant", exact: true })).toBeVisible();
  await expect(directory.getByRole("heading", { name: "Find a tenant", exact: true })).toBeVisible();
  await expect(
    directory.getByText(
      "Search by name or browse tenants to open contact details and preferences.",
      { exact: true },
    ),
  ).toBeVisible();
  await expect(
    directory.getByText("Enter at least 2 characters. Results update as you type.", {
      exact: true,
    }),
  ).toBeVisible();
  await expect(
    directory.getByRole("searchbox", { name: "Search tenants", exact: true }),
  ).toBeVisible();
  await expect(directory.getByRole("button", { name: "Browse tenants", exact: true })).toBeVisible();
  await expect(
    directory.getByRole("checkbox", { name: "Include archived tenants", exact: true }),
  ).toBeVisible();
});

test("tenant search finds a demo tenant by name", async ({ page }) => {
  await page.goto("/tenants");
  const directory = page.getByRole("region", { name: "Tenant directory", exact: true });
  await directory.getByRole("searchbox", { name: "Search tenants", exact: true }).fill("Morgan");
  await expect(page).toHaveURL(/q=Morgan/);
  await expect(directory.getByText("1 matching tenant", { exact: true })).toBeVisible();
  await expect(
    directory.getByRole("link", { name: "Alex Morgan (Demo)", exact: true }),
  ).toBeVisible();
});

test("tenant search matches every demo tenant", async ({ page }) => {
  await page.goto("/tenants");
  const directory = page.getByRole("region", { name: "Tenant directory", exact: true });
  await directory.getByRole("searchbox", { name: "Search tenants", exact: true }).fill("Demo");
  await expect(directory.getByText("12 matching tenants", { exact: true })).toBeVisible();
  for (const name of [
    "Alex Morgan (Demo)",
    "Avery Lane (Demo)",
    "Juniper Studio LLC (Demo)",
    "Northlight Design LLC (Demo)",
  ]) {
    await expect(directory.getByRole("link", { name, exact: true })).toBeVisible();
  }
});

test("browse tenants lists the full demo roster", async ({ page }) => {
  await page.goto("/tenants");
  const directory = page.getByRole("region", { name: "Tenant directory", exact: true });
  await directory.getByRole("button", { name: "Browse tenants", exact: true }).click();
  await expect(page).toHaveURL(/browse=true/);
  await expect(directory.getByText("12 tenants", { exact: true })).toBeVisible();
  await expect(directory.locator(".tenant-directory-card")).toHaveCount(12);
});

test("opening a tenant and returning to the directory", async ({ page }) => {
  await page.goto("/tenants");
  const directory = page.getByRole("region", { name: "Tenant directory", exact: true });
  await directory.getByRole("searchbox", { name: "Search tenants", exact: true }).fill("Avery");
  await expect(directory.getByText("1 matching tenant", { exact: true })).toBeVisible();
  await directory.getByRole("link", { name: "Avery Lane (Demo)", exact: true }).click();
  await expect(page).toHaveURL(/\/tenants\?identity=[^&]+$/);

  const detail = page.getByRole("region", { name: "Person or organization details", exact: true });
  await expect(
    detail.getByRole("heading", { name: "Avery Lane (Demo)", exact: true }),
  ).toBeVisible();
  await expect(
    detail.getByRole("heading", { name: "Official identification", exact: true }),
  ).toBeVisible();
  await expect(
    detail.getByRole("heading", { name: "Tenant preferences", exact: true }),
  ).toBeVisible();

  await page.getByRole("link", { name: "← Back to Tenants", exact: true }).click();
  await expect(page).toHaveURL(/\/tenants\?q=Avery$/);
});

test("tenant search shows the empty state for unknown names", async ({ page }) => {
  await page.goto("/tenants");
  const directory = page.getByRole("region", { name: "Tenant directory", exact: true });
  await directory
    .getByRole("searchbox", { name: "Search tenants", exact: true })
    .fill("NoSuchTenant");
  await expect(
    directory.getByRole("heading", { name: "No tenants found", exact: true }),
  ).toBeVisible();
});
