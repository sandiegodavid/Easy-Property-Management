import { expect, test } from "@playwright/test";

test("read-only operator can browse but cannot create records or change preferences", async ({
  page,
  context,
}) => {
  const control = async (path: string) => {
    const response = await context.request.post(`https://127.0.0.1:18749/__test__/${path}`);
    expect(response.ok(), await response.text()).toBe(true);
    return response;
  };
  const { assertion } = (await (await control("identity")).json()) as { assertion: string };
  await context.setExtraHTTPHeaders({ "Cf-Access-Jwt-Assertion": assertion });
  await page.goto("/sign-in?next=%2Ftasks");
  const admission = page.waitForResponse(
    (response) =>
      response.url().endsWith("/api/hosted/session") && response.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Continue to workspace" }).click();
  if ((await admission).status() === 403) {
    await expect(page.getByRole("alert")).toContainText("administrator approval");
    await control("approve");
    await page.getByRole("button", { name: "Continue to workspace" }).click();
  }
  await expect(page.getByRole("heading", { name: "Tasks", exact: true })).toBeVisible();
  await expect(
    page.getByText("Workspace writes are unavailable.", { exact: true }).first(),
  ).toBeVisible();
  await page.goto("/tasks?workflow=task.create");
  await expect(page.getByLabel("Title (required)")).toBeDisabled();
  await expect(page.getByRole("button", { name: "Create task", exact: true })).toBeDisabled();
  await expect(
    page.getByRole("button", { name: "Save unfinished form", exact: true }),
  ).toBeDisabled();
  await page.goto("/settings");
  await expect(page.getByRole("button", { name: "Save preferences", exact: true })).toBeDisabled();
  expect(
    await page.evaluate(async () => {
      const session = (await (await fetch("/api/hosted/session")).json()) as { csrfToken: string };
      return (
        await fetch("/api/tasks", {
          method: "POST",
          headers: { "X-EPM-CSRF": session.csrfToken, "Content-Type": "application/json" },
          body: "{}",
        })
      ).status;
    }),
  ).toBe(403);
});
