import { expect, test } from "@playwright/test";
import type { components } from "@epm/contracts/generated";
import axe from "axe-core";

declare global {
  interface Window {
    axe: typeof axe;
  }
}

type Schema = components["schemas"];

for (const width of [390, 900, 1440]) {
  for (const theme of ["light", "dark"]) {
    test(`${theme} at ${width}px: keyboard source action and form survive appearance changes`, async ({
      page,
      request,
    }) => {
      const created = await request.post("/api/tasks", {
        headers: { Origin: "http://127.0.0.1:18744" },
        data: {
          title: `Acceptance ${theme} ${width}`,
          priority: "high",
          expectedRevision: 0,
          idempotencyKey: crypto.randomUUID(),
        },
      });
      expect(created.ok(), await created.text()).toBe(true);
      const task = (await created.json()) as Schema["TaskCreationResponse"];
      await page.setViewportSize({ width, height: 900 });
      await page.emulateMedia({ reducedMotion: "reduce" });
      await page.goto("/settings");
      await page
        .getByRole("radio", { name: theme === "dark" ? "Dark" : "Light", exact: true })
        .check();
      await page.getByRole("button", { name: "Save preferences", exact: true }).click();
      await expect(page.getByText("Preferences saved.")).toBeVisible();
      await page.goto(`/tasks?record=task&id=${task.id}`);
      const edit = page.getByRole("button", { name: "Edit task", exact: true });
      await edit.focus();
      await page.keyboard.press("Enter");
      const title = page.getByLabel("Title", { exact: true });
      await title.fill("Preserved keyboard edit");
      await title.focus();
      expect(await title.evaluate((element) => getComputedStyle(element).outlineStyle)).not.toBe(
        "none",
      );
      await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
      await page.evaluate(axe.source);
      const violations = await page.evaluate(async () =>
        (
          await window.axe.run(document, {
            runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21aa"] },
          })
        ).violations.map((violation) => ({
          id: violation.id,
          nodes: violation.nodes.map((node) => node.target),
        })),
      );
      expect(violations).toEqual([]);
      // Equivalent to 200% content zoom; exercises reflow rather than a screenshot alone.
      await page.evaluate(() => {
        document.documentElement.style.fontSize = "200%";
      });
      await expect(title).toHaveValue("Preserved keyboard edit");
      expect(
        await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
      ).toBe(true);
      const save = page.getByRole("button", { name: "Save task changes", exact: true });
      await save.focus();
      await page.keyboard.press("Enter");
      await expect(
        page.locator('.saved-item, section[aria-label="Committed result"]'),
      ).toBeVisible();
      const current = await request.get(`/api/tasks/${task.id}`);
      expect(((await current.json()) as Schema["TaskResponse"]).title).toBe(
        "Preserved keyboard edit",
      );
    });
  }
}

test("an unrelated browser origin cannot submit multipart evidence or a command", async ({
  page,
  request,
}) => {
  let submitted = 0;
  const payloads: string[] = [];
  const listener = (response: import("@playwright/test").Response) => {
    if (response.url().endsWith("/api/files") || response.url().endsWith("/api/tasks")) {
      submitted++;
      expect(response.status()).toBe(403);
      payloads.push(response.url());
    }
  };
  page.on("response", listener);
  await page.route("http://unrelated.example/", (route) =>
    route.fulfill({
      contentType: "text/html",
      body: `<form method="post" enctype="multipart/form-data" action="http://127.0.0.1:18744/api/files"><input type="file" name="file"><button>Send evidence</button></form>`,
    }),
  );
  await page.goto("http://unrelated.example/");
  await page.locator("input").setInputFiles({
    name: "foreign.txt",
    mimeType: "text/plain",
    buffer: Buffer.from("foreign evidence"),
  });
  await page.getByRole("button", { name: "Send evidence" }).click();
  await expect(page.locator("body")).toContainText("transport_origin_rejected");
  const rejected = await request.post("/api/tasks", {
    headers: { Origin: "http://unrelated.example" },
    data: {
      title: "Rejected foreign task",
      expectedRevision: 0,
      idempotencyKey: crypto.randomUUID(),
    },
  });
  expect(rejected.status()).toBe(403);
  expect(submitted).toBe(1);
  expect(payloads).toHaveLength(1);
});
