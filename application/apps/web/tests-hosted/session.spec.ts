import { expect, test, type BrowserContext, type Page } from "@playwright/test";
import { readFile } from "node:fs/promises";

const controls = "https://127.0.0.1:18748/__test__";

async function control(context: BrowserContext, path: string) {
  const response = await context.request.post(`${controls}/${path}`);
  expect(response.ok(), await response.text()).toBe(true);
  return response;
}

async function proof(context: BrowserContext, email = "operator@example.com") {
  const response = await control(context, `identity?email=${encodeURIComponent(email)}`);
  const { assertion } = (await response.json()) as { assertion: string };
  await context.setExtraHTTPHeaders({ "Cf-Access-Jwt-Assertion": assertion });
}

async function signIn(page: Page) {
  await proof(page.context());
  await page.goto("/tasks?workflow=task.create");
  const button = page.getByRole("button", { name: "Continue to workspace" });
  const admission = page.waitForResponse(
    (response) =>
      response.url().endsWith("/api/hosted/session") && response.request().method() === "POST",
  );
  await button.click();
  // Enrollment is intentionally not auto-approved by the product.
  if ((await admission).status() === 403) {
    await expect(page.getByRole("alert")).toContainText("administrator approval");
    await control(page.context(), "approve");
    await button.click();
  }
  await expect(page.getByLabel("Title (required)", { exact: true })).toBeVisible();
}

test("packaged deep link, real enrollment, secure cookie, CSRF, expiry and explicit resume", async ({
  page,
}) => {
  await signIn(page);
  await expect(page).toHaveURL(/\/tasks\?workflow=task.create$/);
  const cookie = (await page.context().cookies()).find(
    (value) => value.name === "__Host-epm_session",
  );
  expect(cookie).toMatchObject({ secure: true, httpOnly: true, sameSite: "Lax", path: "/" });
  const title = page.getByLabel("Title (required)", { exact: true });
  const text = `Hosted task ${crypto.randomUUID()}`;
  await title.fill(text);
  const csrfFailure = await page.evaluate(async () => {
    const response = await fetch("/api/tasks", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
    return { status: response.status, cache: response.headers.get("cache-control") };
  });
  expect(csrfFailure).toEqual({ status: 403, cache: "no-store" });
  await control(page.context(), "expire");
  await page.evaluate(() => window.dispatchEvent(new Event("focus")));
  await expect(page.getByRole("heading", { name: "Sign in to your demo workspace" })).toBeFocused();
  await expect(title).toBeHidden();
  let commands = 0;
  page.on("request", (request) => {
    if (request.method() === "POST" && new URL(request.url()).pathname === "/api/tasks") commands++;
  });
  await proof(page.context());
  await page.getByRole("button", { name: "Continue to workspace" }).click();
  await expect(title).toHaveValue(text);
  expect(commands).toBe(0);
  const created = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" && new URL(response.url()).pathname === "/api/tasks",
  );
  await page.getByRole("button", { name: "Create task", exact: true }).click();
  expect((await created).status()).toBe(201);
  expect(commands).toBe(1);
  // Cloudflare can refresh its assertion while the application session stays live.
  await proof(page.context());
  await page.getByRole("button", { name: "Sign out this device" }).click();
  await expect(title).toHaveCount(0);
  await expect(page.getByRole("alert")).toContainText("Signed out");
  expect(await page.evaluate(async () => (await fetch("/api/operator/recovery")).status)).toBe(401);
  expect(
    await page.evaluate(
      async () => (await fetch("/api/hosted/session", { method: "POST" })).status,
    ),
  ).toBe(403);
});

test("renewing Cloudflare sign-in returns to public sign-in and requires explicit continuation", async ({
  page,
}) => {
  // Model the provider redirect only; the callback, shell and session endpoint
  // remain real application requests. No live Cloudflare logout occurs here.
  await page.route("**/cdn-cgi/access/logout", (route) =>
    route.fulfill({
      status: 302,
      headers: { location: "https://demo.epm.test/?__cf_access_message=logged_out" },
    }),
  );
  await page.goto("/sign-in");
  let admissions = 0;
  page.on("request", (request) => {
    if (request.method() === "POST" && new URL(request.url()).pathname === "/api/hosted/session") {
      admissions++;
    }
  });
  const callback = page.waitForResponse(
    (response) => new URL(response.url()).search === "?__cf_access_message=logged_out",
  );
  await page.getByRole("link", { name: "Renew Cloudflare sign-in", exact: false }).click();
  expect((await callback).status()).toBe(303);
  await expect(page).toHaveURL("https://demo.epm.test/sign-in");
  await expect(page.getByRole("heading", { name: "Sign in to your demo workspace" })).toBeVisible();
  expect(admissions).toBe(0);
  await signIn(page);
  await expect(page.getByLabel("Title (required)", { exact: true })).toBeVisible();
});

