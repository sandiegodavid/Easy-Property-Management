import { expect, test } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  await page.goto("/component-tests/index.html");
});

test("disclosure actions hide by bar width without hiding status or collapse controls", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  const container = page.getByTestId("action-disclosure-container");
  const action = container.locator(".ui-summary-action");
  const tooltip = container.getByRole("tooltip");
  await container.evaluate((element) => {
    element.style.width = "600px";
  });
  await expect(action).toBeVisible();
  await container.locator(".ui-summary").hover();
  await expect(tooltip).toBeHidden();
  await container.evaluate((element) => {
    element.style.width = "280px";
  });
  await expect(action).toBeHidden();
  await container.locator(".ui-summary").hover();
  await expect(tooltip).toHaveText("View");
  await expect(tooltip).toBeVisible();
  await expect(page.getByText("Review needed", { exact: true })).toBeVisible();
  const summary = container.getByRole("button", { name: "Responsive action example", exact: true });
  await expect(summary.locator(".ui-chevron")).toBeVisible();
  await summary.focus();
  await page.mouse.move(0, 0);
  await expect(tooltip).toBeVisible();
  await expect(summary).toHaveAccessibleDescription("View");
  await page.keyboard.press("Escape");
  await expect(tooltip).toBeHidden();
  await page.keyboard.press("Enter");
  await expect(summary).toHaveAttribute("aria-expanded", "true");
  await expect(container.getByText("Responsive action details", { exact: true })).toBeVisible();
  await page.keyboard.press("Space");
  await expect(summary).toHaveAttribute("aria-expanded", "false");
  await container.evaluate((element) => {
    element.style.width = "600px";
  });
  await expect(action).toBeVisible();
  await expect(tooltip).toBeHidden();
});

for (const theme of ["light", "dark"]) {
  test(`${theme}: full bar disclosure retains edits, isolates actions and restores focus`, async ({
    page,
  }) => {
    if (theme === "dark") await page.getByRole("button", { name: "Switch theme" }).click();
    const summary = page.getByRole("button", { name: /Example record Display-only/ });
    await expect(page.getByLabel("Note")).toHaveCount(0);
    await summary.focus();
    await page.keyboard.press("Enter");
    await page.getByLabel("Note").fill("Keep this edit");
    await expect(summary).toHaveAttribute("aria-expanded", "true");
    await page.getByRole("button", { name: "Collapse details" }).click();
    await expect(summary).toBeFocused();
    await expect(page.getByLabel("Note")).toBeHidden();
    await page.keyboard.press("Space");
    await expect(page.getByLabel("Note")).toHaveValue("Keep this edit");
    await page.getByRole("button", { name: "Switch theme" }).click();
    await expect(page.getByLabel("Note")).toHaveValue("Keep this edit");
    const controls = await page
      .locator("button[aria-controls]")
      .evaluateAll((buttons) => buttons.map((button) => button.getAttribute("aria-controls")));
    expect(new Set(controls).size).toBe(controls.length);
    await summary.click({ position: { x: 5, y: 5 } });
    await expect(summary).toHaveAttribute("aria-expanded", "false");
  });
}

test("async sections distinguish unavailable, empty, stale and partial; sparse pages can continue", async ({
  page,
}) => {
  for (const kind of ["loading", "error", "unavailable", "empty"]) {
    await page.getByRole("button", { name: kind, exact: true }).click();
    await expect(page.getByRole("table")).toHaveCount(0);
    await expect(page.getByText("Healthy section data")).toBeVisible();
    await expect(page.getByText("No matching records", { exact: true })).toHaveCount(0);
  }
  await expect(page.getByRole("button", { name: "Continue results" })).toBeEnabled();
  for (const kind of ["stale", "partial", "refreshing"]) {
    await page.getByRole("button", { name: kind, exact: true }).click();
    await expect(page.getByRole("table")).toBeVisible();
    await expect(page.getByText("2026-10-10T12:00:00Z")).toBeVisible();
    await expect(page.getByRole("cell", { name: "Unavailable", exact: true })).toBeVisible();
  }
  await page.getByRole("button", { name: "Continue results" }).click();
  await expect(page.getByRole("button", { name: "Continue results" })).toHaveCount(0);
  await page.getByRole("button", { name: "empty", exact: true }).click();
  await expect(page.getByText("No matching records", { exact: true })).toBeVisible();
});

test("confirmation contains focus, cancels safely and announces acknowledged result", async ({
  page,
}) => {
  await page.getByRole("button", { name: /Example record Display-only/ }).click();
  await page.clock.install();
  const trigger = page.getByRole("button", { name: "Archive example" });
  await trigger.click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByRole("button", { name: "Cancel", exact: true })).toBeFocused();
  await page.keyboard.press("Shift+Tab");
  await expect(dialog.getByRole("button", { name: "Confirm archive" })).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(trigger).toBeFocused();
  await trigger.click();
  await dialog.getByRole("button", { name: "Confirm archive" }).click();
  await expect(dialog.getByRole("button", { name: "Confirm archive" })).toBeDisabled();
  await page.keyboard.press("Escape");
  await expect(dialog).toBeVisible();
  await expect(page.getByText("Example archived", { exact: true })).toHaveCount(0);
  await page.clock.fastForward(200);
  await expect(page.getByText("Example archived", { exact: true })).toBeVisible();
  await expect(trigger).toBeFocused();
  await page.getByRole("link", { name: "Enter a name" }).click();
  await expect(page.getByLabel("Name (required)")).toBeFocused();
  await expect(page.getByLabel("Name (required)")).toHaveAttribute("aria-invalid", "true");
});

test("320px and reduced motion keep controls and table usable", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 700 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.getByRole("button", { name: /Example record Display-only/ }).click();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
  await expect(page.locator(".ui-chevron").first()).toHaveCSS("transition-duration", "0s");
  const scroll = page.getByRole("button", { name: "Scroll Recorded amounts (USD) right" });
  await scroll.focus();
  await expect(scroll).toBeFocused();
  await page.keyboard.press("Enter");
});
