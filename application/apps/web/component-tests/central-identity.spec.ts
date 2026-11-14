import { expect, test } from "@playwright/test";

const flow = "00000000-0000-4000-8000-000000000099";

for (const ready of [false, true]) {
  test(
    ready
      ? "verified Google handoff uses a native POST with a public attempt ID"
      : "central Google sign-in checks the original flow and shows setup readiness",
    async ({ page }) => {
      await page.route("**/firebase_app.js*", (route) =>
        route.fulfill({
          contentType: "text/javascript",
          body: "export const initializeApp = value => value;",
        }),
      );
      await page.route("**/firebase_auth.js*", (route) =>
        route.fulfill({
          contentType: "text/javascript",
          body: `
      export const inMemoryPersistence={}, browserPopupRedirectResolver={};
      export const initializeAuth=()=>({});
      export class GoogleAuthProvider {setCustomParameters(){}}
      export const signInWithPopup=async()=>({user:{getIdToken:async()=>"synthetic-proof"}});
      export const signOut=async()=>{};
      export const getMultiFactorResolver=()=>({});
      export const TotpMultiFactorGenerator={FACTOR_ID:"totp"};
    `,
        }),
      );
      await page.route("**/auth/start?*", (route) => {
        expect(new URL(route.request().url()).searchParams.get("flow")).toBe(flow);
        return route.fulfill({ json: { attemptId: flow, firebase: { apiKey: "synthetic" } } });
      });
      await page.route("**/auth/complete", (route) => {
        if (route.request().isNavigationRequest()) {
          expect(ready).toBe(true);
          expect(route.request().method()).toBe("POST");
          expect(route.request().postData()).toBe("attemptId=" + flow);
          return route.fulfill({
            contentType: "text/html",
            body: "<h1>Workspace continuation</h1>",
          });
        }
        const request = route.request().postDataJSON() as { attemptId: string; token: string };
        expect(request.attemptId).toBe(flow);
        expect(request.token).toBe("synthetic-proof");
        return route.fulfill({
          json: ready
            ? { state: "verified", handoffAttempt: flow }
            : { state: "workspace_not_ready" },
        });
      });
      await page.goto("/central/index.html?flow=" + flow);
      await page.getByRole("button", { name: "Continue with Google" }).click();
      await expect(page.getByRole("status")).toContainText("Identity verified");
      if (ready) {
        await page.getByRole("button", { name: "Continue to your workspace" }).click();
        await expect(page.getByRole("heading", { name: "Workspace continuation" })).toBeVisible();
        expect(new URL(page.url()).search).toBe("");
      } else {
        await expect(page.getByRole("status")).toContainText("not ready");
      }
    },
  );
}

test("email send and original-device status expose no identity proof", async ({ page }) => {
  await page.route("**/auth/email-link", (route) => {
    const value = route.request().postDataJSON() as { email: string; flowId: string };
    expect(value).toEqual({ email: "operator@example.invalid", flowId: flow });
    return route.fulfill({ json: { state: "sent", attemptId: flow } });
  });
  await page.route("**/auth/start?attempt=*", (route) =>
    route.fulfill({ json: { state: "superseded" } }),
  );
  await page.goto("/central/index.html?flow=" + flow);
  await page.getByLabel("Email address (required)").fill("operator@example.invalid");
  await page.getByRole("button", { name: "Email me a sign-in link" }).click();
  await expect(page.getByRole("status")).toContainText("Check your email");
  await page.getByRole("button", { name: "Check sign-in status" }).click();
  await expect(page.getByRole("status")).toContainText("another device");
});

test("email continuation re-entry completes within the enclosing page", async ({ page }) => {
  await page.addInitScript(
    ({ attempt }) => {
      window.epmEmailCompletion = { attempt, code: "synthetic-code" };
      history.replaceState(null, "", location.pathname);
    },
    { attempt: flow },
  );
  await page.route("**/auth/email/continue", (route) => {
    const value = route.request().postDataJSON() as { email: string; code: string };
    expect(value.email).toBe("operator@example.invalid");
    expect(value.code).toBe("synthetic-code");
    return route.fulfill({
      json: {
        state: "workspace_not_ready",
        continueUrl: "https://operator.example.invalid/auth/start?continuation=" + flow,
      },
    });
  });
  await page.goto("/central/index.html?oobCode=synthetic-code");
  expect(page.url()).not.toContain("synthetic-code");
  await page.getByLabel("Email address (required)").fill("operator@example.invalid");
  await page.getByRole("button", { name: "Verify and continue" }).click();
  await expect(page.getByRole("link", { name: "Continue to your workspace" })).toHaveAttribute(
    "href",
    "https://operator.example.invalid/auth/start?continuation=" + flow,
  );
  expect(await page.evaluate(() => localStorage.length)).toBe(0);
});

test("missing source flow offers a safe sign-in instruction", async ({ page }) => {
  await page.goto("/central/index.html");
  await expect(page.getByText("Open Sign in from your workspace")).toBeVisible();
  await expect(page.getByRole("button", { name: "Continue with Google" })).toHaveCount(0);
});