test("wrong email and invalid proof fail closed in the real packaged application", async ({
  page,
}) => {
  await proof(page.context(), "uninvited@example.com");
  await page.goto("/sign-in?next=%2Ftasks");
  await page.getByRole("button", { name: "Continue to workspace" }).click();
  await expect(page.getByRole("alert")).toContainText("not accepted");
  await expect(page.getByLabel("Title (required)")).toHaveCount(0);
  await signIn(page);
  await page.getByLabel("Title (required)", { exact: true }).fill("Private unsubmitted input");
  await page.context().setExtraHTTPHeaders({ "Cf-Access-Jwt-Assertion": "invalid" });
  await page.evaluate(() => window.dispatchEvent(new Event("focus")));
  await expect(page.getByRole("heading", { name: "Sign in to your demo workspace" })).toBeVisible();
  await expect(page.getByLabel("Title (required)")).toBeHidden();
});

test("protected evidence download succeeds, then expiry pauses without navigation or replay", async ({
  page,
}) => {
  await signIn(page);
  const fileId = await page.evaluate(async () => {
    const session = (await (await fetch("/api/hosted/session")).json()) as { csrfToken: string };
    const data = new FormData();
    data.append(
      "metadata",
      JSON.stringify({
        sourceKind: "operator_note",
        channel: "internal",
        body: "Synthetic evidence",
        occurredAtUtc: new Date().toISOString(),
        originSystem: "manual",
        idempotencyKey: crypto.randomUUID(),
      }),
    );
    data.append(
      "files",
      new File(["Synthetic attachment bytes"], "synthetic.txt", { type: "text/plain" }),
    );
    const response = await fetch("/api/intake/sources/import", {
      method: "POST",
      headers: { "X-EPM-CSRF": session.csrfToken },
      body: data,
    });
    if (!response.ok) throw new Error(await response.text());
    const source = (await response.json()) as { sourceId: string };
    const detail = (await (await fetch(`/api/intake/sources/${source.sourceId}`)).json()) as {
      attachments: { file: { file_id: string } }[];
    };
    return detail.attachments[0].file.file_id;
  });
  await page.goto(`/money?file=${fileId}`);
  const link = page.getByRole("link", { name: "Download synthetic.txt", exact: true });
  const download = page.waitForEvent("download");
  await link.click();
  const completed = await download;
  expect(completed.suggestedFilename()).toBe("synthetic.txt");
  expect(await readFile(await completed.path(), "utf8")).toBe("Synthetic attachment bytes");
  await control(page.context(), "expire");
  let downloads = 0;
  page.on("download", () => downloads++);
  await link.click();
  await expect(page.getByRole("heading", { name: "Sign in to your demo workspace" })).toBeFocused();
  await expect(page).toHaveURL(new RegExp(`/money\\?file=${fileId}$`));
  expect(downloads).toBe(0);
  await proof(page.context());
  await page.getByRole("button", { name: "Continue to workspace" }).click();
  await expect(link).toBeVisible();
  expect(downloads).toBe(0);
});

test("all-device logout closes another session and unavailable workspace stays paused", async ({
  page,
  browser,
}) => {
  await signIn(page);
  const second = await browser.newContext({
    baseURL: "https://demo.epm.test",
    ignoreHTTPSErrors: true,
  });
  try {
    const other = await second.newPage();
    await signIn(other);
    await other.getByLabel("Title (required)", { exact: true }).fill("Second device input");
    await page.getByRole("button", { name: "Sign out all devices" }).click();
    await other.evaluate(() => window.dispatchEvent(new Event("focus")));
    await expect(
      other.getByRole("heading", { name: "Sign in to your demo workspace" }),
    ).toBeVisible();
    await proof(second);
    await other.getByRole("button", { name: "Continue to workspace" }).click();
    await expect(other.getByLabel("Title (required)", { exact: true })).toHaveValue(
      "Second device input",
    );
    await control(second, "availability?ready=false");
    const response = await other.evaluate(async () => {
      const response = await fetch("/api/operator/bootstrap");
      return { status: response.status, body: (await response.json()) as unknown };
    });
    expect(response.status).toBe(503);
    await other.getByRole("link", { name: "Money", exact: true }).first().click();
    await expect(
      other.getByRole("heading", { name: "Sign in to your demo workspace" }),
    ).toBeVisible();
  } finally {
    await control(second, "availability?ready=true");
    await second.close();
  }
});

