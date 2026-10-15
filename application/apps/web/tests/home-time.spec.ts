import { expect, test } from "@playwright/test";
import type { components } from "@epm/contracts/generated";

test.use({ timezoneId: "America/Los_Angeles", locale: "en-US" });

for (const [instant, local] of [
  ["2026-01-02T07:30:00Z", "Jan 1, 2026, 11:30 PM"],
  ["2026-07-02T07:30:00Z", "Jul 2, 2026, 12:30 AM"],
] as const) {
  test(`Home displays operator-local card capture time for ${instant}`, async ({ page }) => {
    await page.route("**/api/operator/home?*", async (route) => {
      const response = await route.fetch();
      const data = (await response.json()) as components["schemas"]["HomeResponse"];
      data.asOf = instant;
      data.money.capture.asOf = instant;
      data.money.capture.checkedAt = instant;
      await route.fulfill({ json: data });
    });
    await page.goto("/home");
    const summary = page.getByRole("region", { name: "Home summary", exact: true });
    await expect(summary.locator("time")).toHaveCount(0);
    const money = page.getByRole("region", { name: "Recorded money", exact: true });
    await expect(money).toContainText(`As of ${local} · America/Los_Angeles`);
    await expect(money.locator(".home-capture time")).toHaveAttribute("datetime", instant);
    await expect(money).not.toContainText("Checked at");
    await expect(summary).not.toContainText(instant);
  });
}
