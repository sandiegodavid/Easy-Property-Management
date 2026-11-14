import { expect, test } from "@playwright/test";

test("Admin sign-in reports popup/start failure and keeps keyboard controls usable", async ({
  page,
}) => {
  await page.route("**/api/admin/session", (route) => route.fulfill({ status: 401, json: {} }));
  await page.route("**/auth/start", (route) => route.fulfill({ status: 503, json: {} }));
  await page.goto("/admin/index.html");
  await expect(page.getByRole("heading", { name: "Admin sign-in" })).toBeVisible();
  const google = page.getByRole("button", { name: "Continue with Google" });
  await google.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("status")).toContainText("Sign-in could not continue");
  await expect(google).toBeEnabled();
});

test("Admin shell restores session and signs out after reload", async ({ page }) => {
  await page.route("**/api/admin/session", (route) =>
    route.fulfill({
      json: { expiresAt: Date.now() + 3600000, csrfToken: "test-session-csrf" },
    }),
  );
  let sent = "";
  await page.route("**/auth/logout", (route) => {
    sent = route.request().headers()["x-csrf-token"] ?? "";
    return route.fulfill({ json: { message: "Signed out." } });
  });
  await page.goto("/admin/index.html");
  await page.reload();
  await expect(page.getByRole("heading", { name: "Admin", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page.getByRole("heading", { name: "Admin sign-in" })).toBeVisible();
  expect(sent).toBe("test-session-csrf");
});

async function fakeProvider(
  page: import("@playwright/test").Page,
  scenario: "enroll" | "challenge" | "blocked",
  expired = false,
  cleanupFails = false,
) {
  let submitted = "";
  await page.route("**/api/admin/session", (route) => route.fulfill({ status: 401, json: {} }));
  await page.route("**/auth/start", (route) =>
    route.fulfill({
      json: {
        attemptId: "browser-attempt",
        firebase: { apiKey: "synthetic", projectId: "qualification" },
        supportContact: "owner@example.invalid",
      },
    }),
  );
  await page.route("**/firebase_app.js*", (route) =>
    route.fulfill({
      contentType: "text/javascript",
      body: "export const initializeApp = (config) => config;",
    }),
  );
  await page.route("**/firebase_auth.js*", (route) =>
    route.fulfill({
      contentType: "text/javascript",
      body: `
      export const inMemoryPersistence = {}, browserPopupRedirectResolver = {};
      let enrolled = false;
      const primary = { getIdToken: async () => "primary" };
      const auth = { currentUser: primary };
      export const initializeAuth = () => auth;
      export class GoogleAuthProvider { setCustomParameters() {} }
      export async function signOut() {
        if (${JSON.stringify(cleanupFails)}) throw Error("cleanup unavailable");
        auth.currentUser = null;
      }
      export async function signInWithPopup() {
        if (${JSON.stringify(scenario)} === "blocked") throw { code: "auth/popup-blocked" };
        auth.currentUser = primary;
        if (${JSON.stringify(scenario)} === "enroll" && !enrolled) return { user: primary };
        throw { code: "auth/multi-factor-auth-required" };
      }
      export const TotpMultiFactorGenerator = {
        FACTOR_ID: "totp",
        generateSecret: async () => ({ secretKey: "SYNTHETICSETUPKEY" }),
        assertionForEnrollment: (secret, code) => ({ secret, code }),
        assertionForSignIn: (factor, code) => ({ factor, code }),
      };
      export const multiFactor = () => ({
        getSession: async () => ({}),
        enroll: async ({code}) => { if (code !== "000123") throw Error(); enrolled = true; },
      });
      export const getMultiFactorResolver = () => ({
        hints: [
          { factorId: "phone", uid: "phone", displayName: "Phone" },
          { factorId: "totp", uid: "first", displayName: "First authenticator" },
          { factorId: "totp", uid: "second", displayName: "Backup authenticator" },
        ],
        resolveSignIn: async ({factor, code}) => {
          if (code !== "000123") throw Error();
          return { user: { getIdToken: async () => "verified-" + factor } };
        },
      });
    `,
    }),
  );
  await page.route("**/auth/complete", async (route) => {
    const value = route.request().postDataJSON() as { token: string; phase?: string };
    if (value.phase === "enroll") return route.fulfill({ json: { message: "Continue." } });
    submitted = value.token;
    return route.fulfill({
      status: expired ? 401 : 200,
      json: expired ? {} : { expiresAt: Date.now() + 3600000, csrfToken: "csrf" },
    });
  });
  return () => submitted;
}

for (const colorScheme of ["light", "dark"] as const) {
  test(`Admin enrollment and selected TOTP are usable on narrow ${colorScheme} layouts`, async ({
    page,
  }) => {
    await page.setViewportSize({ width: 375, height: 812 });
    await page.emulateMedia({ colorScheme });
    const submitted = await fakeProvider(page, "enroll");
    await page.goto("/admin/index.html");
    await page.getByRole("button", { name: "Continue with Google" }).click();
    await expect(page.getByText("SYNTHETICSETUPKEY")).toBeVisible();
    await page.getByLabel("Authenticator code (required)").fill("000123");
    await page.getByRole("button", { name: "Add authenticator" }).click();
    await expect(page.getByRole("status")).toContainText("Authenticator added");
    await expect(page.getByText("SYNTHETICSETUPKEY")).toHaveCount(0);
    await page.getByRole("button", { name: "Continue with Google" }).click();
    await expect(page.getByRole("heading", { name: "Admin sign-in" })).toBeFocused();
    await page.getByLabel("Authenticator", { exact: true }).selectOption("second");
    await page.getByLabel("Authenticator code (required)").fill("111111");
    await page.getByRole("button", { name: "Verify and sign in" }).click();
    await expect(page.getByRole("status")).toContainText("could not be verified");
    await page.getByLabel("Authenticator code (required)").fill("000123");
    await page.getByRole("button", { name: "Verify and sign in" }).click();
    await expect(page.getByRole("heading", { name: "Admin", exact: true })).toBeVisible();
    expect(submitted()).toBe("verified-second");
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
    ).toBe(true);
    expect(await page.evaluate(() => localStorage.length)).toBe(0);
  });
}

test("Admin expired attempt keeps code visible until explicit restart", async ({ page }) => {
  await fakeProvider(page, "challenge", true);
  await page.goto("/admin/index.html");
  await page.getByRole("button", { name: "Continue with Google" }).click();
  await page.getByLabel("Authenticator code (required)").fill("000123");
  await page.getByRole("button", { name: "Verify and sign in" }).click();
  await expect(page.getByRole("status")).toContainText("could not be verified");
  await expect(page.getByLabel("Authenticator code (required)")).toHaveValue("000123");
  await page.getByRole("button", { name: "Start sign-in again" }).click();
  await expect(page.getByLabel("Authenticator code (required)")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Continue with Google" })).toBeEnabled();
});

test("Admin popup denial gives an actionable retry", async ({ page }) => {
  await fakeProvider(page, "blocked");
  await page.goto("/admin/index.html");
  await page.getByRole("button", { name: "Continue with Google" }).click();
  await expect(page.getByRole("status")).toContainText("Allow the Google popup");
  await expect(page.getByRole("button", { name: "Continue with Google" })).toBeEnabled();
});

test("Admin committed sign-in remains visible when SDK cleanup fails", async ({ page }) => {
  await fakeProvider(page, "challenge", false, true);
  await page.goto("/admin/index.html");
  await page.getByRole("button", { name: "Continue with Google" }).click();
  await page.getByLabel("Authenticator code (required)").fill("000123");
  await page.getByRole("button", { name: "Verify and sign in" }).click();
  await expect(page.getByRole("heading", { name: "Admin", exact: true })).toBeVisible();
  await expect(page.getByRole("status")).toContainText("Close this tab");
  await expect(page.getByRole("button", { name: "Sign out" })).toBeEnabled();
});