test("host administration is absent and sign-in fits both themes at narrow width", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/sign-in");
  for (const colorScheme of ["light", "dark"] as const) {
    await page.emulateMedia({ colorScheme });
    const button = page.getByRole("button", { name: "Continue to workspace" });
    await button.focus();
    await expect(button).toBeFocused();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
  }
  await signIn(page);
  await page.goto("/settings");
  await expect(
    page
      .getByRole("navigation", { name: "Settings sections" })
      .getByRole("link", { name: "AI assistance" }),
  ).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Built-in AI assistance" })).toHaveCount(0);
  const status = await page.evaluate(
    async () => (await fetch("/api/workspace/backup-status")).status,
  );
  expect(status).toBe(403);
});

test("shared form requires explicit takeover and rejects stale saves without erasing input", async ({
  page,
  browser,
}) => {
  await signIn(page);
  const saved = page.waitForResponse(
    (response) =>
      response.request().method() === "PUT" && response.url().includes("/api/operator/recovery/"),
  );
  await page.getByLabel("Title (required)", { exact: true }).fill("First editor saved input");
  const record = (await (await saved).json()) as { id: string; revision: number };
  const second = await browser.newContext({
    baseURL: "https://demo.epm.test",
    ignoreHTTPSErrors: true,
  });
  try {
    const other = await second.newPage();
    await signIn(other);
    let claims = 0;
    other.on("request", (request) => {
      if (request.url().endsWith("/lease")) claims++;
    });
    await other.goto(`/tasks?workflow=task.create&resume=${record.id}`);
    const title = other.getByLabel("Title (required)", { exact: true });
    await expect(title).toHaveValue("First editor saved input");
    await expect.poll(() => claims).toBe(1);
    await expect(title).toBeDisabled();
    await expect(other.getByRole("region", { name: "Saved form edit authority" })).toContainText(
      "no longer owns",
    );
    other.once("dialog", (dialog) => dialog.accept());
    await other.getByRole("button", { name: "Take over editing", exact: true }).click();
    await expect(other.getByRole("region", { name: "Saved form edit authority" })).toContainText(
      "You can edit",
    );
    await title.fill("Second editor preserved input");
    const updated = other.waitForResponse(
      (response) =>
        response.request().method() === "PUT" &&
        response.url().includes(`/api/operator/recovery/${record.id}`),
    );
    await other.getByRole("button", { name: "Save unfinished form", exact: true }).click();
    expect((await updated).status()).toBe(200);
    const stale = page.waitForResponse(
      (response) =>
        response.request().method() === "PUT" &&
        response.url().includes(`/api/operator/recovery/${record.id}`),
    );
    await page.getByLabel("Title (required)", { exact: true }).fill("Keep stale editor input");
    expect((await stale).status()).toBe(409);
    await expect(page.getByLabel("Title (required)", { exact: true })).toHaveValue(
      "Keep stale editor input",
    );
    const current = await other.evaluate(
      async (id) =>
        (await (await fetch(`/api/operator/recovery/${id}`)).json()) as {
          payload: { title: string };
        },
      record.id,
    );
    expect(current.payload.title).toBe("Second editor preserved input");
    await page.getByRole("button", { name: "Review saved changes", exact: true }).click();
    await expect(page.getByLabel("Title (required)", { exact: true })).toHaveValue(
      "Keep stale editor input",
    );
    page.once("dialog", (dialog) => dialog.accept());
    await page.getByRole("button", { name: "Take over editing", exact: true }).click();
    await expect(page.getByRole("region", { name: "Saved form edit authority" })).toContainText(
      "You can edit",
    );
    const reviewed = page.waitForResponse(
      (response) =>
        response.request().method() === "PUT" &&
        response.url().includes(`/api/operator/recovery/${record.id}`),
    );
    await page.getByRole("button", { name: "Save unfinished form", exact: true }).click();
    expect((await reviewed).status()).toBe(200);
  } finally {
    await second.close();
  }
});

