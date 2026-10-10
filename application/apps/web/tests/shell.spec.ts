import { expect, test } from "@playwright/test";
import type { components } from "@epm/contracts/generated";

test("preferences persist through reload, hiding and reordering keep contextual routes reachable", async ({
  page,
}) => {
  await page.goto("/settings/navigation");
  await page.getByRole("radio", { name: "Dark", exact: true }).check();
  await page.getByRole("checkbox", { name: "Owners", exact: true }).uncheck();
  await page.getByRole("button", { name: "Move Providers up", exact: true }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page.getByRole("button", { name: "Save preferences", exact: true }).click();
  await expect(page.getByText("Preferences saved.")).toBeVisible();
  await page.reload();
  await expect(page.getByRole("radio", { name: "Dark", exact: true })).toBeChecked();
  await expect(page.locator("fieldset ol li").nth(4)).toContainText("Providers");
  await expect(
    page
      .getByRole("navigation", { name: "Primary navigation" })
      .getByRole("link", { name: "Owners", exact: true }),
  ).toHaveCount(0);
  await page.getByText("More", { exact: true }).first().click();
  await page
    .getByRole("navigation", { name: "Hidden destinations" })
    .getByRole("link", { name: "Owners" })
    .click();
  await expect(page).toHaveURL(/\/owners$/);
  await page.goto("/owners/00000000-0000-4000-8000-000000000001/money");
  await page.getByRole("link", { name: "View in Money" }).click();
  await expect(page).toHaveURL(/\/money\?ownerId=/);
  await page.getByRole("button", { name: "Remove owner filter" }).click();
  await expect(page).toHaveURL(/\/money$/);
  await page.goto("/settings");
  await page.getByRole("button", { name: "Restore defaults" }).click();
  await page.getByRole("button", { name: "Save preferences", exact: true }).click();
  await expect(page.getByText("Preferences saved.")).toBeVisible();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
});

test("missing destination capability omits navigation and explains direct access", async ({
  page,
}) => {
  await page.route("**/api/operator/bootstrap", async (route) => {
    const response = await route.fetch();
    const bootstrap = (await response.json()) as components["schemas"]["BootstrapResponse"];
    await route.fulfill({ json: { ...bootstrap, capabilities: [] } });
  });
  await page.goto("/owners");
  await expect(page.getByRole("heading", { name: "Page unavailable" })).toBeVisible();
  await expect(
    page
      .getByRole("navigation", { name: "Primary navigation" })
      .getByRole("link", { name: "Owners" }),
  ).toHaveCount(0);
  await page.getByRole("link", { name: "Return Home" }).click();
  await expect(page).toHaveURL(/\/home$/);
});

test("stale preferences preserve choices and require current revision before saving", async ({
  page,
}) => {
  await page.goto("/settings");
  await page.getByRole("radio", { name: "Dark", exact: true }).check();
  const concurrentStatus = await page.evaluate(async () => {
    const current = (await (
      await fetch("/api/operator/preferences")
    ).json()) as components["schemas"]["PreferenceResponse"];
    const result = await fetch("/api/operator/preferences", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        appearance: current.appearance,
        destinationOrder: current.destinationOrder,
        hiddenDestinationIds: current.hiddenDestinationIds,
        expectedRevision: current.revision,
        idempotencyKey: crypto.randomUUID(),
      }),
    });
    return result.status;
  });
  expect(concurrentStatus).toBe(200);
  await page.getByRole("button", { name: "Save preferences", exact: true }).click();
  await expect(
    page.getByText("Preferences changed in another window.", { exact: false }),
  ).toBeVisible();
  await expect(page.getByRole("radio", { name: "Dark", exact: true })).toBeChecked();
  await expect(page.getByRole("button", { name: "Save preferences", exact: true })).toBeDisabled();
  await page.getByRole("button", { name: "Load current preferences" }).click();
  await expect(page.getByRole("button", { name: "Save preferences", exact: true })).toBeEnabled();
});

test("unknown save outcomes retry only explicitly with the original request", async ({ page }) => {
  const bodies: string[] = [];
  await page.route("**/api/operator/preferences", async (route) => {
    bodies.push(route.request().postData() ?? "");
    if (bodies.length === 1) {
      const committed = await route.fetch();
      expect(committed.status()).toBe(200);
      await route.abort();
    } else await route.continue();
  });
  await page.goto("/settings");
  await page.getByRole("button", { name: "Save preferences", exact: true }).click();
  await expect(page.getByRole("button", { name: "Retry save" })).toBeVisible();
  expect(bodies).toHaveLength(1);
  await page.getByRole("button", { name: "Retry save" }).click();
  await expect(page.getByText("Preferences saved.")).toBeVisible();
  expect(bodies).toHaveLength(2);
  expect(bodies[1]).toBe(bodies[0]);
});

test("narrow navigation, keyboard operation, nested history and unsupported sections", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/home");
  const navigation = page.locator(".narrow-nav > summary");
  await navigation.focus();
  await page.keyboard.press("Enter");
  await page.getByRole("link", { name: "Properties", exact: true }).click();
  await expect(page).toHaveURL(/\/properties$/);
  await expect(page.locator(".narrow-nav")).not.toHaveAttribute("open", "");
  await page.goto("/properties/00000000-0000-4000-8000-000000000001/units");
  await page.getByRole("link", { name: "details", exact: true }).click();
  await page.goBack();
  await expect(page).toHaveURL(/\/units$/);
  await page.reload();
  await expect(page.getByRole("heading", { name: "units", exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
  const unsupported = await page.goto("/settings/unsupported");
  expect(unsupported?.status()).toBe(404);
  await page.goto("/ai/review/00000000-0000-4000-8000-000000000001");
  await expect(page.getByRole("heading", { name: "Page unavailable" })).toBeVisible();
});
