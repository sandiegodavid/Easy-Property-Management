import { expect, test } from "@playwright/test";
import { formatDate, formatUsd } from "../src/shared/presentation";
import { cents } from "../src/workflows/money-presentation";
import { validateForm } from "../src/workflows/form-feedback";

test("display formatting groups USD without losing precision and keeps calendar dates stable", () => {
  expect(formatUsd("21000.00")).toBe("USD 21,000.00");
  expect(formatUsd(cents(195000))).toBe("USD 1,950.00");
  expect(formatUsd(cents(-50))).toBe("USD -0.50");
  expect(formatUsd("9007199254740993.01")).toBe("USD 9,007,199,254,740,993.01");
  expect(formatDate("2026-10-01")).toBe("Oct 1, 2026");
  expect(formatDate("2026-01-01")).toBe("Jan 1, 2026");
});

test("form validation collects missing fields together without API identifiers", () => {
  expect(() =>
    validateForm(
      {
        type: "object",
        properties: { propertyId: { type: "string" }, summary: { type: "string" } },
        required: ["propertyId", "summary"],
      },
      {},
    ),
  ).toThrow("Choose or enter property.\nChoose or enter summary.");
});

test("issue validation summarizes missing fields in operator language and brings feedback into view", async ({
  page,
}) => {
  let submissions = 0;
  page.on("request", (request) => {
    if (
      request.method() === "POST" &&
      new URL(request.url()).pathname === "/api/maintenance/issues"
    )
      submissions++;
  });
  await page.setViewportSize({ width: 390, height: 600 });
  await page.goto("/maintenance?workflow=maintenance.issue.create");
  const editor = page.getByRole("region", { name: "Report maintenance issue", exact: true });
  await expect(
    editor
      .getByRole("combobox", { name: "Priority", exact: true })
      .locator('option[value="normal"]'),
  ).toHaveText("Normal");
  await expect(
    editor
      .getByRole("combobox", { name: "Reporter role (required)", exact: true })
      .locator('option[value="manager"]'),
  ).toHaveText("Manager");
  await expect(
    editor
      .getByRole("combobox", { name: "Reported by (required)", exact: true })
      .locator('option[value="local_operator"]'),
  ).toHaveText("You");
  await editor.locator('button[type="submit"]').click();
  const alert = editor.getByRole("alert");
  await expect(alert).toContainText("property");
  await expect(alert).toContainText("summary");
  await expect(alert).not.toContainText("propertyId");
  await expect(alert).not.toContainText("Request:");
  await expect(alert).toBeFocused();
  await expect(alert).toBeInViewport();
  await editor.locator('button[type="submit"]').click();
  await expect(alert).toBeFocused();
  await expect(alert).toBeInViewport();
  expect(submissions).toBe(0);
  await expect(editor).not.toContainText("Draft dirty");
  await expect(editor).not.toContainText("attempt identity");
  await expect(
    editor.getByRole("button", { name: /^(Save unfinished form|Saving unfinished form…|Saved)$/ }),
  ).toHaveCount(1);
});

for (const scenario of [
  { url: "/maintenance?workflow=maintenance.issue.create", field: "Summary (required)" },
  { url: "/conversations?workflow=communication.create", field: "Subject (required)" },
  { url: "/money?workflow=finance.expense_category.create", field: "Display name (required)" },
  {
    url: "/providers?workflow=provider.category.archive&target=00000000-0000-4000-8000-000000000301",
    field: "Reason (required)",
  },
]) {
  test(`unfinished form save is acknowledged beside the actions for ${scenario.url}`, async ({
    page,
  }) => {
    await page.setViewportSize({ width: 390, height: 600 });
    await page.goto(scenario.url);
    await page.getByLabel(scenario.field, { exact: true }).fill("Visible saved feedback");
    const actions = page.getByRole("group", { name: "Form actions", exact: true });
    const status = actions.getByRole("status");
    await expect(status).toContainText("Unfinished form saved ·");
    await expect(status.locator("time")).toHaveAttribute("datetime", /\d{4}-\d\d-\d\dT/);
    await expect(actions.getByRole("button", { name: "Saved", exact: true })).toBeDisabled();
    await actions.scrollIntoViewIfNeeded();
    await expect(status).toBeInViewport();
    await expect(page.getByText("Form status and recovery details", { exact: true })).toHaveCount(
      0,
    );
  });
}

test("explicit unfinished save acknowledges saving and completion at the action row", async ({
  page,
}) => {
  let finishSave: (() => void) | undefined;
  await page.route("**/api/operator/recovery/*", async (route) => {
    if (route.request().method() === "PUT")
      await new Promise<void>((resolve) => {
        finishSave = resolve;
      });
    await route.continue();
  });
  await page.goto("/maintenance?workflow=maintenance.issue.create");
  await page.getByLabel("Summary (required)").fill("Acknowledged manual save");
  const actions = page.getByRole("group", { name: "Form actions", exact: true });
  await actions.getByRole("button", { name: "Save unfinished form", exact: true }).click();
  await expect(actions.getByRole("status")).toHaveText("Saving unfinished form…");
  await expect.poll(() => !!finishSave).toBe(true);
  finishSave!();
  await expect(actions.getByRole("status")).toContainText("Unfinished form saved ·");
  await expect(actions.getByRole("button", { name: "Saved", exact: true })).toBeDisabled();
});
