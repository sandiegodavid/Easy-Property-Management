import { expect, test } from "@playwright/test";

test("packaged recovery route loads bounded metadata with reselection guidance", async ({
  page,
}) => {
  await page.goto("/home");
  const ids = await page.evaluate(async () => {
    const saved: string[] = [];
    for (let index = 0; index < 2; index++) {
      const id = crypto.randomUUID();
      const result = await fetch(`/api/operator/recovery/${id}`, {
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
      saved.push(id);
    }
    return saved;
  });
  const reads: string[] = [];
  page.on("request", (request) => {
    if (request.url().includes("/api/operator/recovery")) reads.push(request.url());
  });
  await page.goto("/settings/recovery");
  await expect(page.getByRole("heading", { name: "Unfinished forms" })).toBeVisible();
  await expect(page.getByText(/Files and credentials must be selected again/)).toBeVisible();
  for (const id of ids) {
    const resume = page.locator(`a[href*="resume=${id}"]`);
    await expect(resume).toHaveText("Resume task.create");
    await expect(resume).toHaveAttribute("href", `/tasks?workflow=task.create&resume=${id}`);
  }
  await expect(page.getByText(/Private draft/)).toHaveCount(0);
  expect(reads).toHaveLength(1);
  expect(reads[0]).toContain("limit=50");
});
