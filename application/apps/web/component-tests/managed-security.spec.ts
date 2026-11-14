import { expect, test } from "@playwright/test";

const now = Date.now();
const original = {
  identity: "original",
  sessionId: "original-session",
  csrfToken: "csrf-first",
  expiresAt: now + 3600_000,
  renewAfter: now + 300_000,
  supportContact: "help@example.invalid",
  capabilities: ["records.read"],
};
const fixture = "/component-tests/managed-security.html";

test("popup renewal keeps the same editor and requires explicit continuation", async ({
  page,
  context,
}) => {
  let state: "active" | "expired" = "active";
  let session = original;
  await page.route("**/api/hosted/session", (route) =>
    route.fulfill(
      state === "active" ? { json: session } : { status: 401, json: { state: "renewal_required" } },
    ),
  );
  await context.route("**/auth/start?*", (route) =>
    route.fulfill({ contentType: "text/html", body: "<h1>Verify sign-in</h1>" }),
  );
  await page.goto(fixture);
  const input = page.getByLabel("Unsubmitted note");
  await input.fill("Leave this input mounted");
  state = "expired";
  await page.evaluate(() => window.dispatchEvent(new Event("focus")));
  await expect(page.getByRole("heading", { name: "Renew your sign-in" })).toBeVisible();
  await expect(input).toBeHidden();
  const popup = context.waitForEvent("page");
  await page.getByRole("button", { name: "Renew sign-in" }).click();
  const verification = await popup;
  await expect(verification.getByRole("heading", { name: "Verify sign-in" })).toBeVisible();
  expect(new URL(verification.url()).searchParams.get("renew")).toBe("1");
  expect(await verification.evaluate(() => window.opener === null)).toBe(true);
  session = { ...original, sessionId: "replacement", csrfToken: "csrf-second" };
  state = "active";
  await page.evaluate(() => window.dispatchEvent(new Event("focus")));
  await expect(page.getByRole("button", { name: "Continue to workspace" })).toBeVisible();
  await expect(input).toBeHidden();
  await page.getByRole("button", { name: "Continue to workspace" }).click();
  await expect(input).toHaveValue("Leave this input mounted");
  await expect(input).toBeFocused();

  session = { ...original, identity: "different", sessionId: "different-session" };
  await page.evaluate(() => window.dispatchEvent(new Event("focus")));
  await page.getByRole("button", { name: "Continue to workspace" }).click();
  await expect(input).toHaveValue("");
});

test("blocked popup offers a top-level fallback without navigating or clearing the editor", async ({
  page,
}) => {
  await page.addInitScript(() => {
    window.open = () => null;
  });
  await page.route("**/api/hosted/session", (route) => route.fulfill({ json: original }));
  await page.goto(fixture);
  await page.getByLabel("Unsubmitted note").fill("Keep the current input");
  await page.getByRole("button", { name: "Renew sign-in" }).click();
  await expect(page.getByRole("link", { name: "Continue sign-in in this tab" })).toHaveAttribute(
    "href",
    "/auth/start?returnTo=%2Fsign-in&renew=1",
  );
  await expect(page.getByLabel("Unsubmitted note")).toHaveValue("Keep the current input");
  await page.getByRole("button", { name: "Cancel sign-in" }).click();
  await expect(page.getByRole("link", { name: "Continue sign-in in this tab" })).toHaveCount(0);
});