test("bounded visible change polling refreshes records from another session", async ({
  page,
  browser,
}) => {
  await signIn(page);
  await page.goto("/tasks");
  const second = await browser.newContext({
    baseURL: "https://demo.epm.test",
    ignoreHTTPSErrors: true,
  });
  try {
    const other = await second.newPage();
    await signIn(other);
    const title = `Cross-device task ${crypto.randomUUID()}`;
    await other.getByLabel("Title (required)", { exact: true }).fill(title);
    const saved = other.waitForResponse(
      (response) =>
        response.request().method() === "POST" && new URL(response.url()).pathname === "/api/tasks",
    );
    await other.getByRole("button", { name: "Create task", exact: true }).click();
    expect((await saved).status()).toBe(201);
    await expect(page.getByText(title, { exact: true }).first()).toBeVisible({ timeout: 20_000 });
  } finally {
    await second.close();
  }
});

test("hidden pages suspend change polling and runtime changes discard private editor context", async ({
  page,
}) => {
  await signIn(page);
  let polls = 0;
  page.on("request", (request) => {
    if (request.url().endsWith("/api/operator/changes")) polls++;
  });
  const initial = page.waitForResponse((response) =>
    response.url().endsWith("/api/operator/changes"),
  );
  await page.goto("/tasks?workflow=task.create");
  await initial;
  await page.clock.install();
  await page.evaluate(() => {
    Object.defineProperty(document, "visibilityState", { configurable: true, value: "hidden" });
    document.dispatchEvent(new Event("visibilitychange"));
  });
  const before = polls;
  await page.clock.fastForward(120_000);
  expect(polls).toBe(before);
  await page.evaluate(() => {
    Object.defineProperty(document, "visibilityState", { configurable: true, value: "visible" });
    document.dispatchEvent(new Event("visibilitychange"));
  });
  await expect.poll(() => polls).toBeGreaterThan(before);
  await page.getByLabel("Title (required)", { exact: true }).fill("Private to old runtime");
  await control(page.context(), "runtime");
  await page.evaluate(() => window.dispatchEvent(new Event("focus")));
  await expect(page.getByRole("heading", { name: "Sign in to your demo workspace" })).toBeVisible();
  await expect(page.getByLabel("Title (required)")).toHaveCount(0);
  await page.getByRole("button", { name: "Continue to workspace" }).click();
  await expect(page.getByLabel("Title (required)", { exact: true })).toHaveValue("");
});

test("four sessions keep two independent workspaces and reject copied cookies and foreign IDs", async ({
  page,
  browser,
}) => {
  await signIn(page);
  const a2 = await browser.newContext({
    baseURL: "https://demo.epm.test",
    ignoreHTTPSErrors: true,
  });
  const b1 = await browser.newContext({
    baseURL: "https://demo-b.epm.test",
    ignoreHTTPSErrors: true,
  });
  const b2 = await browser.newContext({
    baseURL: "https://demo-b.epm.test",
    ignoreHTTPSErrors: true,
  });
  try {
    await signIn(await a2.newPage());
    const bPages: Page[] = [];
    for (const context of [b1, b2]) {
      const response = await context.request.post("https://127.0.0.1:18749/__test__/identity");
      const { assertion } = (await response.json()) as { assertion: string };
      await context.setExtraHTTPHeaders({ "Cf-Access-Jwt-Assertion": assertion });
      const other = await context.newPage();
      await other.goto("/sign-in?next=%2Ftasks");
      const begin = other.waitForResponse(
        (response) =>
          response.url().endsWith("/api/hosted/session") && response.request().method() === "POST",
      );
      await other.getByRole("button", { name: "Continue to workspace" }).click();
      if ((await begin).status() === 403) {
        expect((await context.request.post("https://127.0.0.1:18749/__test__/approve")).ok()).toBe(
          true,
        );
        await other.getByRole("button", { name: "Continue to workspace" }).click();
      }
      await expect(other.getByRole("heading", { name: "Tasks", exact: true })).toBeVisible();
      bPages.push(other);
    }
    const created = await page.evaluate(async () => {
      const session = (await (await fetch("/api/hosted/session")).json()) as { csrfToken: string };
      const response = await fetch("/api/tasks", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-EPM-CSRF": session.csrfToken,
        },
        body: JSON.stringify({
          title: "Only in A",
          expectedRevision: 0,
          idempotencyKey: crypto.randomUUID(),
        }),
      });
      if (!response.ok) throw new Error(await response.text());
      return (await response.json()) as { id: string };
    });
    const identities = await Promise.all(
      [page, a2.pages()[0], ...bPages].map((page) =>
        page.evaluate(
          async () =>
            (await (await fetch("/api/operator/bootstrap")).json()) as { workspaceId: string },
        ),
      ),
    );
    expect(identities[0].workspaceId).toBe(identities[1].workspaceId);
    expect(identities[2].workspaceId).toBe(identities[3].workspaceId);
    expect(identities[0].workspaceId).not.toBe(identities[2].workspaceId);
    expect(
      await bPages[0].evaluate(async (id) => (await fetch(`/api/tasks/${id}`)).status, created.id),
    ).toBe(404);
    const cookie = (await page.context().cookies()).find(
      (value) => value.name === "__Host-epm_session",
    );
    if (!cookie) throw new Error("Expected A session cookie");
    await b2.addCookies([{ ...cookie, domain: "demo-b.epm.test" }]);
    expect(
      await bPages[1].evaluate(async () => (await fetch("/api/operator/bootstrap")).status),
    ).toBe(401);
  } finally {
    await Promise.all([a2.close(), b1.close(), b2.close()]);
  }
});

