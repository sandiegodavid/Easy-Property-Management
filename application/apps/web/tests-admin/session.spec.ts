import { expect, test, type APIRequestContext } from "@playwright/test";

const origin = "http://epm-admin.localhost:18756";
const fixture = "http://127.0.0.1:18756";
const headers = { Host: "epm-admin.localhost:18756", Origin: origin };

async function privateStep(request: APIRequestContext, action: string, data: object = {}) {
  const response = await request.post(`${fixture}/__test/${action}`, {
    headers,
    data,
  });
  expect(response.ok()).toBeTruthy();
  const value: unknown = await response.json();
  if (action !== "issue") return "";
  if (
    typeof value !== "object" ||
    value === null ||
    !("credential" in value) ||
    typeof value.credential !== "string"
  )
    throw new Error("Missing synthetic credential");
  return value.credential;
}

test.beforeEach(async ({ request }) => {
  await privateStep(request, "restore");
});

test("private sign-in supports keyboard, reload, logout and keeps credentials out of URLs and storage", async ({
  page,
  request,
}) => {
  const credential = await privateStep(request, "issue");
  await page.goto("/");
  const input = page.getByLabel("One-use sign-in credential");
  await expect(input).toBeFocused();
  await input.fill(credential);
  await page.keyboard.press("Tab");
  await expect(page.getByRole("button", { name: "Sign in", exact: true })).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.getByText("Signed in as Synthetic administrator.")).toBeVisible();
  await expect(page).toHaveURL(`${origin}/`);
  expect(await page.content()).not.toContain(credential);
  expect(await page.evaluate(() => Object.keys(localStorage))).toEqual([]);
  expect(await page.evaluate(() => Object.keys(sessionStorage))).toEqual([]);
  expect(await page.evaluate(() => document.cookie)).toBe("");
  await page.goto("/");
  await page.reload();
  await expect(page.getByText("Signed in as Synthetic administrator.")).toBeVisible();
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(input).toBeVisible();
  await input.fill(credential);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("Obtain a new credential");
  expect(await page.content()).not.toContain(credential);
});

test("expired grants and identity revocation cannot grant or retain authority", async ({
  page,
  request,
}) => {
  const expired = await privateStep(request, "issue");
  await privateStep(request, "advance", { seconds: 301 });
  await page.goto("/");
  await page.getByLabel("One-use sign-in credential").fill(expired);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.getByRole("alert")).toBeVisible();
  const fresh = await privateStep(request, "issue");
  await page.getByLabel("One-use sign-in credential").fill(fresh);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.getByText("Signed in as Synthetic administrator.")).toBeVisible();
  await privateStep(request, "revoke");
  await page.goto("/");
  await expect(page.getByLabel("One-use sign-in credential")).toBeVisible();
  await privateStep(request, "restore");
  await page.reload();
  await expect(page.getByLabel("One-use sign-in credential")).toBeVisible();
});

test("operator origins, arbitrary hosts and broker methods are rejected", async ({ request }) => {
  const crossSite = await request.post(`${fixture}/login`, {
    headers: { ...headers, Origin: "https://demo.example.com" },
    data: { credential: "not-authority" },
  });
  expect(crossSite.status()).toBe(403);
  const wrongHost = await request.get(`${fixture}/`);
  expect(wrongHost.status()).toBe(403);
  const privateRoute = await request.post(`${fixture}/bootstrap`, { headers, data: {} });
  expect(privateRoute.status()).toBe(400);
  expect(privateRoute.headers()["cache-control"]).toBe("no-store");
  expect(privateRoute.headers()["access-control-allow-origin"]).toBeUndefined();
});
