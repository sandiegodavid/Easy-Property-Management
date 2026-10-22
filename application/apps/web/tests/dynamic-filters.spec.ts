import { expect, test } from "@playwright/test";
test.use({ timezoneId: "America/Los_Angeles" });

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
  await page.goForward();
  await expect(page.getByLabel("Search providers", { exact: true })).toHaveValue("Latest");
  await page.getByText("More filters", { exact: true }).click();
  await expect(page.getByRole("combobox", { name: "Show providers", exact: true })).toHaveValue(
    "all",
  );
  await expect(page.getByLabel("Has references", { exact: true })).toBeChecked();
});

for (const directory of [
  {
    menu: "Properties",
    search: "Property name or address",
    select: "State",
    key: "state",
    option: "archived",
  },
  { menu: "Owners", search: "Search", select: "State", key: "state", option: "archived" },
  { menu: "Maintenance", search: null, select: "Status", key: "status", option: "resolved" },
]) {
  test(`${directory.menu} filters replace history and browser Forward restores all controls`, async ({
    page,
  }) => {
    await page.setViewportSize({ width: 1280, height: 1600 });
    await page.goto("/settings");
    await page
      .getByRole("navigation", { name: "Primary navigation" })
      .getByRole("link", { name: directory.menu, exact: true })
      .click();
    const input = directory.search ? page.getByLabel(directory.search, { exact: true }) : null;
    const choice = page.getByRole("combobox", { name: directory.select, exact: true });
    await expect(choice).toBeVisible();
    const length = await page.evaluate(() => history.length);
    if (input) await input.fill("Contract");
    await choice.selectOption(directory.option);
    await expect
      .poll(() => new URL(page.url()).searchParams.get(directory.key))
      .toBe(directory.option);
    if (input) await expect(page).toHaveURL(/q=Contract/);
    expect(await page.evaluate(() => history.length)).toBe(length);
    const filtered = page.url();
    await page.goBack();
    await expect(page).toHaveURL(/\/settings$/);
    await page.goForward();
    await expect(page).toHaveURL(filtered);
    await expect(choice).toHaveValue(directory.option);
    if (input) await expect(input).toHaveValue("Contract");
  });
}

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

test("Intake date pickers use browser time and send zoned instants", async ({ page }) => {
  const requests: string[] = [];
  page.on("request", (request) => {
    if (new URL(request.url()).pathname === "/api/intake/sources") requests.push(request.url());
  });
  await page.goto("/conversations?intake=true");
  await expect(page.getByText(/^\d+ retained sources? on this page\.$/)).toBeVisible();
  const from = page.getByLabel("Received from", { exact: true });
  await expect(from).toHaveAttribute("type", "datetime-local");
  await expect(from).toHaveAccessibleDescription("Your time zone: America/Los_Angeles");
  await from.fill("2026-03-08T02:30");
  await page.getByRole("combobox", { name: "Channel", exact: true }).selectOption("email");
  expect(await from.evaluate((input: HTMLInputElement) => input.validity.valid)).toBe(false);
  expect(requests).toHaveLength(1);
  await from.fill("2026-10-01T10:00");
  await page.getByRole("combobox", { name: "Channel", exact: true }).selectOption("email");
  await expect(page).toHaveURL(/receivedFrom=2026-10-01T17%3A00%3A00.000Z/);
  await expect.poll(() => requests.length).toBe(2);
  expect(new URL(requests[1]).searchParams.get("channel")).toBe("email");
  await page.reload();
  await expect(from).toHaveValue("2026-10-01T10:00");
  await from.fill("");
  await expect.poll(() => new URL(page.url()).searchParams.has("receivedFrom")).toBe(false);
  await page.goto("/conversations?intake=true&receivedFrom=2026-11-01T01%3A30%3A00-08%3A00");
  await expect(from).toHaveValue("2026-11-01T01:30");
  await page.getByRole("combobox", { name: "Channel", exact: true }).selectOption("sms");
  await expect
    .poll(() => new URL(page.url()).searchParams.get("receivedFrom"))
    .toBe("2026-11-01T01:30:00-08:00");
});

test("Maintenance property picker loads bounded pages and local dates become UTC filters", async ({
  page,
}) => {
  const first = "00000000-0000-4000-8000-000000000111";
  const second = "00000000-0000-4000-8000-000000000112";
  const cursors: (string | null)[] = [];
  await page.route("**/api/operator/properties?*", async (route) => {
    const url = new URL(route.request().url());
    expect(url.searchParams.get("limit")).toBe("50");
    cursors.push(url.searchParams.get("cursor"));
    const more = url.searchParams.has("cursor");
    await route.fulfill({
      json: {
        items: [
          {
            id: more ? second : first,
            displayName: more ? "Second House" : "First House",
            status: more ? "archived" : "active",
          },
        ],
        nextCursor: more ? null : "next-properties",
      },
    });
  });
  await page.route(`**/api/properties/${second}`, (route) =>
    route.fulfill({ json: { displayName: "Second House" } }),
  );
  await page.goto("/maintenance");
  const filters = page.getByRole("form", { name: "Maintenance filters" });
  const picker = filters.getByRole("combobox", { name: "Property", exact: true });
  await expect(picker.locator("option")).toHaveText(["All properties", "First House"]);
  await filters.getByRole("button", { name: "Load more properties" }).click();
  await picker.selectOption(second);
  await expect(page).toHaveURL(new RegExp(`propertyId=${second}`));
  expect(cursors).toEqual([null, "next-properties"]);
  await expect(picker).toHaveValue(second);
  await filters.getByText("More filters", { exact: true }).click();
  const from = filters.getByLabel("Recorded from", { exact: true });
  await from.fill("2026-01-02T10:00");
  await expect(page).toHaveURL(/reportedFrom=2026-01-02T18%3A00%3A00.000Z/);
  await filters.getByRole("button", { name: "Clear filters" }).click();
  await expect(picker).toHaveValue("");
  await expect(from).toHaveValue("");
});
