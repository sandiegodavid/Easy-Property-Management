# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: component-tests/central-identity.spec.ts >> verified Google handoff uses a native POST with a public attempt ID
- Location: component-tests/central-identity.spec.ts:6:3

# Error details

```
Error: page.goto: Protocol error (Page.navigate): Cannot navigate to invalid URL
Call log:
  - navigating to "/central/index.html?flow=00000000-0000-4000-8000-000000000099", waiting until "load"

```

# Test source

```ts
  1   | import { expect, test } from "@playwright/test";
  2   | 
  3   | const flow = "00000000-0000-4000-8000-000000000099";
  4   | 
  5   | for (const ready of [false, true]) {
  6   |   test(
  7   |     ready
  8   |       ? "verified Google handoff uses a native POST with a public attempt ID"
  9   |       : "central Google sign-in checks the original flow and shows setup readiness",
  10  |     async ({ page }) => {
  11  |       await page.route("**/firebase_app.js*", (route) =>
  12  |         route.fulfill({
  13  |           contentType: "text/javascript",
  14  |           body: "export const initializeApp = value => value;",
  15  |         }),
  16  |       );
  17  |       await page.route("**/firebase_auth.js*", (route) =>
  18  |         route.fulfill({
  19  |           contentType: "text/javascript",
  20  |           body: `
  21  |       export const inMemoryPersistence={}, browserPopupRedirectResolver={};
  22  |       export const initializeAuth=()=>({});
  23  |       export class GoogleAuthProvider {setCustomParameters(){}}
  24  |       export const signInWithPopup=async()=>({user:{getIdToken:async()=>"synthetic-proof"}});
  25  |       export const signOut=async()=>{};
  26  |       export const getMultiFactorResolver=()=>({});
  27  |       export const TotpMultiFactorGenerator={FACTOR_ID:"totp"};
  28  |     `,
  29  |         }),
  30  |       );
  31  |       await page.route("**/auth/start?*", (route) => {
  32  |         expect(new URL(route.request().url()).searchParams.get("flow")).toBe(flow);
  33  |         return route.fulfill({ json: { attemptId: flow, firebase: { apiKey: "synthetic" } } });
  34  |       });
  35  |       await page.route("**/auth/complete", (route) => {
  36  |         if (route.request().isNavigationRequest()) {
  37  |           expect(ready).toBe(true);
  38  |           expect(route.request().method()).toBe("POST");
  39  |           expect(route.request().postData()).toBe("attemptId=" + flow);
  40  |           return route.fulfill({
  41  |             contentType: "text/html",
  42  |             body: "<h1>Workspace continuation</h1>",
  43  |           });
  44  |         }
  45  |         const request = route.request().postDataJSON() as { attemptId: string; token: string };
  46  |         expect(request.attemptId).toBe(flow);
  47  |         expect(request.token).toBe("synthetic-proof");
  48  |         return route.fulfill({
  49  |           json: ready
  50  |             ? { state: "verified", handoffAttempt: flow }
  51  |             : { state: "workspace_not_ready" },
  52  |         });
  53  |       });
> 54  |       await page.goto("/central/index.html?flow=" + flow);
      |                  ^ Error: page.goto: Protocol error (Page.navigate): Cannot navigate to invalid URL
  55  |       await page.getByRole("button", { name: "Continue with Google" }).click();
  56  |       await expect(page.getByRole("status")).toContainText("Identity verified");
  57  |       if (ready) {
  58  |         await page.getByRole("button", { name: "Continue to your workspace" }).click();
  59  |         await expect(page.getByRole("heading", { name: "Workspace continuation" })).toBeVisible();
  60  |         expect(new URL(page.url()).search).toBe("");
  61  |       } else {
  62  |         await expect(page.getByRole("status")).toContainText("not ready");
  63  |       }
  64  |     },
  65  |   );
  66  | }
  67  | 
  68  | test("email send and original-device status expose no identity proof", async ({ page }) => {
  69  |   await page.route("**/auth/email-link", (route) => {
  70  |     const value = route.request().postDataJSON() as { email: string; flowId: string };
  71  |     expect(value).toEqual({ email: "operator@example.invalid", flowId: flow });
  72  |     return route.fulfill({ json: { state: "sent", attemptId: flow } });
  73  |   });
  74  |   await page.route("**/auth/start?attempt=*", (route) =>
  75  |     route.fulfill({ json: { state: "superseded" } }),
  76  |   );
  77  |   await page.goto("/central/index.html?flow=" + flow);
  78  |   await page.getByLabel("Email address (required)").fill("operator@example.invalid");
  79  |   await page.getByRole("button", { name: "Email me a sign-in link" }).click();
  80  |   await expect(page.getByRole("status")).toContainText("Check your email");
  81  |   await page.getByRole("button", { name: "Check sign-in status" }).click();
  82  |   await expect(page.getByRole("status")).toContainText("another device");
  83  | });
  84  | 
  85  | test("email continuation re-entry completes within the enclosing page", async ({ page }) => {
  86  |   await page.addInitScript(
  87  |     ({ attempt }) => {
  88  |       window.epmEmailCompletion = { attempt, code: "synthetic-code" };
  89  |       history.replaceState(null, "", location.pathname);
  90  |     },
  91  |     { attempt: flow },
  92  |   );
  93  |   await page.route("**/auth/email/continue", (route) => {
  94  |     const value = route.request().postDataJSON() as { email: string; code: string };
  95  |     expect(value.email).toBe("operator@example.invalid");
  96  |     expect(value.code).toBe("synthetic-code");
  97  |     return route.fulfill({
  98  |       json: {
  99  |         state: "workspace_not_ready",
  100 |         continueUrl: "https://operator.example.invalid/auth/start?continuation=" + flow,
  101 |       },
  102 |     });
  103 |   });
  104 |   await page.goto("/central/index.html?oobCode=synthetic-code");
  105 |   expect(page.url()).not.toContain("synthetic-code");
  106 |   await page.getByLabel("Email address (required)").fill("operator@example.invalid");
  107 |   await page.getByRole("button", { name: "Verify and continue" }).click();
  108 |   await expect(page.getByRole("link", { name: "Continue to your workspace" })).toHaveAttribute(
  109 |     "href",
  110 |     "https://operator.example.invalid/auth/start?continuation=" + flow,
  111 |   );
  112 |   expect(await page.evaluate(() => localStorage.length)).toBe(0);
  113 | });
  114 | 
  115 | test("missing source flow offers a safe sign-in instruction", async ({ page }) => {
  116 |   await page.goto("/central/index.html");
  117 |   await expect(page.getByText("Open Sign in from your workspace")).toBeVisible();
  118 |   await expect(page.getByRole("button", { name: "Continue with Google" })).toHaveCount(0);
  119 | });
  120 | 
```