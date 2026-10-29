import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

const origin = "http://epm-admin.localhost:18756";
async function fixture(request: APIRequestContext, action: string, data: object = {}) {
  const response = await request.post(`http://127.0.0.1:18756/__test/${action}`, {
    headers: { Host: "epm-admin.localhost:18756", Origin: origin },
    data,
  });
  expect(response.ok()).toBeTruthy();
  return (await response.json()) as Record<string, string>;
}
async function signIn(page: Page, request: APIRequestContext, path = "/") {
  await fixture(request, "restore");
  const { credential } = await fixture(request, "issue");
  await page.goto(path);
  await page.getByLabel("One-use sign-in credential").fill(credential);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.getByRole("navigation", { name: "Administration", exact: true })).toBeVisible();
  return credential;
}

test("overview and operator details show independent facts without granting new acceptance", async ({
  page,
  request,
}) => {
  const writes: string[] = [];
  page.on("request", (req) => {
    if (req.method() === "POST") writes.push(new URL(req.url()).pathname);
  });
  const credential = await signIn(page, request);
  await expect(page.getByRole("heading", { name: "Operators", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Add operator", exact: true })).toBeDisabled();
  await expect(page.getByRole("region", { name: "Operator directory", exact: true })).toContainText(
    "2 registered operators",
  );
  await expect(page.getByRole("region", { name: "Host capacity", exact: true })).toContainText(
    "1907 MiB",
    { timeout: 15000 },
  );
  await expect(page.getByText("Remaining Access seats: Unknown.", { exact: false })).toBeVisible();
  await expect(
    page.getByRole("region", { name: "Recovery availability", exact: true }),
  ).toContainText("Not verified");
  await page.screenshot({ path: test.info().outputPath("overview.png"), fullPage: true });
  await page.getByRole("link", { name: "Operator A", exact: true }).click();
  await expect(page).toHaveURL(`${origin}/operators/a`);
  await expect(page.getByRole("region", { name: "Access", exact: true })).toContainText(
    "Access enabled",
    { timeout: 15000 },
  );
  await expect(page.getByRole("region", { name: "Recovery", exact: true })).toContainText(
    "No verified reading",
  );
  await page.reload();
  await expect(page.getByRole("heading", { name: "Operator A", exact: true })).toBeVisible();
  await expect(
    page.getByRole("region", { name: "Runtime and capacity", exact: true }),
  ).toContainText("Matches", { timeout: 15000 });
  expect(await page.content()).not.toContain(credential);
  expect(await page.content()).not.toContain("/var/lib");
  expect(await page.evaluate(() => Object.keys(localStorage))).toEqual([]);
  expect(await page.evaluate(() => Object.keys(sessionStorage))).toEqual([]);
  expect(writes).toEqual(["/sign-in"]);
});

test("discrepancy and qualification pages keep unregistered C unqualified and never adopt it", async ({
  page,
  request,
}) => {
  await signIn(page, request, "/discrepancies");
  await expect(page).toHaveURL(`${origin}/discrepancies`);
  await expect(
    page.getByRole("region", { name: "Registered versus discovered keys", exact: true }),
  ).toContainText("c — inspect privately", { timeout: 15000 });
  await page.getByRole("link", { name: "Qualification plan", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Qualification plan", exact: true }),
  ).toBeVisible();
  await expect(page.getByText("No qualification plan registered.")).toBeVisible();
  await expect(page.getByText("Recorded ordinary ceiling:", { exact: false })).toContainText(
    "Unknown",
  );
  await page.getByRole("link", { name: "Operators", exact: true }).click();
  await expect(page.getByRole("region", { name: "Operator directory", exact: true })).toContainText(
    "2 registered operators",
  );
  await expect(page.getByRole("link", { name: "Operator C", exact: true })).toHaveCount(0);
});

test("lost observations retain their exact verified time and data as stale while navigation works", async ({
  page,
  request,
}) => {
  await signIn(page, request, "/operators/a");
  const access = page.getByRole("region", { name: "Access", exact: true });
  await expect(access).toContainText("Access enabled", { timeout: 15000 });
  const checked = await access.getByText(/^Last verified:/).textContent();
  await fixture(request, "observations", { failed: true });
  await expect(access.locator(".state")).toHaveText("Stale", { timeout: 15000 });
  await expect(access).toContainText("Access enabled");
  await expect(access.getByText(/^Last verified:/)).toHaveText(checked ?? "");
  expect(await page.content()).not.toContain("private provider failure");
  await page.getByRole("link", { name: "Operations", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Recent operations", exact: true })).toBeVisible();
});

test("an admitted operation survives reload and updates through read-only checkpoint polling", async ({
  page,
  request,
}) => {
  await signIn(page, request);
  const { id } = await fixture(request, "operation");
  await page.goto(`/operations/${id}`);
  const mutations: string[] = [];
  page.on("request", (req) => {
    if (req.method() === "POST") mutations.push(req.url());
  });
  await expect(page.getByRole("region", { name: "Operation", exact: true })).toContainText(
    "Queued",
  );
  await page.reload();
  await expect(page.getByText(id, { exact: true })).toBeVisible();
  await fixture(request, "finish", { id });
  await expect(page.getByRole("region", { name: "Operation", exact: true })).toContainText(
    "Succeeded",
    { timeout: 10000 },
  );
  await expect(page.getByRole("region", { name: "Checked steps", exact: true })).toContainText(
    "Verified",
  );
  await expect(page.getByRole("region", { name: "Operation history", exact: true })).toContainText(
    "Admitted",
  );
  expect(mutations).toEqual([]);
});

test("private navigation is keyboard usable on a narrow screen in both appearances", async ({
  page,
  request,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await signIn(page, request);
  const nav = page.getByRole("navigation", { name: "Administration", exact: true });
  const theme = nav.getByRole("button");
  await theme.focus();
  await page.keyboard.press("Enter");
  await expect(theme).toBeFocused();
  await page.screenshot({ path: test.info().outputPath("narrow.png"), fullPage: true });
  await expect(page.getByRole("heading", { name: "Operators", exact: true })).toBeVisible();
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
  ).toBeTruthy();
  await page.keyboard.press("Enter");
  const operations = nav.getByRole("link", { name: "Operations", exact: true });
  await operations.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("heading", { name: "Recent operations", exact: true })).toBeVisible();
  await expect(nav.getByRole("link", { name: "Operations", exact: true })).toHaveAttribute(
    "aria-current",
    "page",
  );
});

test("session expiry preserves the exact detail route and requires sign-in without command replay", async ({
  page,
  request,
}) => {
  await signIn(page, request, "/operators/b");
  const access = page.getByRole("region", { name: "Access", exact: true });
  await expect(access).toContainText("Enrollment needs review", { timeout: 15000 });
  await fixture(request, "advance", { seconds: 1801 });
  await expect(access.getByRole("alert")).toContainText("Your private session ended", {
    timeout: 10000,
  });
  await access.getByRole("link", { name: "Sign in again", exact: true }).click();
  const { credential } = await fixture(request, "issue");
  await page.getByLabel("One-use sign-in credential").fill(credential);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page).toHaveURL(`${origin}/operators/b`);
  await expect(page.getByRole("heading", { name: "Operator B", exact: true })).toBeVisible();
});

test("hidden pages stop observation polling and resume checking only on return", async ({
  page,
  request,
}) => {
  await signIn(page, request, "/operators/a");
  await expect(page.getByRole("region", { name: "Access", exact: true })).toContainText(
    "Access enabled",
    { timeout: 15000 },
  );
  await page.clock.install();
  let reads = 0;
  page.on("request", (req) => {
    if (req.url().includes("/observations/")) reads += 1;
  });
  await page.evaluate(() => {
    Object.defineProperty(document, "hidden", { value: true, configurable: true });
    document.dispatchEvent(new Event("visibilitychange"));
  });
  await page.clock.fastForward(90000);
  expect(reads).toBe(0);
  await page.evaluate(() => {
    Object.defineProperty(document, "hidden", { value: false, configurable: true });
    document.dispatchEvent(new Event("visibilitychange"));
  });
  await expect.poll(() => reads).toBeGreaterThan(0);
});

for (const stage of ["response", "body"] as const) {
  for (const refresh of [false, true]) {
    test(`a stalled ${refresh ? "refresh" : "initial read"} ${stage} times out and recovers`, async ({
      page,
      request,
    }) => {
      await page.addInitScript(
        ({ stage, refresh }) => {
          const original = window.fetch.bind(window);
          let count = 0;
          window.fetch = async (input, init) => {
            if (input !== "/admin-api/operators/a/observations/access")
              return original(input, init);
            count += 1;
            const data = {
              state: "available",
              observed: 1793293200,
              data: {
                active: true,
                binding_matches: true,
                pending_enrollments: 0,
                starts: 0,
                expires: 4102444800,
                capabilities: ["records.read"],
              },
            };
            const pending = () =>
              new Promise<never>((_, reject) => {
                const abort = () => reject(new DOMException("Aborted", "AbortError"));
                if (init?.signal?.aborted) abort();
                else init?.signal?.addEventListener("abort", abort, { once: true });
              });
            if (count === (refresh ? 2 : 1)) {
              if (stage === "response") return pending();
              const response = Response.json(data);
              response.json = pending;
              return response;
            }
            return Response.json(data);
          };
        },
        { stage, refresh },
      );
      await page.clock.install();
      await signIn(page, request, "/operators/a");
      const access = page.getByRole("region", { name: "Access", exact: true });
      if (refresh) {
        await expect(access.locator(".state")).toHaveText("Available");
        await page.clock.runFor(5000);
      } else {
        await expect(access).toContainText("Loading…");
      }
      const checked = await access.getByText(/^Last verified:/).textContent();
      await page.clock.runFor(10001);
      await expect(access).toContainText("Connection unavailable");
      await expect(access.locator(".state")).toHaveText(refresh ? "Stale" : "Unknown");
      await expect(access.getByText(/^Last verified:/)).toHaveText(checked ?? "");
      await expect(access).not.toContainText("Loading…");
      if (refresh) await expect(access).toContainText("Access enabled");
      await page.clock.runFor(10001);
      await expect(access.locator(".state")).toHaveText("Available");
      await expect(access).not.toContainText("Connection unavailable");
      await expect(access).toContainText("Access enabled");
    });
  }
}
