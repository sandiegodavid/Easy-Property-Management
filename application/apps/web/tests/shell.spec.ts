import { expect, test } from "@playwright/test";
import type { components } from "@epm/contracts/generated";

test("brand follows the selected appearance on desktop and mobile after reload", async ({
  page,
}) => {
  await page.goto("/settings/navigation");
  for (const appearance of ["Dark", "Light"] as const) {
    await page.getByRole("radio", { name: appearance, exact: true }).check();
    for (const reload of [false, true]) {
      if (reload) await page.reload();
      for (const width of [1280, 390]) {
        await page.setViewportSize({ width, height: 900 });
        const brand = page.locator(".workspace-brand:visible img");
        await expect(brand).toHaveCount(1);
        await expect(brand).toBeVisible();
        const asset = width < 768 ? "logo-4" : "logo-text-4";
        await expect
          .poll(() => brand.evaluate((image) => (image as HTMLImageElement).currentSrc))
          .toMatch(new RegExp(`${asset}-${appearance.toLowerCase()}[^/]*\\.png$`));
        await expect
          .poll(() => brand.evaluate((image) => (image as HTMLImageElement).naturalWidth))
          .toBeGreaterThan(0);
      }
    }
  }
});

test("sidebar navigation keeps the viewport and shell position stable", async ({ page }) => {
  await page.goto("/properties");
  await expect(page.getByRole("heading", { name: "Properties", exact: true })).toBeVisible();
  await page.evaluate(() => window.scrollTo(0, 0));
  const initial = await page.locator(".ui-brand").boundingBox();
  const nav = page.getByRole("navigation", { name: "Primary navigation" });
  const labels = await nav.getByRole("link").allTextContents();
  expect(labels.indexOf("Tenants")).toBe(labels.indexOf("Owners") + 1);
  await expect(nav.getByRole("link", { name: "Tenants", exact: true })).toHaveAttribute(
    "href",
    "/tenants",
  );
  for (const name of ["Owners", "Tenants", "Leasing", "Properties"]) {
    await nav.getByRole("link", { name, exact: true }).click();
    await expect(page.getByRole("heading", { name, level: 2, exact: true })).toBeVisible();
    await expect(page.locator("#workspace-content")).toBeFocused();
    expect(await page.evaluate(() => window.scrollY)).toBe(0);
    const current = await page.locator(".ui-brand").boundingBox();
    expect(current).toEqual(initial);
  }
});

test("Settings and live workspace/backup status sit at the sidebar bottom", async ({ page }) => {
  await page.route("**/api/workspace/backup-status", (route) =>
    route.fulfill({ json: { lastSuccessAt: "2026-10-14T15:10:00Z", needsAttention: false } }),
  );
  await page.goto("/properties");
  const footer = page.locator(".sidebar-footer");
  await expect(footer.getByRole("link", { name: "Settings", exact: true })).toBeVisible();
  await expect(footer).toContainText("Local workspace connected.");
  await expect(footer).toContainText("Last backup");
  await expect(footer.locator("time")).toHaveAttribute("datetime", "2026-10-14T15:10:00Z");
  const more = await page.locator(".wide-nav").boundingBox();
  const bottom = await footer.boundingBox();
  expect(bottom!.y).toBeGreaterThanOrEqual(more!.y + more!.height);
  expect(bottom!.y + bottom!.height).toBeLessThanOrEqual(page.viewportSize()!.height);
  await footer.getByRole("link", { name: "Settings", exact: true }).click();
  await expect(page).toHaveURL(/\/settings$/);
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(footer.getByRole("link", { name: "Settings", exact: true })).toBeVisible();
});

test("More appears only for overflow and reveals a scrollable remaining menu", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/properties");
  const menu = page.locator(".wide-nav");
  const primary = menu.getByRole("navigation", { name: "Primary navigation" });
  await expect(primary.getByRole("link")).toHaveCount(8);
  await expect(menu.locator(".more-destinations")).toHaveCount(0);

  await page.setViewportSize({ width: 1280, height: 450 });
  const more = menu.locator(".more-destinations");
  await expect(more).toBeVisible();
  const count = await primary.getByRole("link").count();
  expect(count).toBeLessThan(8);
  await more.locator("summary").focus();
  await page.keyboard.press("Enter");
  const remaining = more.getByRole("navigation", { name: "Hidden destinations" });
  await expect(remaining.getByRole("link")).toHaveCount(8 - count);
  expect(await remaining.evaluate((element) => element.scrollHeight > element.clientHeight)).toBe(
    true,
  );
  const settings = await page.locator(".sidebar-footer").boundingBox();
  const remainingBox = await remaining.boundingBox();
  expect(remainingBox!.y + remainingBox!.height).toBeLessThanOrEqual(settings!.y);
  await remaining.getByRole("link", { name: "Providers", exact: true }).click();
  await expect(page).toHaveURL(/\/providers$/);

  await page.setViewportSize({ width: 1280, height: 900 });
  await expect(primary.getByRole("link")).toHaveCount(8);
  await expect(menu.locator(".more-destinations")).toHaveCount(0);
});

test("sidebar distinguishes no backup, attention and unavailable status", async ({ page }) => {
  for (const state of ["none", "attention", "unavailable"] as const) {
    await page.route("**/api/workspace/backup-status", (route) =>
      state === "unavailable"
        ? route.fulfill({ status: 503, json: { detail: "Unavailable" } })
        : route.fulfill({ json: { lastSuccessAt: null, needsAttention: state === "attention" } }),
    );
    await page.goto("/properties");
    await expect(page.locator(".sidebar-status")).toContainText(
      state === "none"
        ? "No successful backup yet"
        : state === "attention"
          ? "Backup needs attention"
          : "Backup status unavailable",
    );
    await page.unroute("**/api/workspace/backup-status");
  }
});

test("preferences persist through reload, hiding and reordering keep contextual routes reachable", async ({
  page,
}) => {
  await page.goto("/settings/navigation");
  await page.getByRole("radio", { name: "Dark", exact: true }).check();
  await page.reload();
  await expect(page.getByRole("radio", { name: "Dark", exact: true })).toBeChecked();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page.getByRole("checkbox", { name: "Owners", exact: true }).uncheck();
  await page.getByRole("button", { name: "Move Providers up", exact: true }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page.getByRole("button", { name: "Save preferences", exact: true }).click();
  await expect(page.getByText("Preferences saved.")).toBeVisible();
  await page.reload();
  await expect(page.getByRole("radio", { name: "Dark", exact: true })).toBeChecked();
  const order = await page.locator("fieldset ol li").allTextContents();
  expect(order.findIndex((text) => text.includes("Providers"))).toBe(
    order.findIndex((text) => text.includes("Maintenance")) - 1,
  );
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
  await page.getByRole("link", { name: "Property setup", exact: true }).click();
  await page.goBack();
  await expect(page).toHaveURL(/\/units$/);
  await page.reload();
  await expect(page.getByRole("heading", { name: "units", exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
  const unsupported = await page.goto("/settings/unsupported");
  expect(unsupported?.status()).toBe(404);
  await page.goto("/settings/ai");
  await expect(page.getByRole("heading", { name: "Built-in AI assistance" })).toBeVisible();
});