test("lost financial response reconciles its original expense without a second dispatch", async ({
  page,
}) => {
  await signIn(page);
  const fixture = await page.evaluate(async () => {
    const session = (await (await fetch("/api/hosted/session")).json()) as { csrfToken: string };
    const propertyResponse = await fetch("/api/properties", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-EPM-CSRF": session.csrfToken },
      body: JSON.stringify({
        displayName: `Hosted finance ${crypto.randomUUID()}`,
        addressLine1: "10 Maple Street",
        city: "Portland",
        region: "OR",
        postalCode: "97201",
        countryCode: "US",
        propertyType: "single_family_home",
        expectedPropertyRevision: 0,
        idempotencyKey: crypto.randomUUID(),
        ownerships: [{ ownerKind: "local_operator" }],
      }),
    });
    if (!propertyResponse.ok) throw new Error(await propertyResponse.text());
    const property = (await propertyResponse.json()) as { id: string; effectiveLocalDate: string };
    const categories = (await (await fetch("/api/expense-categories")).json()) as { id: string }[];
    return { property, categoryId: categories[0].id };
  });
  await page.goto(`/money?workflow=finance.expense.create&propertyId=${fixture.property.id}`);
  await page.getByLabel("Category id (required)").selectOption(fixture.categoryId);
  await page.getByLabel("Payee name", { exact: true }).fill("Synthetic plumber");
  await page.getByLabel("Paid on (required)").fill(fixture.property.effectiveLocalDate);
  await page.getByLabel("Amount (required)").fill("120.01");
  await page.getByLabel("Description (required)").fill("Synthetic paid repair");
  const requests: { idempotencyKey: string; amount: string }[] = [];
  let original: { id: string } | undefined;
  await page.route("**/api/expenses", async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    requests.push(route.request().postDataJSON() as { idempotencyKey: string; amount: string });
    const committed = await route.fetch({
      url: "https://127.0.0.1:18748/api/expenses",
      headers: { ...route.request().headers(), host: "demo.epm.test" },
      maxRedirects: 0,
    });
    expect(committed.status()).toBe(201);
    original = (await committed.json()) as { id: string };
    await route.abort("failed");
  });
  await page.getByRole("button", { name: "Record paid expense", exact: true }).click();
  await expect(page.getByRole("button", { name: "Check submission", exact: true })).toBeVisible();
  expect(requests).toHaveLength(1);
  await page.getByRole("button", { name: "Check submission", exact: true }).click();
  await expect(page.getByRole("region", { name: "Expense saved", exact: true })).toContainText(
    "120.01",
  );
  expect(requests).toHaveLength(1);
  await page.unroute("**/api/expenses");
  const result = await page.evaluate(
    async ({ propertyId, originalRequest }) => {
      const session = (await (await fetch("/api/hosted/session")).json()) as { csrfToken: string };
      const changed = await fetch("/api/expenses", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-EPM-CSRF": session.csrfToken },
        body: JSON.stringify({ ...originalRequest, amount: "120.02" }),
      });
      const expenses = (await (await fetch(`/api/expenses?propertyId=${propertyId}`)).json()) as {
        items: { id: string; amount: string }[];
      };
      return { conflict: changed.status, expenses: expenses.items };
    },
    { propertyId: fixture.property.id, originalRequest: requests[0] },
  );
  expect(result.conflict).toBe(409);
  expect(result.expenses).toHaveLength(1);
  expect(result.expenses[0].id).toBe(original?.id);
  expect(result.expenses[0].amount).toBe("120.01");
});