test("device actions confirm with keyboard, keep other sessions, and check a lost sign-out once", async ({
  page,
  context,
}) => {
  let statusChecks = 0;
  let logoutPosts = 0;
  let originSession = original;
  let other = {
    sessionId: "other-device",
    label: "Firefox",
    lastSeenAt: now - 1000,
    current: false,
  };
  let signedOut = false;
  let saved: URLSearchParams | null = null;
  await context.route("**/api/hosted/session", (route) =>
    route.fulfill(
      signedOut ? { status: 401, json: { state: "signed_out" } } : { json: originSession },
    ),
  );
  await context.route("**/api/hosted/sessions", (route) =>
    route.fulfill({
      json: {
        items: [
          { sessionId: originSession.sessionId, label: "Chrome", lastSeenAt: now, current: true },
          ...(other.sessionId ? [other] : []),
        ],
      },
    }),
  );
  await context.route("**/api/hosted/session/logout", async (route) => {
    logoutPosts++;
    expect(route.request().headers()["x-epm-csrf"]).toBe(original.csrfToken);
    const body = new URLSearchParams(route.request().postData() ?? "");
    if (body.get("selection") === "other") {
      expect(body.get("device")).toBe("other-device");
      other = { ...other, sessionId: "" };
      await route.fulfill({ json: { state: "confirmed" } });
    } else {
      expect(body.get("selection")).toBe("all");
      saved = body;
      signedOut = true;
      await route.abort();
    }
  });
  await context.route("**/api/hosted/session/logout/check", (route) => {
    statusChecks++;
    expect(route.request().postData()).toBe(saved?.toString());
    return route.fulfill({ json: { state: "confirmed" } });
  });
  await page.setViewportSize({ width: 375, height: 760 });
  await page.goto(fixture);
  await page.evaluate(() => {
    document.documentElement.dataset.theme = "dark";
  });
  await page.getByRole("button", { name: "Security" }).click();
  await expect(page.getByText(/Chrome · This device/)).toBeVisible();
  const deviceAction = page.getByRole("button", { name: "Sign out device", exact: true });
  await deviceAction.click();
  await expect(page.getByRole("button", { name: "Cancel" })).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(deviceAction).toBeFocused();
  await deviceAction.click();
  await page.getByRole("button", { name: "Confirm sign-out" }).click();
  await expect(page.getByText("Device signed out.")).toBeVisible();
  await expect(page.getByText(/Firefox/)).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Private workspace" })).toBeVisible();

  const sibling = await context.newPage();
  await sibling.goto(fixture);
  await sibling.getByLabel("Unsubmitted note").fill("This tab is private");
  await page.getByRole("button", { name: "Sign out all devices" }).click();
  await page.getByRole("button", { name: "Confirm sign-out" }).click();
  await expect(page.getByLabel("Unsubmitted note")).toHaveCount(0);
  await expect(sibling.getByLabel("Unsubmitted note")).toHaveCount(0);
  await page.reload();
  await page.getByRole("button", { name: "Check sign-out status" }).click();
  await expect(page.getByText("Signed out.", { exact: true })).toBeVisible();
  expect(logoutPosts).toBe(2);
  expect(statusChecks).toBe(1);
  originSession = { ...original, sessionId: "next-session" };
  signedOut = false;
  await sibling.evaluate(() => window.dispatchEvent(new Event("focus")));
  await expect(sibling.getByLabel("Unsubmitted note")).toHaveValue("");
});

test("an independent device pauses after revocation and retains its input for the same identity", async ({
  browser,
  page,
  context,
}) => {
  const device = await browser.newContext();
  try {
    const second = await device.newPage();
    let revoked = false;
    let renewed = false;
    const remote = { ...original, sessionId: "second-browser" };
    await context.route("**/api/hosted/session", (route) => route.fulfill({ json: original }));
    await device.route("**/api/hosted/session", (route) =>
      route.fulfill(
        revoked && !renewed
          ? { status: 401, json: { state: "signed_out" } }
          : { json: { ...remote, sessionId: renewed ? "replacement-browser" : remote.sessionId } },
      ),
    );
    await page.route("**/api/hosted/sessions", (route) =>
      route.fulfill({
        json: {
          items: revoked
            ? []
            : [{ sessionId: remote.sessionId, label: "Firefox", lastSeenAt: now, current: false }],
        },
      }),
    );
    await page.route("**/api/hosted/session/logout", (route) => {
      expect(new URLSearchParams(route.request().postData() ?? "").get("device")).toBe(
        remote.sessionId,
      );
      revoked = true;
      return route.fulfill({ json: { state: "confirmed" } });
    });
    await page.goto(fixture);
    const base = new URL(page.url()).origin;
    await second.goto(base + fixture);
    const editor = second.getByLabel("Unsubmitted note");
    await editor.fill("Second device input");
    await page.getByRole("button", { name: "Security" }).click();
    await page.getByRole("button", { name: "Sign out device", exact: true }).click();
    await page.getByRole("button", { name: "Confirm sign-out" }).click();
    await expect(page.getByText("Device signed out.")).toBeVisible();
    await second.evaluate(() => window.dispatchEvent(new Event("focus")));
    await expect(second.getByRole("heading", { name: "Sign in to your workspace" })).toBeVisible();
    await expect(editor).toBeHidden();
    await expect(page.getByRole("heading", { name: "Private workspace" })).toBeVisible();
    renewed = true;
    await second.evaluate(() => window.dispatchEvent(new Event("focus")));
    await second.getByRole("button", { name: "Continue to workspace" }).click();
    await expect(editor).toHaveValue("Second device input");
  } finally {
    await device.close();
  }
});
