import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import type { components } from "@epm/contracts/generated";

type Schema = components["schemas"];
test.use({ extraHTTPHeaders: { Origin: "http://127.0.0.1:18744" } });
const period = "fromOn=2026-10-01&throughOn=2026-10-31";

function p95(samples: number[]) {
  return [...samples].sort((left, right) => left - right)[Math.ceil(samples.length * 0.95) - 1];
}

async function task(request: APIRequestContext) {
  const response = await request.post("/api/tasks", {
    data: {
      title: `Home latency ${crypto.randomUUID()}`,
      dueAtUtc: new Date(Date.now() - 3 * 86_400_000).toISOString(),
      dueTimezone: "UTC",
      priority: "normal",
      expectedRevision: 0,
      idempotencyKey: crypto.randomUUID(),
    },
  });
  expect(response.ok(), await response.text()).toBe(true);
  return (await response.json()) as Schema["TaskCreationResponse"];
}

async function ready(page: Page) {
  await expect(
    page.getByRole("region", { name: "Recorded money", exact: true }).locator(".home-capture time"),
  ).toBeVisible();
  await expect(page.getByRole("region", { name: "Home action list", exact: true })).toContainText(
    "As of",
  );
}

async function latency(page: Page, name: string) {
  await page.waitForFunction((mark) => performance.getEntriesByName(mark).length > 0, name);
  return page.evaluate((mark) => performance.getEntriesByName(mark).at(-1)!.startTime, name);
}

test("Home live reads meet local p95 and shell-feedback gates without a snapshot cache", async ({
  page,
  request,
}) => {
  test.setTimeout(30_000);
  const sample = await task(request);
  const initial: number[] = [];
  const collection: number[] = [];
  const refresh: number[] = [];
  const shell: number[] = [];

  // Record rendered readiness in the browser, not the test runner: locator
  // assertion polling and protocol round trips are not application latency.
  // Navigation starts at zero, so the first (cold) document remains measured.
  await page.addInitScript(() => {
    let shellStarted: number | undefined;
    let refreshStarted: number | undefined;
    let previousCapture: string | null | undefined;
    const liveCapture = () =>
      document
        .querySelector('[aria-label="Home action list"] .home-capture time')
        ?.getAttribute("datetime");
    const mark = (name: string, startTime: number) => {
      if (performance.getEntriesByName(name).length === 0) performance.mark(name, { startTime });
    };
    const observer = new MutationObserver(() => {
      requestAnimationFrame(() => {
        const now = performance.now();
        const heading = document.querySelector("h2");
        if (shellStarted !== undefined && heading?.textContent === "Your day, in view")
          mark("home-shell", now - shellStarted);
        if (
          document
            .querySelector(".home-money-note")
            ?.closest("section")
            ?.querySelector(".home-capture time") &&
          liveCapture()
        )
          mark("home-ready", now);
        if (document.querySelector('[aria-label="Home collection page"] .home-capture time'))
          mark("collection-ready", now);
        const capture = liveCapture();
        if (refreshStarted !== undefined && capture && capture !== previousCapture)
          mark("home-refresh", now - refreshStarted);
      });
    });
    observer.observe(document, { subtree: true, childList: true, attributes: true });
    document.addEventListener(
      "click",
      (event) => {
        if (!(event.target instanceof Element)) return;
        if (event.target.closest('a[href="/home"]')) {
          performance.clearMarks("home-shell");
          shellStarted = performance.now();
        }
        if (event.target.closest("button")?.textContent?.trim() === "Refresh") {
          performance.clearMarks("home-refresh");
          previousCapture = liveCapture();
          refreshStarted = performance.now();
        }
      },
      true,
    );
  });

  for (let index = 0; index < 10; index += 1) {
    await page.goto(`/home?${period}`);
    await ready(page);
    initial.push(await latency(page, "home-ready"));

    const attention = page.getByRole("region", { name: "Needs action", exact: true });
    await attention.getByRole("button", { name: new RegExp(sample.title) }).click();
    await attention.getByRole("link", { name: "View", exact: true }).click();
    await expect(page).toHaveURL(/\/tasks\?record=task/);
    await page.getByRole("link", { name: "Home", exact: true }).click();
    await expect(
      page.getByRole("heading", { name: "Your day, in view", exact: true }),
    ).toBeVisible();
    shell.push(await latency(page, "home-shell"));
    await ready(page);

    await page.goto(`/home/collections/needs_action?horizonDays=7&${period}`);
    await expect(
      page.getByRole("region", { name: "Home collection page", exact: true }),
    ).toBeVisible();
    await expect(
      page.getByRole("region", { name: "Needs action", exact: true }).getByText(/^\d+ items?$/),
    ).toBeVisible();
    collection.push(await latency(page, "collection-ready"));

    await page.goto(`/home?${period}`);
    await ready(page);
    const refreshed = page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname === "/api/operator/home/attention" &&
        response.status() === 200,
    );
    await page.getByRole("button", { name: "Refresh", exact: true }).click();
    await refreshed;
    await expect(page.getByRole("region", { name: "Home action list", exact: true })).toContainText(
      "As of",
    );
    refresh.push(await latency(page, "home-refresh"));
  }

  const measurements = {
    initialP95Ms: Math.round(p95(initial)),
    collectionP95Ms: Math.round(p95(collection)),
    refreshP95Ms: Math.round(p95(refresh)),
    shellP95Ms: Math.round(p95(shell)),
  };
  console.log(`DASH-001 Slice 18 browser latency ${JSON.stringify(measurements)}`);
  expect(measurements.initialP95Ms).toBeLessThanOrEqual(1_000);
  expect(measurements.collectionP95Ms).toBeLessThanOrEqual(1_000);
  expect(measurements.refreshP95Ms).toBeLessThanOrEqual(1_000);
  expect(measurements.shellP95Ms).toBeLessThanOrEqual(100);
});
