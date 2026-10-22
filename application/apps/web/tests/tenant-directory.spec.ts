import { expect, test, type APIRequestContext } from "@playwright/test";
import type { components } from "@epm/contracts/generated";
import axe from "axe-core";

type Schemas = components["schemas"];
test.use({ extraHTTPHeaders: { Origin: "http://127.0.0.1:18744" } });

async function tenant(request: APIRequestContext, name: string) {
  const response = await request.post("/api/tenants", {
    data: {
      partyKind: "individual",
      displayName: name,
      confirmedNewParty: true,
      expectedRevision: 0,
      idempotencyKey: crypto.randomUUID(),
    },
  });
  expect(response.ok(), await response.text()).toBe(true);
  return (await response.json()) as Schemas["TenantMutationResponse"];
}

test("tenant directory focuses on names, archived records and tenant creation", async ({
  page,
  request,
}, testInfo) => {
  const term = `Directory ${crypto.randomUUID().slice(0, 8)}`;
  const active = await tenant(request, `Alex ${term}`);
  const archived = await tenant(request, `Robin ${term}`);
  const archivedResponse = await request.post(`/api/tenants/${archived.id}/archive`, {
    data: {
      expectedRevision: archived.profile.revision,
      idempotencyKey: crypto.randomUUID(),
      confirmed: true,
    },
  });
  expect(archivedResponse.ok(), await archivedResponse.text()).toBe(true);
  const reads: string[] = [];
  page.on("request", (entry) => {
    if (new URL(entry.url()).pathname === "/api/operator/search") reads.push(entry.url());
  });
  await page.goto("/tenants");
  const directory = page.getByRole("region", { name: "Tenant directory", exact: true });
  await expect(
    directory.getByRole("heading", { name: "Find a tenant", exact: true }),
  ).toBeVisible();
  await expect(directory.getByRole("button", { name: "Create tenant", exact: true })).toBeVisible();
  await expect(directory.getByText(/One identity|Party revision|multiple roles/)).toHaveCount(0);
  await expect(
    directory.getByRole("region", { name: "Find shared identity", exact: true }),
  ).toHaveCount(0);
  await expect(
    directory.getByRole("link", { name: /Properties|Providers|Create identity/ }),
  ).toHaveCount(0);
  expect(reads).toHaveLength(0);
  const search = directory.getByRole("searchbox", { name: "Search tenants", exact: true });
  await search.fill(term);
  await expect(
    directory.getByRole("link", { name: active.displayName, exact: true }),
  ).toBeVisible();
  await expect(
    directory.getByRole("link", { name: archived.displayName, exact: true }),
  ).toHaveCount(0);
  await expect(directory.getByText("1 matching tenant", { exact: true })).toBeVisible();
  await expect(search).toBeFocused();
  await directory.getByRole("checkbox", { name: "Include archived tenants" }).check();
  await expect(
    directory.getByRole("link", { name: archived.displayName, exact: true }),
  ).toContainText("Archived");
  await expect(directory.getByText("2 matching tenants", { exact: true })).toBeVisible();
  expect(reads).toHaveLength(2);
  expect(reads.every((url) => new URL(url).searchParams.get("limit") === "20")).toBe(true);
  await expect(directory).not.toContainText(active.id);
  for (const theme of ["light", "dark"]) {
    await page.evaluate((value) => {
      document.documentElement.dataset.theme = value;
    }, theme);
    for (const width of [1280, 390]) {
      await page.setViewportSize({ width, height: 900 });
      expect(
        await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
      ).toBe(true);
      const cards = await directory.locator(".tenant-directory-card").all();
      const first = await cards[0].boundingBox();
      const second = await cards[1].boundingBox();
      expect(first).not.toBeNull();
      expect(second).not.toBeNull();
      if (first && second)
        expect(second.y >= first.y + first.height || second.x >= first.x + first.width).toBe(true);
      await directory.screenshot({ path: testInfo.outputPath(`tenants-${theme}-${width}.png`) });
    }
    await page.evaluate(axe.source);
    const violations = await page.evaluate(async () =>
      (
        await window.axe.run(".tenant-directory", {
          runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21aa"] },
        })
      ).violations.map((item) => item.id),
    );
    expect(violations).toEqual([]);
  }
  await directory.getByRole("link", { name: active.displayName, exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/tenants\\?identity=${active.id}`));
  await page.getByRole("link", { name: "← Back to Tenants", exact: true }).click();
  await expect(search).toHaveValue(term);
  await directory.getByRole("button", { name: "Create tenant", exact: true }).click();
  await expect(page).toHaveURL(/\/tenants\?workflow=tenant.create$/);
});

test("tenant search distinguishes retryable failure, no matches and incomplete input", async ({
  page,
}) => {
  let attempts = 0;
  await page.route("**/api/operator/search?*", async (route) => {
    attempts += 1;
    if (attempts === 1)
      await route.fulfill({ status: 503, json: { detail: "Temporarily unavailable" } });
    else await route.continue();
  });
  await page.goto("/tenants?q=NoSuchTenantDirectory");
  const directory = page.getByRole("region", { name: "Tenant directory", exact: true });
  await expect(directory.getByRole("alert")).toContainText("Tenant search is unavailable");
  await expect(directory.getByRole("heading", { name: "No tenants found" })).toHaveCount(0);
  await directory.getByRole("button", { name: "Retry search", exact: true }).click();
  await expect(directory.getByRole("heading", { name: "No tenants found" })).toBeVisible();
  expect(attempts).toBe(2);
  const search = directory.getByRole("searchbox", { name: "Search tenants", exact: true });
  await search.fill("N");
  await expect(
    directory.getByRole("heading", { name: "Find a tenant", exact: true }),
  ).toBeVisible();
  await expect(directory.getByRole("heading", { name: "No tenants found" })).toHaveCount(0);
  await directory.getByRole("checkbox", { name: "Include archived tenants" }).check();
  expect(attempts).toBe(2);
  await search.fill("");
  await expect(page).toHaveURL(/\/tenants\?archived=true$/);
});

test("tenant browsing can retry a failed list without inventing an empty result", async ({
  page,
}) => {
  let attempts = 0;
  await page.route("**/api/operator/tenants?*", async (route) => {
    attempts += 1;
    if (attempts === 1)
      await route.fulfill({ status: 503, json: { detail: "Temporarily unavailable" } });
    else await route.continue();
  });
  await page.goto("/tenants?browse=true");
  const directory = page.getByRole("region", { name: "Tenant directory", exact: true });
  await expect(directory.getByRole("alert")).toContainText("Tenant list is unavailable");
  await expect(directory.getByRole("heading", { name: "No tenants found" })).toHaveCount(0);
  await directory.getByRole("button", { name: "Retry loading tenants", exact: true }).click();
  await expect(directory.getByRole("alert")).toHaveCount(0);
  await expect(directory.locator(".tenant-directory-count, .tenant-directory-empty")).toBeVisible();
  expect(attempts).toBe(2);
});

test("browse tenants pages without gaps and preserves browse on return and archived filtering", async ({
  page,
  request,
}) => {
  const term = `AAA Browse ${crypto.randomUUID().slice(0, 8)}`;
  const records = [];
  for (let index = 0; index < 21; index++)
    records.push(await tenant(request, `${term} ${String(index).padStart(2, "0")}`));
  const archived = await tenant(request, `${term} Archived`);
  const response = await request.post(`/api/tenants/${archived.id}/archive`, {
    data: {
      expectedRevision: archived.profile.revision,
      idempotencyKey: crypto.randomUUID(),
      confirmed: true,
    },
  });
  expect(response.ok(), await response.text()).toBe(true);
  const reads: string[] = [];
  const details: string[] = [];
  page.on("request", (entry) => {
    const path = new URL(entry.url()).pathname;
    if (path === "/api/operator/tenants") reads.push(entry.url());
    if (/^\/api\/tenants\/[0-9a-f-]+$/.test(path)) details.push(path);
  });
  await page.goto("/tenants");
  const directory = page.getByRole("region", { name: "Tenant directory", exact: true });
  const browseHistoryLength = await page.evaluate(() => history.length);
  await directory.getByRole("button", { name: "Browse tenants", exact: true }).click();
  await expect(page).toHaveURL(/browse=true/);
  expect(await page.evaluate(() => history.length)).toBe(browseHistoryLength);
  const cards = directory.locator(".tenant-directory-card");
  await expect(cards).toHaveCount(20);
  const seen: string[] = [];
  for (let pageIndex = 0; pageIndex < 20; pageIndex++) {
    seen.push(
      ...(await cards.evaluateAll((entries) =>
        entries.map((entry) => entry.getAttribute("href")!),
      )),
    );
    const next = directory.getByRole("button", { name: "Next tenants", exact: true });
    if (!(await next.count())) break;
    const before = await cards.first().getAttribute("href");
    await next.click();
    await expect(cards.first()).not.toHaveAttribute("href", before!);
  }
  expect(new Set(seen).size).toBe(seen.length);
  for (const record of records) expect(seen).toContain(`/tenants?identity=${record.id}`);
  expect(seen).not.toContain(`/tenants?identity=${archived.id}`);
  expect(reads.every((url) => new URL(url).searchParams.get("limit") === "20")).toBe(true);
  expect(details).toHaveLength(0);
  await directory.getByRole("button", { name: "Back to first page", exact: true }).click();
  await directory.getByRole("checkbox", { name: "Include archived tenants" }).check();
  await expect(page).not.toHaveURL(/cursor=/);
  const included: string[] = [];
  for (let pageIndex = 0; pageIndex < 20; pageIndex++) {
    await expect(cards.first()).toBeVisible();
    included.push(
      ...(await cards.evaluateAll((entries) =>
        entries.map((entry) => entry.getAttribute("href")!),
      )),
    );
    const next = directory.getByRole("button", { name: "Next tenants", exact: true });
    if (!(await next.count())) break;
    const before = await cards.first().getAttribute("href");
    await next.click();
    await expect(cards.first()).not.toHaveAttribute("href", before!);
  }
  expect(included).toContain(`/tenants?identity=${archived.id}`);
  const selected = cards.first();
  const returnUrl = page.url();
  await selected.click();
  await page.getByRole("link", { name: "← Back to Tenants", exact: true }).click();
  await expect(page).toHaveURL(returnUrl);
  await directory.getByRole("searchbox", { name: "Search tenants", exact: true }).fill(term);
  await expect(page).toHaveURL(/q=/);
  await expect(page).not.toHaveURL(/browse=true|cursor=/);
  await expect(cards).toHaveCount(20);
});
