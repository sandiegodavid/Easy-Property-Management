import { expect, test } from "@playwright/test";

test("provider search debounces typing, retains focus and clears an old page", async ({ page }) => {
  const searches: string[] = [];
  await page.route("**/api/providers?*", async (route) => {
    const url = new URL(route.request().url());
    if (url.searchParams.has("search")) searches.push(url.searchParams.get("search")!);
    await route.fulfill({
      json: { items: [], nextCursor: url.searchParams.size === 2 ? "next-page" : null },
    });
  });
  await page.goto("/providers");
  await page.getByRole("button", { name: "Next Providers", exact: true }).click();
  await expect(page).toHaveURL(/cursor=next-page/);
  const input = page.getByLabel("Search providers", { exact: true });
  await input.focus();
  const before = await input.boundingBox();
  await input.pressSequentially("Acme Plumbing", { delay: 20 });
  await expect(page).toHaveURL(/q=Acme\+Plumbing/);
  expect(new URL(page.url()).searchParams.has("cursor")).toBe(false);
  await expect(input).toBeFocused();
  await expect(input).toHaveValue("Acme Plumbing");
  expect((await input.boundingBox())?.y).toBe(before?.y);
  await expect.poll(() => searches).toEqual(["Acme Plumbing"]);
  await expect(page.getByRole("button", { name: /Apply Provider filters/ })).toHaveCount(0);
});

test("dynamic dropdowns preserve pending text and browser Back restores the filters", async ({
  page,
}) => {
  await page.route("**/api/providers?*", async (route) => {
    const url = new URL(route.request().url());
    await route.fulfill({
      json: { items: [], nextCursor: url.searchParams.has("cursor") ? null : "next-page" },
    });
  });
  await page.goto("/providers?q=Earlier&archiveState=archived");
  await page.getByRole("button", { name: "Next Providers", exact: true }).click();
  await expect(page).toHaveURL(/cursor=next-page/);
  await page.getByLabel("Search providers", { exact: true }).fill("Latest");
  await page.getByText("More filters", { exact: true }).click();
  await page.getByRole("combobox", { name: "Show providers", exact: true }).selectOption("all");
  await expect(page).toHaveURL(/q=Latest&archiveState=all/);
  await page.getByLabel("Has references", { exact: true }).check();
  await expect(page).toHaveURL(/hasReference=true/);
  await page.goBack();
  await expect(page.getByLabel("Search providers", { exact: true })).toHaveValue("Earlier");
  await page.getByText("More filters", { exact: true }).click();
  await expect(page.getByRole("combobox", { name: "Show providers", exact: true })).toHaveValue(
    "archived",
  );
  await expect(page.getByLabel("Has references", { exact: true })).not.toBeChecked();
});

test("invalid money ranges retain input without sending a request, then apply when corrected", async ({
  page,
}) => {
  const requested: string[] = [];
  page.on("request", (request) => {
    if (new URL(request.url()).pathname === "/api/money/properties") requested.push(request.url());
  });
  await page.goto("/money?tab=reporting");
  await page.getByLabel("Reporting from (required)").fill("2026-03-01");
  await page.getByLabel("Reporting through (required)").fill("2026-02-28");
  await expect(page.getByRole("alert")).toHaveText(
    "The start date must be on or before the end date.",
  );
  expect(requested).toHaveLength(0);
  await expect(page.getByLabel("Reporting from (required)")).toHaveValue("2026-03-01");
  await page.getByLabel("Reporting through (required)").fill("2026-03-31");
  await expect(page).toHaveURL(/fromOn=2026-03-01&throughOn=2026-03-31/);
  await expect.poll(() => requested.length).toBe(1);
  await expect(page.getByText("The start date must be on or before the end date.")).toHaveCount(0);
});

test("leaving a filter page cancels an unfinished search", async ({ page }) => {
  const requested: string[] = [];
  page.on("request", (request) => {
    if (new URL(request.url()).pathname === "/api/providers") requested.push(request.url());
  });
  await page.goto("/providers");
  await expect(page.locator(".provider-directory-count, .provider-directory-empty")).toBeVisible();
  await page.getByLabel("Search providers", { exact: true }).fill("Do not apply");
  await page
    .getByRole("navigation", { name: "Primary navigation" })
    .getByRole("link", { name: "Owners", exact: true })
    .click();
  await expect(page.getByRole("heading", { name: "Owners", exact: true })).toBeVisible();
  await page.waitForTimeout(400);
  expect(requested.every((url) => !new URL(url).searchParams.has("search"))).toBe(true);
  await expect(page).toHaveURL(/\/owners$/);
});

test("Intake timestamp filters wait for a complete offset before requesting sources", async ({
  page,
}) => {
  const requests: string[] = [];
  page.on("request", (request) => {
    if (new URL(request.url()).pathname === "/api/intake/sources") requests.push(request.url());
  });
  await page.goto("/conversations?intake=true");
  await expect(page.getByText(/sources on this bounded page/)).toBeVisible();
  const from = page.getByRole("textbox", { name: "Received from", exact: true });
  await from.fill("2026-10-");
  await page.getByRole("combobox", { name: "Channel", exact: true }).selectOption("email");
  expect(await from.evaluate((input: HTMLInputElement) => input.validity.valid)).toBe(false);
  expect(requests).toHaveLength(1);
  await from.fill("2026-10-01T10:00:00-07:00");
  await expect(page).toHaveURL(/receivedFrom=2026-10-01T10%3A00%3A00-07%3A00/);
  await expect.poll(() => requests.length).toBe(2);
  expect(new URL(requests[1]).searchParams.get("channel")).toBe("email");
});