test("storage maintenance preserves input and full storage has an accessible explicit retry", async ({
  page,
}) => {
  await signIn(page);
  const title = page.getByLabel("Title (required)", { exact: true });
  try {
    await title.fill("Keep this input during maintenance");
    await control(page.context(), "storage?mode=maintenance");
    await page.getByRole("button", { name: "Create task", exact: true }).click();
    await expect(page.getByRole("alert").first()).toContainText("disk maintenance");
    await expect(title).toHaveValue("Keep this input during maintenance");
    await control(page.context(), "storage?mode=full");
    page.once("dialog", (dialog) => dialog.accept());
    await page.goto("/tasks");
    await expect(page.getByRole("alert")).toContainText("Workspace storage or maintenance");
    await expect(page.getByRole("button", { name: "Retry connection" })).toBeVisible();
    await control(page.context(), "storage?mode=ready");
    await page.getByRole("button", { name: "Retry connection" }).click();
    await expect(page.getByRole("heading", { name: "Tasks", exact: true })).toBeVisible();
  } finally {
    await control(page.context(), "storage?mode=ready");
  }
});

for (const operation of ["save", "prepare"] as const) {
  for (const expiry of ["session", "lease"] as const) {
    test(`lost ${operation} response recovers its original key after ${expiry} expiry`, async ({
      page,
    }) => {
      await signIn(page);
      const title = page.getByLabel("Title (required)", { exact: true });
      const saved = page.waitForResponse(
        (response) =>
          response.request().method() === "PUT" &&
          response.url().includes("/api/operator/recovery/"),
      );
      await title.fill(`Retain ${operation} ${expiry}`);
      const original = (await (await saved).json()) as { id: string };
      const requests: string[] = [];
      const pattern =
        operation === "save"
          ? `**/api/operator/recovery/${original.id}`
          : `**/api/operator/recovery/${original.id}/attempt`;
      let lose = true;
      await page.route(pattern, async (route) => {
        if (route.request().method() !== (operation === "save" ? "PUT" : "POST"))
          return route.continue();
        requests.push(route.request().postData() ?? "");
        if (!lose) return route.continue();
        lose = false;
        const committed = await route.fetch({
          url: `https://127.0.0.1:18748${new URL(route.request().url()).pathname}`,
          headers: { ...route.request().headers(), host: "demo.epm.test" },
          maxRedirects: 0,
        });
        expect(committed.ok()).toBe(true);
        await route.abort("failed");
      });
      if (operation === "save") {
        await title.fill(`Preserved ${operation} ${expiry}`);
        await expect(
          page.getByRole("button", { name: "Retry saving unfinished form", exact: true }),
        ).toBeVisible();
      } else {
        await page.getByRole("button", { name: "Create task", exact: true }).click();
        await expect(
          page.getByRole("button", { name: "Check submission", exact: true }),
        ).toBeVisible();
      }
      if (expiry === "session") {
        await control(page.context(), "expire");
        await page.evaluate(() => window.dispatchEvent(new Event("focus")));
        await expect(
          page.getByRole("heading", { name: "Sign in to your demo workspace" }),
        ).toBeVisible();
        await proof(page.context());
        await page.getByRole("button", { name: "Continue to workspace" }).click();
      } else {
        await control(page.context(), "expire-draft-leases");
        await page.clock.install();
        await page.clock.fastForward(301_000);
        await page
          .getByRole("button", {
            name: operation === "save" ? "Retry saving unfinished form" : "Check submission",
            exact: true,
          })
          .click();
      }
      await expect(title).toHaveValue(
        `${operation === "save" ? "Preserved" : "Retain"} ${operation} ${expiry}`,
      );
      if (expiry === "lease") await page.clock.setSystemTime(new Date());
      if (operation === "save")
        await page.getByRole("button", { name: "Review saved changes", exact: true }).click();
      page.once("dialog", (dialog) => dialog.accept());
      await page.getByRole("button", { name: "Take over editing", exact: true }).click();
      await expect(page.getByRole("region", { name: "Saved form edit authority" })).toContainText(
        "You can edit",
      );
      await page
        .getByRole("button", {
          name: operation === "save" ? "Retry saving unfinished form" : "Check submission",
          exact: true,
        })
        .click();
      // Lease loss is discovered by an explicit rejected retry before takeover.
      await expect.poll(() => requests.length).toBe(expiry === "lease" ? 3 : 2);
      expect(new Set(requests).size).toBe(1);
      const retained = (await page.evaluate(
        async (id) => (await (await fetch(`/api/operator/recovery/${id}`)).json()) as unknown,
        original.id,
      )) as { payload: { title: string }; status: string };
      expect(retained.payload.title).toBe(
        `${operation === "save" ? "Preserved" : "Retain"} ${operation} ${expiry}`,
      );
      expect(retained.status).toBe(operation === "save" ? "active" : "outcome_unknown");
    });
  }
}

