import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import type { components } from "@epm/contracts/generated";
import axe from "axe-core";

type Schema = components["schemas"];
type Category = Schema["app__modules__vendors__api__router__CategoryResponse"];
test.use({ extraHTTPHeaders: { Origin: "http://127.0.0.1:18744" } });

async function catalog(request: APIRequestContext) {
  const response = await request.get("/api/provider-categories?archiveState=all");
  expect(response.ok(), await response.text()).toBe(true);
  return (await response.json()) as Category[];
}
async function save(page: Page, name: string) {
  await test.step(name, async () => {
    await page
      .getByRole("group", { name: "Form actions", exact: true })
      .locator('button[type="submit"]')
      .click();
  });
  await expect(page.locator('.saved-item, section[aria-label="Committed result"]')).toBeVisible();
}

test("Settings manages categories separately from Services, retains assignments and filters effective coverage", async ({
  page,
  request,
}) => {
  const seeds = await catalog(request);
  expect(seeds).toHaveLength(7);
  expect(seeds.map((item) => item.displayOrder)).toEqual([0, 1, 2, 3, 4, 5, 6]);
  const legal = seeds.find((item) => item.displayName === "Legal / Attorney")!;
  expect(legal.id).toBe("00000000-0000-4000-8000-000000000301");
  await page.goto("/settings");
  await page.getByRole("link", { name: "Provider categories", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Provider categories", exact: true }),
  ).toBeVisible();
  await expect(page.getByText(/Services describe specific offerings/)).toBeVisible();
  await page.goto("/providers?workflow=provider.category.create");
  await page.getByLabel("Display name (required)").fill("Specialist category");
  await save(page, "create provider category");
  const custom = (await catalog(request)).find(
    (item) => item.displayName === "Specialist category",
  )!;
  const providerResponse = await request.post("/api/providers", {
    data: {
      party: { partyKind: "organization", displayName: "Categorized legal provider" },
      services: [{ displayName: "Lease review practice" }],
      categoryIds: [legal.id, custom.id],
      expectedRevision: 0,
      idempotencyKey: crypto.randomUUID(),
    },
  });
  expect(providerResponse.ok(), await providerResponse.text()).toBe(true);
  const provider = (await providerResponse.json()) as Schema["ProviderMutationResponse"];
  await page.goto(`/providers?workflow=provider.category.patch&target=${custom.id}`);
  await page.getByRole("textbox", { name: /^Display name/ }).fill("Renamed specialist");
  await page.getByRole("checkbox", { name: "Clear description", exact: true }).uncheck();
  await page.getByRole("textbox", { name: /^Description/ }).fill("Editable directory grouping");
  await page.getByRole("spinbutton", { name: /Display order/ }).fill("0");
  await save(page, "edit provider category");
  const updated = (await catalog(request)).find((item) => item.id === custom.id)!;
  expect(updated).toMatchObject({
    displayName: "Renamed specialist",
    description: "Editable directory grouping",
    displayOrder: 0,
    effectiveProviderCount: 1,
  });
  await page.goto("/providers");
  await page.getByRole("combobox", { name: "Category", exact: true }).selectOption(custom.id);
  await expect(
    page.getByRole("link", { name: "Categorized legal provider", exact: true }),
  ).toBeVisible();
  await page.reload();
  await expect(page.getByRole("combobox", { name: "Category", exact: true })).toHaveValue(
    custom.id,
  );
  await page.goto(`/providers?workflow=provider.category.archive&target=${custom.id}`);
  await page.getByLabel("Reason (required)").fill("Temporarily retire grouping");
  await page.getByLabel("I confirm this lifecycle change", { exact: true }).check();
  await save(page, "archive provider category");
  await page.goto("/settings/provider-categories");
  await expect(page.getByRole("region", { name: "Archived Provider categories" })).toContainText(
    "Renamed specialist",
  );
  await expect(page.getByRole("region", { name: "Active Provider categories" })).not.toContainText(
    "Renamed specialist",
  );
  expect(
    (await catalog(request)).find((item) => item.id === custom.id)?.effectiveProviderCount,
  ).toBe(0);
  await page.goto("/providers");
  await expect(
    page
      .getByRole("combobox", { name: "Category", exact: true })
      .getByRole("option", { name: "Renamed specialist" }),
  ).toHaveCount(0);
  await page.goto(`/providers?workflow=provider.category.restore&target=${custom.id}`);
  await page.getByLabel("I confirm this lifecycle change", { exact: true }).check();
  await save(page, "restore provider category");
  expect(
    (await catalog(request)).find((item) => item.id === custom.id)?.effectiveProviderCount,
  ).toBe(1);
  const detail = (await (
    await request.get(`/api/providers/${provider.profile.partyId}?includeArchived=true`)
  ).json()) as Schema["ProviderResponse"];
  expect(detail.categories).toHaveLength(2);
  expect(detail.services.map((item) => item.displayName)).toEqual(["Lease review practice"]);
  await page.goto(`/providers?categoryState=uncategorized&categoryId=${custom.id}`);
  await expect(
    page.getByRole("heading", { name: "No providers found", exact: true }),
  ).toBeVisible();
  const uncategorized = await request.post("/api/providers", {
    data: {
      party: { partyKind: "organization", displayName: "Unclassified provider" },
      expectedRevision: 0,
      idempotencyKey: crypto.randomUUID(),
    },
  });
  expect(uncategorized.ok(), await uncategorized.text()).toBe(true);
  await page.goto("/providers?categoryState=uncategorized");
  await expect(
    page.getByRole("link", { name: "Unclassified provider", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("link", { name: "Categorized legal provider", exact: true }),
  ).toHaveCount(0);
  await expect(
    page
      .getByRole("link", { name: "Unclassified provider", exact: true })
      .getByText("No categories assigned", { exact: true }),
  ).toBeVisible();
});

test("a lost category response recovers its original receipt without duplicating the catalog", async ({
  page,
  request,
}) => {
  await page.goto("/providers?workflow=provider.category.create");
  await page.getByLabel("Display name (required)").fill("Recoverable category");
  let dispatches = 0;
  await page.route("**/api/provider-categories", async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    dispatches++;
    const response = await route.fetch();
    expect(response.ok()).toBe(true);
    return route.abort();
  });
  await page.getByRole("button", { name: "Create provider category", exact: true }).click();
  await expect(page.getByRole("button", { name: "Check submission", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Check submission", exact: true }).click();
  await expect(page.locator('.saved-item, section[aria-label="Committed result"]')).toBeVisible();
  expect(dispatches).toBe(1);
  expect(
    (await catalog(request)).filter((item) => item.displayName === "Recoverable category"),
  ).toHaveLength(1);
});

test("category settings show clear actions and retained history in both themes and on mobile", async ({
  page,
  request,
}, testInfo) => {
  const seeds = await catalog(request);
  const items: Category[] = [
    {
      ...seeds[0],
      displayName: "Repairs and maintenance",
      description: "Plumbing, electrical and general repairs.",
      effectiveProviderCount: 2,
    },
    { ...seeds[1], displayName: "Specialist advice", description: null, effectiveProviderCount: 0 },
    {
      ...seeds[2],
      displayName: "Retired services",
      archivedAt: "2026-10-20T17:30:00Z",
      archiveReason: "Replaced by more specific categories.",
      effectiveProviderCount: 0,
    },
  ];
  let historyReads = 0;
  page.on("request", (pending) => {
    if (new URL(pending.url()).pathname.startsWith("/api/audit/events/provider_category/"))
      historyReads++;
  });
  await page.route("**/api/provider-categories?*", (route) => route.fulfill({ json: items }));
  await page.goto("/settings/provider-categories");
  await expect(page.getByRole("link", { name: "← Back to Settings", exact: true })).toHaveCount(1);
  await expect(page.getByRole("button", { name: "Add category", exact: true })).toBeVisible();
  const active = page.getByRole("region", { name: "Active Provider categories", exact: true });
  const archived = page.getByRole("region", { name: "Archived Provider categories", exact: true });
  await expect(active.getByText("2 categories", { exact: true })).toBeVisible();
  await expect(archived.getByText("1 category", { exact: true })).toBeVisible();
  const repair = active.getByRole("article", { name: items[0].displayName, exact: true });
  await expect(repair.getByText(items[0].description!, { exact: true })).toBeVisible();
  await expect(
    repair.getByRole("link", { name: "2 providers in Repairs and maintenance", exact: true }),
  ).toHaveAttribute("href", `/providers?categoryId=${items[0].id}`);
  await expect(active.getByText("No active providers", { exact: true })).toBeVisible();
  await expect(
    repair.getByRole("link", { name: "Edit category Repairs and maintenance", exact: true }),
  ).toBeVisible();
  await expect(
    repair.getByRole("link", { name: "Archive category Repairs and maintenance", exact: true }),
  ).toBeVisible();
  await expect(
    archived.getByRole("link", { name: "Restore category Retired services", exact: true }),
  ).toBeVisible();
  await expect(archived.getByText(items[2].archiveReason!, { exact: true })).toBeVisible();
  await expect(archived.locator("time")).toHaveAttribute("datetime", items[2].archivedAt!);
  await expect(page.getByText("Category administration", { exact: true })).toHaveCount(0);
  expect(historyReads).toBe(0);
  for (const theme of ["light", "dark"]) {
    await page.evaluate((value) => {
      document.documentElement.dataset.theme = value;
    }, theme);
    for (const width of [1280, 390]) {
      await page.setViewportSize({ width, height: 900 });
      expect(
        await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
      ).toBe(true);
      await page.screenshot({
        path: testInfo.outputPath(`provider-categories-${theme}-${width}.png`),
        fullPage: true,
      });
      await page.evaluate(axe.source);
      expect(
        await page.evaluate(
          async () =>
            (await window.axe.run(document, { runOnly: ["wcag2a", "wcag2aa"] })).violations,
        ),
      ).toEqual([]);
    }
  }
  await repair.getByText("History", { exact: true }).click();
  await expect.poll(() => historyReads).toBe(1);
  await repair
    .getByRole("link", { name: "Edit category Repairs and maintenance", exact: true })
    .click();
  await expect(page).toHaveURL(
    new RegExp(`workflow=provider.category.patch&target=${items[0].id}`),
  );
});

test("category settings distinguish unavailable data from an empty catalog and allow retry", async ({
  page,
}) => {
  let fail = true;
  await page.route("**/api/provider-categories?*", (route) =>
    route.fulfill(fail ? { status: 503, json: { detail: "Unavailable" } } : { json: [] }),
  );
  await page.goto("/settings/provider-categories");
  await expect(page.getByRole("alert")).toContainText("Categories are unavailable.");
  await expect(page.getByText("No active categories.", { exact: false })).toHaveCount(0);
  fail = false;
  await page.getByRole("button", { name: "Retry categories", exact: true }).click();
  await expect(
    page.getByText("No active categories. Add a category to start organizing providers.", {
      exact: true,
    }),
  ).toBeVisible();
  await expect(page.getByText("No archived categories.", { exact: true })).toBeVisible();
});
