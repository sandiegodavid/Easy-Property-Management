import { expect, test } from "@playwright/test";

const session = {
  operatorId: "00000000-0000-4000-8000-000000000001",
  workspaceId: "00000000-0000-4000-8000-000000000002",
  identityBinding: "a".repeat(64),
  csrfToken: "verified-csrf",
  expiresAt: new Date(Date.now() + 3600_000).toISOString(),
  demoExpiresAt: new Date(Date.now() + 86400_000).toISOString(),
  administratorContact: "admin@example.com",
  capabilities: ["records.read", "records.write"],
};

test("explicit sign-in, CSRF, paused editing, same-identity resume and logout", async ({
  page,
}) => {
  let signedIn = false;
  let posts = 0;
  let deletions = 0;
  await page.route("**/api/hosted/session", async (route) => {
    const method = route.request().method();
    if (method === "POST") {
      posts++;
      signedIn = true;
      await route.fulfill({ json: { csrfToken: session.csrfToken, expiresAt: session.expiresAt } });
    } else if (method === "DELETE") {
      expect(route.request().headers()["x-epm-csrf"]).toBe(session.csrfToken);
      deletions++;
      signedIn = false;
      await route.fulfill({ status: 204 });
    } else {
      await route.fulfill(
        signedIn
          ? { json: session }
          : {
              status: 401,
              json: { detail: { code: "hosted_session_required" } },
            },
      );
    }
  });
  await page.route("**/api/operator/bootstrap", (route) =>
    route.fulfill({
      status: 401,
      json: { detail: { code: "hosted_session_expired" } },
    }),
  );
  await page.goto("/component-tests/hosted-session.html");
  await expect(page.getByRole("heading", { name: "Sign in to your demo workspace" })).toBeVisible();
  expect(posts).toBe(0);
  await page.getByRole("button", { name: "Continue to workspace" }).click();
  await page.getByLabel("Unsubmitted note").fill("Keep this input");
  await page.getByRole("button", { name: "Check protected record" }).click();
  await expect(page.getByLabel("Unsubmitted note")).toBeHidden();
  await expect(page.getByRole("heading", { name: "Sign in to your demo workspace" })).toBeFocused();
  expect(posts).toBe(1);
  await page.getByRole("button", { name: "Continue to workspace" }).click();
  await expect(page.getByLabel("Unsubmitted note")).toHaveValue("Keep this input");
  await page.getByRole("button", { name: "Sign out this device" }).click();
  await expect(page.getByLabel("Unsubmitted note")).toHaveCount(0);
  await expect(page.getByRole("alert")).toContainText("Signed out");
  expect(deletions).toBe(1);
});

test("pending enrollment is announced and remains usable at narrow width in both themes", async ({
  page,
}) => {
  await page.route("**/api/hosted/session", (route) =>
    route.fulfill({
      status: 403,
      json: { detail: { code: "hosted_enrollment_pending" } },
    }),
  );
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/component-tests/hosted-session.html");
  for (const theme of ["light", "dark"]) {
    await page.evaluate((value) => {
      document.documentElement.dataset.theme = value;
    }, theme);
    const button = page.getByRole("button", { name: "Continue to workspace" });
    await button.focus();
    await page.keyboard.press("Enter");
    await expect(page.getByRole("alert")).toContainText("administrator approval");
    await expect(page.getByRole("heading", { name: "Private workspace" })).toHaveCount(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
  }
});

test("a changed verified identity clears private input and all-device logout uses CSRF", async ({
  page,
}) => {
  let binding = session.identityBinding;
  let posts = 0;
  let allLogouts = 0;
  await page.route("**/api/hosted/session", async (route) => {
    if (route.request().method() === "POST") posts++;
    await route.fulfill({ json: { ...session, identityBinding: binding } });
  });
  await page.route("**/api/operator/bootstrap", (route) =>
    route.fulfill({
      status: 401,
      json: { detail: { code: "hosted_session_expired" } },
    }),
  );
  await page.route("**/api/hosted/session/all", async (route) => {
    expect(route.request().method()).toBe("DELETE");
    expect(route.request().headers()["x-epm-csrf"]).toBe(session.csrfToken);
    allLogouts++;
    await route.fulfill({ status: 204 });
  });
  await page.goto("/component-tests/hosted-session.html");
  await page.getByLabel("Unsubmitted note").fill("Private to previous identity");
  await page.getByRole("button", { name: "Check protected record" }).click();
  binding = "b".repeat(64);
  await page.getByRole("button", { name: "Continue to workspace" }).click();
  await expect(page.getByLabel("Unsubmitted note")).toHaveValue("");
  expect(posts).toBe(1);
  await page.getByRole("button", { name: "Sign out all devices" }).click();
  await expect(page.getByLabel("Unsubmitted note")).toHaveCount(0);
  expect(allLogouts).toBe(1);
});

test("absolute expiry pauses editing without an automatic sign-in attempt", async ({ page }) => {
  let deadline: string | undefined;
  let posts = 0;
  await page.route("**/api/hosted/session", (route) => {
    if (route.request().method() === "POST") posts++;
    deadline ??= new Date(Date.now() + 2500).toISOString();
    return route.fulfill({ json: { ...session, expiresAt: deadline } });
  });
  await page.goto("/component-tests/hosted-session.html");
  await page.getByLabel("Unsubmitted note").fill("Keep until explicit reauthentication");
  await expect(page.getByRole("alert")).toContainText("session expired");
  await expect(page.getByLabel("Unsubmitted note")).toBeHidden();
  expect(posts).toBe(0);
});

test("a session response arriving after logout cannot reopen private content", async ({ page }) => {
  let hold = false;
  let release: (() => void) | undefined;
  await page.route("**/api/hosted/session", async (route) => {
    if (route.request().method() === "DELETE") {
      await route.fulfill({ status: 204 });
      return;
    }
    if (hold)
      await new Promise<void>((resolve) => {
        release = resolve;
      });
    await route.fulfill({ json: session });
  });
  await page.goto("/component-tests/hosted-session.html");
  await page.getByLabel("Unsubmitted note").fill("Private input");
  hold = true;
  await page.evaluate(() => window.dispatchEvent(new Event("focus")));
  await expect.poll(() => Boolean(release)).toBe(true);
  await page.getByRole("button", { name: "Sign out this device" }).click();
  await expect(page.getByRole("alert")).toContainText("Signed out");
  const response = page.waitForResponse(
    (result) => result.url().endsWith("/api/hosted/session") && result.request().method() === "GET",
  );
  release?.();
  await response;
  await expect(page.getByRole("heading", { name: "Private workspace" })).toHaveCount(0);
});
