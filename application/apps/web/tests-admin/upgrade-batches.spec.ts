import { expect, test } from "@playwright/test";

const origin = "http://epm-admin.localhost:18756";
const batch = "00000000-0000-4000-8000-000000000077";
const target = "release-20261101-01";

test("bulk selection survives paging and a lost start keeps the original reviewed serial plan", async ({
  page,
  request,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await request.post("http://127.0.0.1:18756/__test/restore", {
    headers: { Host: "epm-admin.localhost:18756", Origin: origin },
  });
  const response = await request.post("http://127.0.0.1:18756/__test/issue", {
    headers: { Host: "epm-admin.localhost:18756", Origin: origin },
  });
  const { credential } = (await response.json()) as { credential: string };
  const observation = { state: "unknown", data: null };
  function operator(key: string) {
    return {
      key,
      name: `Operator ${key.toUpperCase()}`,
      email: `${key}@example.com`,
      hostname: `${key}.example.com`,
      release: "release-20261031-01",
      profile: "two",
      registered_revision: 1,
      access: observation,
      runtime: observation,
      recovery: observation,
    };
  }
  await page.route("**/admin-api/operators/page/*", (route) =>
    route.fulfill({
      json: {
        items: [operator(route.request().url().endsWith("/0") ? "a" : "b")],
        total: 51,
        offset: route.request().url().endsWith("/0") ? 0 : 50,
        next: route.request().url().endsWith("/0") ? 50 : null,
      },
    }),
  );
  await page.route("**/admin-api/operators/*/upgrade-options", (route) =>
    route.fulfill({
      json: {
        items: [
          {
            release: target,
            digest: "a".repeat(64),
            installed: 1,
            notes: "Qualified release",
            eligible: true,
            blockers: [],
            preserve_sessions: true,
            compatibility_digest: "b".repeat(64),
          },
        ],
      },
    }),
  );
  let running = false;
  let writes = 0;
  const members = ["a", "b"].map((instance, sequence) => ({
    sequence,
    instance,
    name: `Operator ${instance.toUpperCase()}`,
    expected_revision: 1,
    status: "queued",
    operation: null,
    rollback: null,
    operation_revision: null,
    observed: 100,
    original_release: "release-20261031-01",
    target_digest: "a".repeat(64),
    preserve_sessions: sequence === 0,
    session_handling: null,
    access_active: true,
    error: null,
  }));
  function view() {
    return {
      id: batch,
      state: running ? "running" : "ready",
      revision: running ? 3 : 2,
      release: target,
      error: null,
      total: 2,
      counts: { queued: 2 },
      window_start: running ? 100 : null,
      window_end: running ? 200 : null,
      items: members,
      offset: 0,
      next_offset: null,
    };
  }
  await page.route("**/admin-api/upgrade-batches/*/page/*/*", (route) =>
    route.fulfill({ json: view() }),
  );
  await page.route("**/admin-api/upgrade-batch-commands/*", (route) =>
    route.fulfill({ json: { found: true, batch: view() } }),
  );
  await page.route("**/upgrade-batch-command", async (route) => {
    const payload = route.request().postDataJSON() as {
      batch: {
        action: string;
        members: { instance: string }[];
        sessions: { instance: string; handling: string }[];
        window_start: number;
        window_end: number;
      };
      credential: string;
    };
    writes++;
    if (payload.batch.action === "check") {
      expect(payload.batch.members.map((item) => item.instance)).toEqual(["a", "b"]);
      await route.fulfill({ json: { id: batch, state: "checking", revision: 1 } });
    } else {
      expect(payload.batch.action).toBe("start");
      expect(payload.batch.sessions.map((item) => item.handling)).toEqual(["preserve", "revoke"]);
      expect(payload.batch.window_end).toBeGreaterThan(payload.batch.window_start);
      expect(payload.credential).toBe("private-batch-grant");
      running = true;
      await route.abort();
    }
  });
  await page.goto("/operators");
  await page.getByLabel("One-use sign-in credential").fill(credential);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  const first = page.getByLabel("Select Operator A", { exact: true });
  await first.focus();
  await first.press("Space");
  await expect(first).toBeChecked();
  await page.getByRole("button", { name: "Next 50", exact: true }).click();
  await page.getByLabel("Select Operator B", { exact: true }).check();
  await expect(page.getByText("2 selected · Maximum 50 operators per batch")).toBeVisible();
  await page.getByRole("link", { name: "Upgrade selected operators", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Operator A", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Operator B", exact: true })).toBeVisible();
  await page.getByLabel("Installed target release").selectOption(target);
  await page.getByRole("button", { name: "Check batch readiness", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Batch upgrade progress" })).toBeVisible();
  await expect(page.getByLabel("Operator B — Session handling")).toHaveValue("revoke");
  await page.getByLabel("Maintenance window starts (your local time)").fill("2026-11-01T10:00");
  await page.getByLabel("Maintenance window ends (your local time)").fill("2026-11-01T12:00");
  await page.getByLabel("Reason", { exact: true }).fill("Agreed maintenance window");
  await page
    .getByLabel("I reviewed the selected operators, maintenance window and access consequences.")
    .check();
  await page.getByRole("button", { name: "Review batch", exact: true }).click();
  await page.getByLabel("Action credential").fill("private-batch-grant");
  await page.getByRole("button", { name: "Start batch", exact: true }).click();
  await expect(page.getByRole("button", { name: "Check original submission" })).toBeVisible();
  expect(writes).toBe(2);
  await page.getByRole("button", { name: "Check original submission" }).click();
  await expect(
    page.getByRole("progressbar", { name: "Accepted operator upgrades" }),
  ).toHaveAttribute("value", "0");
  await page.reload();
  expect(writes).toBe(2);
});

for (const colorScheme of ["light", "dark"] as const) {
  test(`batch history, paging, stale reads and explicit queue decisions remain usable in ${colorScheme}`, async ({
    page,
    request,
  }) => {
    await page.emulateMedia({ colorScheme });
    await page.setViewportSize({ width: 390, height: 844 });
    await page.clock.install();
    await request.post("http://127.0.0.1:18756/__test/restore", {
      headers: { Host: "epm-admin.localhost:18756", Origin: origin },
    });
    const issued = await request.post("http://127.0.0.1:18756/__test/issue", {
      headers: { Host: "epm-admin.localhost:18756", Origin: origin },
    });
    const { credential } = (await issued.json()) as { credential: string };
    let unavailable = false;
    let state = "paused";
    let revision = 4;
    const actions: string[] = [];
    const members = Array.from({ length: 12 }, (_, sequence) => ({
      sequence,
      instance: `operator-${sequence}`,
      name: `Operator ${sequence + 1}`,
      expected_revision: 1,
      status:
        sequence === 0
          ? "accepted_restored"
          : sequence === 1
            ? "accepted_disabled"
            : sequence === 2
              ? "skipped"
              : sequence === 3
                ? "failed"
                : "queued",
      operation:
        sequence < 4 ? `00000000-0000-4000-8000-${String(sequence + 1).padStart(12, "0")}` : null,
      rollback: null,
      operation_revision: 2,
      observed: 100,
      original_release: "release-20261031-01",
      target_digest: "a".repeat(64),
      preserve_sessions: true,
      session_handling: "preserve",
      access_active: true,
      error: sequence === 3 ? "admin_upgrade_recovery_space_required" : null,
      can_skip: sequence >= 3,
    }));
    await page.route("**/admin-api/upgrade-batches/page/*", (route) =>
      route.fulfill({
        json: {
          items: [
            {
              id: batch,
              state,
              revision,
              created: 100,
              updated: 100,
              release: target,
              total: 12,
              accepted: 2,
              skipped: 1,
            },
          ],
          total: 1,
          offset: 0,
          next_offset: null,
        },
      }),
    );
    await page.route("**/admin-api/upgrade-batches/*/page/*/*", async (route) => {
      if (unavailable) {
        await route.abort();
        return;
      }
      const parts = new URL(route.request().url()).pathname.split("/");
      const offset = Number(parts.at(-2));
      const limit = Number(parts.at(-1));
      await route.fulfill({
        json: {
          id: batch,
          state,
          revision,
          release: target,
          error: state === "paused" ? "admin_batch_child_recovery_required" : null,
          total: 12,
          counts: {
            accepted_restored: 1,
            accepted_disabled: 1,
            skipped: members[3].status === "skipped" ? 2 : 1,
            failed: members[3].status === "failed" ? 1 : 0,
            queued: 8,
          },
          window_start: 100,
          window_end: 200,
          items: members.slice(offset, offset + limit),
          offset,
          next_offset: offset + limit < 12 ? offset + limit : null,
        },
      });
    });
    await page.route("**/upgrade-batch-command", async (route) => {
      const body = route.request().postDataJSON() as {
        batch: { action: string; sessions: { instance: string }[]; expected_revision: number };
        credential: string;
      };
      expect(body.batch.expected_revision).toBe(revision);
      actions.push(body.batch.action);
      revision++;
      if (body.batch.action === "skip") {
        expect(body.credential).toBe("private-skip");
        members[3].status = "skipped";
        members[3].can_skip = false;
      } else if (body.batch.action === "recheck") {
        state = "ready";
      } else if (body.batch.action === "resume") {
        expect(body.credential).toBe("private-resume");
        expect(body.batch.sessions).toHaveLength(12);
        state = "running";
      } else if (body.batch.action === "pause") {
        expect(body.credential).toBe("private-pause");
        state = "paused";
      } else if (body.batch.action === "cancel") {
        expect(body.credential).toBe("private-cancel");
        state = "cancelled";
      }
      await route.fulfill({ json: { id: batch, state, revision } });
    });
    await page.goto("/upgrade-batches");
    await page.getByLabel("One-use sign-in credential").fill(credential);
    await page.getByRole("button", { name: "Sign in", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Release upgrade batches" })).toBeVisible();
    await page.getByRole("link", { name: target, exact: true }).click();
    await expect(
      page.getByText("Access restored: 1 · Kept disabled: 1 · Skipped: 1 · Needs recovery: 1"),
    ).toBeVisible();
    await expect(
      page.getByText("Private recovery staging has insufficient space.", { exact: false }),
    ).toBeVisible();
    await page.getByRole("button", { name: "Next operators", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Operator 12", exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Next operators", exact: true })).toBeDisabled();
    await page.getByRole("button", { name: "Previous operators", exact: true }).click();
    await page.getByLabel("Reason", { exact: true }).fill("Keep this reviewed reason");
    unavailable = true;
    await page.clock.fastForward(3001);
    await expect(page.getByLabel("Reason", { exact: true })).toBeDisabled();
    await expect(page.getByLabel("Reason", { exact: true })).toHaveValue(
      "Keep this reviewed reason",
    );
    unavailable = false;
    await page.clock.fastForward(6001);
    await expect(page.getByLabel("Reason", { exact: true })).toBeEnabled();
    await page
      .getByLabel("I reviewed the selected operators, maintenance window and access consequences.")
      .check();
    await page.getByRole("button", { name: "Skip Operator 4", exact: true }).click();
    await page.getByLabel("Action credential").fill("private-skip");
    await page.getByRole("button", { name: "Skip this operator", exact: true }).click();
    await page.getByLabel("Reason", { exact: true }).fill("Review remaining operators");
    await page.getByRole("button", { name: "Check readiness again", exact: true }).click();
    await page.getByRole("button", { name: "Check readiness again", exact: true }).click();
    await page.getByLabel("Maintenance window starts (your local time)").fill("2026-11-01T10:00");
    await page.getByLabel("Maintenance window ends (your local time)").fill("2026-11-01T12:00");
    await page.getByLabel("Reason", { exact: true }).fill("New agreed window");
    await page
      .getByLabel("I reviewed the selected operators, maintenance window and access consequences.")
      .check();
    await page.getByRole("button", { name: "Review and resume batch", exact: true }).click();
    await page.getByLabel("Action credential").fill("private-resume");
    await page.getByRole("button", { name: "Resume batch", exact: true }).click();
    await page.getByLabel("Reason", { exact: true }).fill("Pause after current operator");
    await page
      .getByLabel("I reviewed the selected operators, maintenance window and access consequences.")
      .check();
    await page.getByRole("button", { name: "Pause after this operator", exact: true }).click();
    await page.getByLabel("Action credential").fill("private-pause");
    await page.getByRole("button", { name: "Pause after this operator", exact: true }).click();
    await page.getByLabel("Reason", { exact: true }).fill("Cancel all unstarted operators");
    await page
      .getByLabel("I reviewed the selected operators, maintenance window and access consequences.")
      .check();
    await page.getByRole("button", { name: "Cancel remaining operators", exact: true }).click();
    await page.getByLabel("Action credential").fill("private-cancel");
    await page.getByRole("button", { name: "Cancel remaining operators", exact: true }).click();
    await expect(page.getByText("Remaining upgrades canceled", { exact: false })).toBeVisible();
    expect(actions).toEqual(["skip", "recheck", "resume", "pause", "cancel"]);
  });
}