for (const takeover of [false, true]) {
  test(`lost return response retains its operation after lease expiry and ${takeover ? "takeover" : "claim"}`, async ({
    page,
  }) => {
    await signIn(page);
    const title = page.getByLabel("Title (required)", { exact: true });
    await title.fill(`Retained return ${takeover}`);
    await page.route("**/api/tasks", (route) =>
      route.request().method() === "POST" ? route.abort("failed") : route.continue(),
    );
    await page.getByRole("button", { name: "Create task", exact: true }).click();
    await expect(
      page.getByRole("region", { name: "Submission needs checking", exact: true }),
    ).toBeVisible();
    const returns: string[] = [];
    let originalRevision = 0;
    await page.route("**/api/operator/recovery/*/return", async (route) => {
      returns.push(route.request().postData() ?? "");
      if (returns.length > 1) return route.continue();
      const committed = await route.fetch({
        url: `https://127.0.0.1:18748${new URL(route.request().url()).pathname}`,
        headers: { ...route.request().headers(), host: "demo.epm.test" },
        maxRedirects: 0,
      });
      expect(committed.ok()).toBe(true);
      originalRevision = ((await committed.json()) as { revision: number }).revision;
      await route.abort("failed");
    });
    page.once("dialog", (dialog) => dialog.accept());
    await page.getByRole("button", { name: "Fix and continue", exact: true }).click();
    await expect.poll(() => returns.length).toBe(1);
    await expect(page.getByRole("button", { name: "Fix and continue", exact: true })).toBeEnabled();
    await control(page.context(), "expire-draft-leases");
    await page.clock.install();
    await page.clock.fastForward(301_000);
    page.once("dialog", (dialog) => dialog.accept());
    await page.getByRole("button", { name: "Fix and continue", exact: true }).click();
    const authority = page.getByRole("region", { name: "Saved form edit authority", exact: true });
    await expect(
      authority.getByRole("button", { name: "Continue editing", exact: true }),
    ).toBeVisible();
    const beforeRetry = returns.length;
    await page.clock.setSystemTime(new Date());
    if (takeover) page.once("dialog", (dialog) => dialog.accept());
    await authority
      .getByRole("button", {
        name: takeover ? "Take over editing" : "Continue editing",
        exact: true,
      })
      .click();
    await expect(authority).toContainText("You can edit");
    page.once("dialog", (dialog) => dialog.accept());
    const retried = page.waitForResponse(
      (response) => response.request().method() === "POST" && response.url().endsWith("/return"),
    );
    await page.getByRole("button", { name: "Fix and continue", exact: true }).click();
    const result = await retried;
    expect(result.ok()).toBe(true);
    expect(((await result.json()) as { revision: number }).revision).toBe(originalRevision);
    expect(returns).toHaveLength(beforeRetry + 1);
    expect(new Set(returns).size).toBe(1);
    await expect(title).toBeEnabled();
    await expect(title).toHaveValue(`Retained return ${takeover}`);
  });
}
