import { expect, test } from "@playwright/test";
import type { components } from "@epm/contracts/generated";

test("unfinished-form guard returns keyboard focus to the attempted navigation after Keep editing", async ({
  page,
}) => {
  await page.clock.install();
  await page.goto("/tasks?workflow=task.create");
  await page.getByLabel("Title (required)", { exact: true }).fill("Keep my input and focus");
  const back = page.locator(".parent-back-link");
  await back.click();
  const guard = page.getByRole("region", { name: "Unfinished form", exact: true });
  await expect(guard).toBeVisible();
  await guard.getByRole("button", { name: "Keep editing", exact: true }).click();
  await expect(guard).toHaveCount(0);
  await expect(back).toBeFocused();
  await expect(page.getByLabel("Title (required)", { exact: true })).toHaveValue(
    "Keep my input and focus",
  );
  await page.keyboard.press("Enter");
  await expect(guard).toBeVisible();
});

test("cancelling inline draft-discard confirmation restores focus and retains the draft", async ({
  page,
}) => {
  await page.goto("/tasks?workflow=task.create");
  const response = page.waitForResponse(
    (entry) =>
      entry.request().method() === "PUT" &&
      new URL(entry.url()).pathname.startsWith("/api/operator/recovery/"),
  );
  await page.getByLabel("Title (required)", { exact: true }).fill("Cancel this discard");
  const draft = (await (await response).json()) as components["schemas"]["RecoveryResponse"];
  await expect(page.getByRole("button", { name: "Saved", exact: true })).toBeDisabled();
  await page.goto("/settings/recovery");
  const row = page
    .locator(".recovery-form-card")
    .filter({ has: page.locator(`a[href*="resume=${draft.id}"]`) });
  const discard = row.getByRole("button", { name: "Discard", exact: true });
  let prompts = 0;
  page.on("dialog", async (dialog) => {
    prompts++;
    expect(dialog.message()).toContain("Discard this");
    await dialog.dismiss();
  });
  await discard.click();
  await expect(discard).toBeFocused();
  await expect(row).toBeVisible();
  expect(prompts).toBe(1);
  await row.getByRole("link", { name: "Continue editing: Create task", exact: true }).click();
  await expect(page.getByLabel("Title (required)", { exact: true })).toHaveValue(
    "Cancel this discard",
  );
});
