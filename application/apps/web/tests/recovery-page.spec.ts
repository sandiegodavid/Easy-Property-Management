import { expect, test } from "@playwright/test";

test("packaged recovery route loads bounded metadata with reselection guidance", async ({
  page,
}) => {
  await page.goto("/home");
  await page.evaluate(async () => {
    for (let index = 0; index < 2; index++) {
      const result = await fetch(`/api/operator/recovery/${crypto.randomUUID()}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          formKey: "task.create",
          schemaVersion: 1,
          expectedRevision: 0,
          idempotencyKey: crypto.randomUUID(),
          payload: { title: `Private draft ${index}` },
        }),
      });
      if (!result.ok) throw new Error("Fixture save failed.");
    }
  });
  const reads: string[] = [];
  page.on("request", (request) => {
    if (request.url().includes("/api/operator/recovery")) reads.push(request.url());
  });
  await page.goto("/settings/recovery");
  await expect(page.getByRole("heading", { name: "Unfinished forms" })).toBeVisible();
  await expect(page.getByText(/Files and credentials must be selected again/)).toBeVisible();
  await expect(page.getByText(/Resume from the owning workflow/)).toHaveCount(2);
  await expect(page.getByText(/Private draft/)).toHaveCount(0);
  expect(reads).toHaveLength(1);
  expect(reads[0]).toContain("limit=50");
});
