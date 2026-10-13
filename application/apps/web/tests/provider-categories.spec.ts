import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import type { components } from "@epm/contracts/generated";

type Schema = components["schemas"];
type Category = Schema["app__modules__vendors__api__router__CategoryResponse"];
test.use({ extraHTTPHeaders: { Origin: "http://127.0.0.1:18744" } });

async function catalog(request: APIRequestContext) {
  const response = await request.get("/api/provider-categories?archiveState=all");
  expect(response.ok(), await response.text()).toBe(true);
  return (await response.json()) as Category[];
}
async function save(page: Page, name: string) {
  await page.getByRole("button", { name: `Save ${name}`, exact: true }).click();
  await expect(page.getByRole("region", { name: "Committed result" })).toBeVisible();
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
  await page.getByRole("button", { name: "Apply Provider filters", exact: true }).click();
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
  await expect(page.getByText(/No .*Providers/i)).toBeVisible();
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
  await expect(page.getByRole("article").getByText("Uncategorized", { exact: true })).toBeVisible();
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
  await page.getByRole("button", { name: "Save create provider category", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Check original result", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Check original result", exact: true }).click();
  await expect(page.getByRole("region", { name: "Committed result" })).toBeVisible();
  expect(dispatches).toBe(1);
  expect(
    (await catalog(request)).filter((item) => item.displayName === "Recoverable category"),
  ).toHaveLength(1);
});
