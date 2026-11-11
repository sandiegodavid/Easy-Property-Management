import { expect, test } from "@playwright/test";

for (const colorScheme of ["light", "dark"] as const) {
  for (const width of [320, 1280]) {
    test(`held hosted status is readable and keyboard-operable: ${colorScheme}, ${width}`, async ({
      page,
    }) => {
      await page.emulateMedia({ colorScheme });
      await page.setViewportSize({ width, height: 700 });
      const requests: string[] = [];
      page.on("request", (request) => requests.push(`${request.method()} ${request.url()}`));
      const response = await page.goto("/properties?workflow=portfolio.property.create");
      expect(response?.status()).toBe(503);
      await expect(page).toHaveTitle("Temporarily unavailable | Easy Property Management");
      await expect(page.getByRole("main")).toBeVisible();
      await expect(page.getByRole("heading", { level: 1 })).toHaveText("Temporarily unavailable");
      await expect(page.locator("time")).toContainText("UTC");
      await expect(page.getByText("Keep any open form.", { exact: false })).toBeVisible();
      expect(await page.locator("script, form, input").count()).toBe(0);
      expect(
        await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
      ).toBe(true);
      const background = await page
        .locator("main")
        .evaluate((node) => getComputedStyle(node).backgroundColor);
      expect(background).toBe(colorScheme === "dark" ? "rgb(38, 49, 43)" : "rgb(240, 244, 239)");
      await page.keyboard.press("Tab");
      await expect(page.getByRole("link", { name: "Check availability again" })).toBeFocused();
      const refreshed = page.waitForResponse((r) => r.request().isNavigationRequest());
      await page.keyboard.press("Enter");
      expect((await refreshed).status()).toBe(503);
      await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
      // One explicit refresh, no API dispatch, command replay or polling loop.
      expect(requests.filter((request) => request.endsWith("18753/"))).toHaveLength(1);
      expect(requests.filter((request) => request.includes("?workflow="))).toHaveLength(1);
      expect(requests.every((request) => request.startsWith("GET "))).toBe(true);
      expect(requests.some((request) => request.includes("/api/"))).toBe(false);
    });
  }
}
