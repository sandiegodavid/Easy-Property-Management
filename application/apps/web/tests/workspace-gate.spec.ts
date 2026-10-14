import { expect, test } from "@playwright/test";
import {
  BootstrapFailure,
  readRetry,
  WorkspaceScope,
  type Bootstrap,
} from "../src/app/workspace-scope";

const ready: Bootstrap = {
  contractVersion: 1,
  serverTimeUtc: "2026-10-14T12:00:00Z",
  state: "ready",
  workspaceId: "00000000-0000-4000-8000-000000000001",
  runtimeEpoch: "00000000-0000-4000-8000-000000000002",
  canWrite: true,
  reasonCode: null,
  capabilities: [],
  capabilityVersion: 1,
  preferencesState: "unavailable",
  preferences: null,
  recoveryActions: [],
};

for (const [reasonCode, message] of [
  ["workspace_missing", "Workspace not found"],
  ["workspace_busy", "Workspace is busy"],
  ["workspace_invalid", "Workspace could not be validated"],
  ["workspace_migration_required", "Workspace format is unsupported"],
] as const) {
  test(`${reasonCode} gates domain reads and provides setup guidance`, async ({ page }) => {
    const requests: string[] = [];
    await page.route("**/api/**", async (route) => {
      requests.push(route.request().url());
      expect(route.request().method()).toBe("GET");
      await route.fulfill({
        json: { ...ready, state: "unavailable", workspaceId: null, canWrite: false, reasonCode },
      });
    });
    await page.goto("/properties");
    await expect(page.getByRole("status")).toContainText(message);
    await expect(page.getByText("To locate a workspace", { exact: false })).toBeVisible();
    await expect(page.getByText("Property workflows", { exact: false })).toHaveCount(0);
    await expect(page.getByRole("button")).toHaveCount(0);
    expect(requests).toHaveLength(1);
    expect(requests[0]).toContain("/api/operator/bootstrap");
  });
}

test("nullable preferences and read-only capability remain explicit", async ({ page }) => {
  await page.route("**/api/operator/bootstrap", (route) =>
    route.fulfill({ json: { ...ready, canWrite: false } }),
  );
  await page.goto("/home");
  await expect(page.getByText("Using display defaults.", { exact: false })).toBeVisible();
  await expect(page.getByText("Workspace writes are unavailable.")).toBeVisible();
  await expect(page.getByRole("button")).toHaveCount(0);
});

test("network failure retries once and offers explicit connection retry", async ({ page }) => {
  let requests = 0;
  await page.route("**/api/operator/bootstrap", async (route) => {
    requests += 1;
    if (requests <= 2) await route.abort("failed");
    else await route.fulfill({ json: ready });
  });
  await page.goto("/home");
  await expect(page.getByRole("alert")).toContainText("Cannot connect");
  expect(requests).toBe(2);
  await page.getByRole("button", { name: "Retry connection" }).click();
  await expect(
    page.getByRole("status").filter({ hasText: "Local workspace connected." }),
  ).toBeVisible();
  expect(requests).toBe(3);
});

test("structured server failures do not auto retry or appear as an empty portfolio", async ({
  page,
}) => {
  let requests = 0;
  await page.route("**/api/operator/bootstrap", async (route) => {
    requests += 1;
    await route.fulfill({ status: 409, json: { detail: { code: "workspace_busy" } } });
  });
  await page.goto("/properties");
  await expect(page.getByRole("alert")).toContainText("unusable response");
  expect(requests).toBe(1);
  await expect(page.getByText("Property workflows", { exact: false })).toHaveCount(0);
});

test("supported recovery rechecks bootstrap before admitting a new runtime", async ({ page }) => {
  let requests = 0;
  await page.route("**/api/operator/bootstrap", async (route) => {
    requests += 1;
    await route.fulfill({
      json:
        requests === 1
          ? {
              ...ready,
              state: "busy",
              canWrite: false,
              reasonCode: "workspace_busy",
              recoveryActions: [
                { kind: "api_operation", action: "getOperatorBootstrap", label: "Retry" },
              ],
            }
          : ready,
    });
  });
  await page.goto("/home");
  await page.getByRole("button", { name: "Retry workspace check" }).click();
  await expect(
    page.getByRole("status").filter({ hasText: "Local workspace connected." }),
  ).toBeVisible();
  expect(requests).toBe(2);
});

test("disposing a workspace drops pages, cancels late reads and rejects stale writes", async () => {
  const previous = new WorkspaceScope("first", "epoch-one", true);
  const current = new WorkspaceScope("first", "epoch-two", false);
  previous.client.setQueryData(previous.key("properties"), { nextCursor: "old-page" });
  let finish: (value: string) => void = () => {};
  const pending = previous.client
    .fetchQuery({
      queryKey: previous.key("late"),
      queryFn: () =>
        new Promise<string>((resolve) => {
          finish = resolve;
        }),
    })
    .catch(() => "cancelled");
  previous.dispose();
  finish("old workspace data");
  await pending;
  expect(previous.client.getQueryCache().getAll()).toEqual([]);
  expect(current.client.getQueryCache().getAll()).toEqual([]);
  expect(current.key("properties")).toEqual(["first", "epoch-two", "properties"]);
  expect(() => previous.requireWrite()).toThrow();
  expect(() => current.requireWrite()).toThrow();
  expect(readRetry(0, new BootstrapFailure(true))).toBe(true);
  expect(readRetry(1, new BootstrapFailure(true))).toBe(false);
  expect(readRetry(0, new BootstrapFailure(false))).toBe(false);
  current.dispose();
});

test("readiness refresh withdraws domain content before a different workspace is admitted", async ({
  page,
}) => {
  let response: Bootstrap = ready;
  await page.route("**/api/operator/bootstrap", (route) => route.fulfill({ json: response }));
  await page.goto("/home");
  await expect(
    page.getByRole("status").filter({ hasText: "Local workspace connected." }),
  ).toBeVisible();
  response = { ...ready, state: "busy", canWrite: false, workspaceId: null };
  const refresh = async () => {
    await page.evaluate(() => {
      Object.defineProperty(document, "visibilityState", { configurable: true, value: "hidden" });
      document.dispatchEvent(new Event("visibilitychange", { bubbles: true }));
      Object.defineProperty(document, "visibilityState", { configurable: true, value: "visible" });
      document.dispatchEvent(new Event("visibilitychange", { bubbles: true }));
    });
  };
  await refresh();
  await expect(page.getByRole("status")).toContainText("Workspace is busy");
  await expect(page.getByText("Property workflows", { exact: false })).toHaveCount(0);
  response = {
    ...ready,
    workspaceId: "00000000-0000-4000-8000-000000000003",
    runtimeEpoch: "00000000-0000-4000-8000-000000000004",
  };
  await refresh();
  await expect(
    page.getByRole("status").filter({ hasText: "Local workspace connected." }),
  ).toBeVisible();
});
