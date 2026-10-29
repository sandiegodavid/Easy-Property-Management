import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

const origin = "http://epm-admin.localhost:18756";
async function fixture(request: APIRequestContext, action: string, data: object = {}) {
  const result = await request.post(`http://127.0.0.1:18756/__test/${action}`, {
    headers: { Host: "epm-admin.localhost:18756", Origin: origin },
    data,
  });
  expect(result.ok()).toBeTruthy();
  return (await result.json()) as Record<string, string>;
}
async function begin(page: Page, request: APIRequestContext, allowed = false) {
  await fixture(request, "restore");
  await fixture(request, "setup", { allowed, provider_ready: false, pending: false });
  const { credential } = await fixture(request, "issue");
  await page.goto("/setups/new");
  await page.getByLabel("One-use sign-in credential").fill(credential);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Add operator — Operator" })).toBeVisible();
}
async function operatorStep(page: Page) {
  const name = `Synthetic ${test.info().testId}`;
  await page.getByLabel("Display name").fill(name);
  await page.getByLabel("Exact sign-in email").fill(`${crypto.randomUUID()}@example.test`);
  await page.getByLabel("Support email").fill("support@example.test");
  await page.getByRole("button", { name: "Save and continue", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Add operator — Demo" })).toBeFocused();
  return name;
}
async function confirm(page: Page) {
  await page.getByRole("button", { name: "Save and continue", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Add operator — Review" })).toBeFocused();
  await page.getByRole("checkbox", { name: "I reviewed the recipient" }).check();
  await page.getByRole("button", { name: "Create isolated demo", exact: true }).click();
}

test("setup survives reload and blocked admission preserves acknowledged fields without resource effects", async ({
  page,
  request,
}) => {
  await begin(page, request);
  const name = await operatorStep(page);
  const savedPath = page.url();
  await page.reload();
  await expect(page.getByLabel("Display name")).toHaveValue(name);
  await page.getByRole("button", { name: "Save and continue", exact: true }).click();
  await confirm(page);
  await expect(page.getByRole("alert")).toContainText("qualified operator ceiling");
  await expect(page.getByRole("alert")).toBeFocused();
  expect(page.url()).toBe(savedPath);
  await page.getByRole("button", { name: "Previous", exact: true }).click();
  await page.getByRole("button", { name: "Previous", exact: true }).click();
  await expect(page.getByLabel("Display name")).toHaveValue(name);
  await page.getByRole("button", { name: "Discard draft", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Saved operator setups", exact: true }),
  ).toBeVisible();
  await expect(page.getByRole("link", { name, exact: true })).toHaveCount(0);
});

test("isolated setup resumes manual verification and identity approval keeps business access fenced", async ({
  page,
  request,
}) => {
  test.setTimeout(45000);
  await begin(page, request, true);
  await operatorStep(page);
  await confirm(page);
  await expect(page.getByRole("heading", { name: "Administrator setup required" })).toBeVisible({
    timeout: 15000,
  });
  const id = new URL(page.url()).pathname.split("/").at(-1) ?? "";
  const status = await page.evaluate(
    async (draft) =>
      (await (await fetch(`/admin-api/setup-status/${draft}`)).json()) as {
        operation_id: string;
        instance: string;
      },
    id,
  );
  await page.reload();
  await expect(page.getByRole("heading", { name: "Administrator setup required" })).toBeVisible();
  await fixture(request, "setup", { provider_ready: true, pending: true });
  const grant = await fixture(request, "resume-grant", { id: status.operation_id });
  await page.getByLabel("One-use resume credential").fill(grant.credential);
  await page.getByRole("button", { name: "Resume reviewed setup" }).click();
  await expect(page.getByLabel("Invitation", { exact: true })).toBeVisible({ timeout: 15000 });
  await expect(page.getByLabel("Invitation", { exact: true })).toContainText("pending-approval");
  await expect(page.getByLabel("Invitation", { exact: true })).toContainText(
    "Use synthetic data only",
  );
  await page.getByLabel("Verified subject").selectOption("synthetic-verified-subject");
  const command = JSON.parse(await page.locator("pre").innerText()) as object;
  const action = await fixture(request, "action-grant", command);
  await page.getByLabel("One-use action credential").fill(action.credential);
  await page.getByRole("button", { name: "Authorize reviewed approval" }).click();
  await expect(
    page.getByRole("button", { name: "Approve identity — keep access blocked" }),
  ).toBeEnabled();
  await page.getByRole("button", { name: "Approve identity — keep access blocked" }).click();
  await expect(page.getByRole("heading", { name: "Identity approved", exact: true })).toBeVisible({
    timeout: 10000,
  });
  await expect(
    page.getByText("Recovery verification pending · Business access blocked.", { exact: false }),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: "Copy ready-to-use instructions" })).toHaveCount(0);
  const calls = await fixture(request, "setup");
  expect(calls.calls).not.toContain("epm-a");
  await expect(page.locator("body")).not.toContainText(grant.credential);
  expect(await page.evaluate(() => Object.keys(localStorage))).toEqual([]);
});

test("setup remains keyboard usable on a narrow screen in both appearances", async ({
  page,
  request,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await begin(page, request);
  for (const appearance of ["Dark appearance", "Light appearance"]) {
    const button = page.getByRole("button", { name: appearance, exact: true });
    if (await button.isVisible()) await button.click();
    await page.getByLabel("Display name").focus();
    await page.keyboard.type("Keyboard operator");
    await page.keyboard.press("Tab");
    await expect(page.getByLabel("Exact sign-in email")).toBeFocused();
    await expect
      .poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth))
      .toBe(true);
  }
});

test("a lost create response checks the original setup without a duplicate allocation", async ({
  page,
  request,
}) => {
  await begin(page, request, true);
  await operatorStep(page);
  let creates = 0;
  await page.route("**/setup-command", async (route) => {
    const body = route.request().postDataJSON() as { setup: { action: string } };
    if (body.setup.action !== "create") return route.continue();
    creates += 1;
    await route.fetch();
    await route.abort("failed");
  });
  await confirm(page);
  await expect(page.getByRole("alert")).toContainText("response could not be confirmed");
  await page.getByRole("link", { name: "Check saved setup", exact: true }).click();
  await expect(page.getByRole("heading", { name: /Setup progress/ })).toBeVisible();
  expect(creates).toBe(1);
  await expect(page.getByRole("button", { name: "Create isolated demo" })).toHaveCount(0);
  await page.getByRole("button", { name: "Stop setup — retain resources" }).click();
  await expect(page.getByRole("heading", { name: "Cancelled", exact: true })).toBeVisible({
    timeout: 10000,
  });
  await expect(page.getByRole("button", { name: "Copy invitation" })).toHaveCount(0);
});

test("failed background reads retain unsaved entries and stale revisions preserve the form", async ({
  page,
  request,
}) => {
  await page.clock.install();
  await begin(page, request);
  await operatorStep(page);
  await page.reload();
  await page.getByLabel("Display name").fill("Unsaved local change");
  await page.route("**/admin-api/setup-drafts/*", (route) => route.abort("failed"));
  await page.clock.runFor(31000);
  await expect(page.getByRole("alert")).toContainText("entries remain on this page");
  await expect(page.getByLabel("Display name")).toHaveValue("Unsaved local change");
  await page.unroute("**/admin-api/setup-drafts/*");
  const id = new URL(page.url()).pathname.split("/").at(-1) ?? "";
  await page.evaluate(async (identifier) => {
    const saved = (await (await fetch(`/admin-api/setup-drafts/${identifier}`)).json()) as {
      revision: number;
      data: object;
    };
    await fetch("/setup-command", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Epm-Admin-Csrf":
          document.querySelector<HTMLInputElement>('header input[name="csrf"]')?.value ?? "",
      },
      body: JSON.stringify({
        setup: {
          action: "save",
          draft_id: identifier,
          expected_revision: saved.revision,
          data: { ...saved.data, reference: "Changed in another tab" },
        },
      }),
    });
  }, id);
  await page.clock.resume();
  await page.getByRole("button", { name: "Save and continue", exact: true }).click();
  await expect(page.getByRole("alert").filter({ hasText: "changed elsewhere" })).toBeVisible();
  await expect(page.getByLabel("Display name")).toHaveValue("Unsaved local change");
});
