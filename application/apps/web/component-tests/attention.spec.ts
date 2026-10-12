import { expect, test } from "@playwright/test";

test("attention and calendar disclosures preserve input and dates in both themes at narrow width", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/component-tests/attention.html");
  const waiting = page.getByRole("region", { name: "Waiting", exact: true });
  const summary = waiting.getByRole("button", { name: /Review repair appointment/ });
  expect(await summary.locator("input, a, select, button").count()).toBe(0);
  await summary.focus();
  await page.keyboard.press("Enter");
  await waiting.getByLabel("Follow-up note").fill("Call tomorrow");
  await expect(summary).toHaveAttribute("aria-expanded", "true");
  await waiting.getByRole("button", { name: "Collapse details" }).click();
  await expect(summary).toBeFocused();
  await page.keyboard.press("Space");
  await expect(waiting.getByLabel("Follow-up note")).toHaveValue("Call tomorrow");
  await page.getByRole("button", { name: "Switch theme" }).click();
  await expect(waiting.getByLabel("Follow-up note")).toHaveValue("Call tomorrow");
  await summary.click({ position: { x: 5, y: 5 } });
  await expect(summary).toHaveAttribute("aria-expanded", "false");
  await expect(page.getByRole("button", { name: /All-day visit/ })).toContainText(
    "2026-10-13 · All day",
  );
  await expect(page.getByRole("button", { name: /Timed visit/ })).toContainText(
    "2026-10-13T17:00:00Z · America/Los_Angeles",
  );
  const ids = await page
    .locator("button[aria-controls]")
    .evaluateAll((buttons) => buttons.map((button) => button.getAttribute("aria-controls")));
  expect(new Set(ids).size).toBe(ids.length);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
});
