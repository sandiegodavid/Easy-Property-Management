import { expect, test } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  await page.goto("/component-tests/recovery.html");
  await page.waitForFunction(() => Boolean(window.recoveryFixture));
});

test("form navigation waits for acknowledged autosave and explicit discard", async ({ page }) => {
  await page.goto("/component-tests/recovery-form.html");
  await page.getByLabel("Title", { exact: true }).fill("Preserve navigation input");
  await page.getByRole("link", { name: "Leave form" }).click();
  await expect(page.getByRole("region", { name: "Unfinished form" })).toBeVisible();
  await page.getByRole("button", { name: "Keep editing" }).click();
  await expect(page.getByLabel("Title", { exact: true })).toHaveValue("Preserve navigation input");
  await page.getByLabel("Title", { exact: true }).fill("Persist before navigation");
  await page.getByRole("link", { name: "Leave form" }).click();
  await page.getByRole("button", { name: "Save and leave" }).click();
  await expect(page.getByText("Navigation completed")).toBeVisible();
  await page.goto("/component-tests/recovery-form.html");
  await page.getByLabel("Title", { exact: true }).fill("Discard this edit");
  await page.getByRole("link", { name: "Leave form" }).click();
  await page.getByRole("button", { name: "Discard and leave" }).click();
  await expect(page.getByText("Navigation completed")).toBeVisible();
});

test("real autosave serializes edits and two-tab conflicts preserve local values", async ({
  page,
}) => {
  const result = await page.evaluate(async () => {
    const f = window.recoveryFixture;
    const item = await f.setup();
    await item.controller.flush();
    const first = item.controller.getSnapshot().record;
    if (!first) throw new Error("No saved form");
    const stale = new f.RecoveryController(
      item.scope,
      item.id,
      item.identity,
      first.payload,
      first,
    );
    item.controller.edit({ ...item.initial, changes: { title: "First edit" } }, 10000);
    const saving = item.controller.flush();
    item.controller.edit({ ...item.initial, changes: { title: "Latest edit" } }, 10000);
    await saving;
    stale.edit({ ...item.initial, changes: { title: "Other tab" } }, 10000);
    await stale.flush().catch(() => undefined);
    const conflict = stale.getSnapshot().draft;
    const latest = item.controller.getSnapshot().record;
    if (!latest) throw new Error("Missing latest");
    stale.reviewLatest(latest, "1");
    await stale.flush();
    return {
      conflict,
      first: first.revision,
      latest: latest.revision,
      payload: latest.payload,
      retained: stale.getSnapshot().record?.payload,
    };
  });
  expect(result.conflict).toBe("conflicted");
  expect(result.latest).toBe(result.first + 2);
  expect(result.payload.changes).toEqual({ title: "Latest edit" });
  expect(result.retained?.changes).toEqual({ title: "Other tab" });
});

test("lost commit response reconciles after reload and identical replay cannot duplicate", async ({
  page,
}) => {
  let patches = 0;
  await page.route("**/api/tasks/*", async (route) => {
    if (route.request().method() !== "PATCH") return route.continue();
    patches++;
    await route.fetch();
    await route.abort("failed");
  });
  const record = await page.evaluate(async () => {
    const f = window.recoveryFixture;
    const item = await f.setup();
    await item.controller.submit(f.dispatch).catch(() => undefined);
    return {
      state: item.controller.getSnapshot().command,
      record: item.controller.getSnapshot().record,
    };
  });
  expect(record.state).toBe("outcome_unknown");
  expect(patches).toBe(1);
  await page.unroute("**/api/tasks/*");
  await page.reload();
  await page.waitForFunction(() => Boolean(window.recoveryFixture));
  const result = await page.evaluate(async (id) => {
    const f = window.recoveryFixture;
    const loaded = await f.api.GET("/api/operator/recovery/{record_id}", {
      params: { path: { record_id: id } },
    });
    if (!loaded.data) throw new Error("Missing durable attempt");
    const original = await f.dispatch(loaded.data);
    const replay = await f.dispatch(loaded.data);
    const changed = {
      ...loaded.data,
      payload: { ...loaded.data.payload, changes: { title: "Different request" } },
    };
    const conflict = await f.dispatch(changed).then(
      () => "accepted",
      (error: Error) => error.message,
    );
    const receipt = await f.recoveryApi.reconcile(id, {
      expectedRevision: loaded.data.revision,
      idempotencyKey: crypto.randomUUID(),
    });
    return { original, replay, conflict, receipt };
  }, record.record?.id ?? "");
  expect(result.original).toEqual(result.replay);
  expect(result.conflict).not.toBe("accepted");
  expect(result.receipt.status).toBe("reconciled");
  expect(result.receipt.receipt?.attemptKey).toBe(record.record?.attemptKey);
});

test("cancelled dispatch remains unresolved and explicit original replay recovers", async ({
  page,
}) => {
  const result = await page.evaluate(async () => {
    const f = window.recoveryFixture;
    const item = await f.setup();
    await item.controller
      .submit(() => f.mutation(() => Promise.reject(new DOMException("Cancelled", "AbortError"))))
      .catch(() => undefined);
    const unknown = item.controller.getSnapshot();
    await item.controller.reconcile().catch(() => undefined);
    const attemptedNew = await item.controller.submit(f.dispatch).then(
      () => true,
      () => false,
    );
    await item.controller.replay(f.dispatch);
    return { unknown: unknown.command, attemptedNew, final: item.controller.getSnapshot() };
  });
  expect(result.unknown).toBe("outcome_unknown");
  expect(result.attemptedNew).toBe(false);
  expect(result.final.command).toBe("committed");
});

test("unknown autosave retries identical operation and rejects secret/file recovery", async ({
  page,
}) => {
  const keys: string[] = [];
  let lose = true;
  await page.route("**/api/operator/recovery/*", async (route) => {
    if (route.request().method() !== "PUT") return route.continue();
    const body = route.request().postDataJSON() as { idempotencyKey: string };
    keys.push(body.idempotencyKey);
    if (!lose) return route.continue();
    lose = false;
    await route.fetch();
    await route.abort("failed");
  });
  const result = await page.evaluate(async () => {
    const f = window.recoveryFixture;
    const item = await f.setup();
    await item.controller.flush().catch(() => undefined);
    const failed = item.controller.getSnapshot().draft;
    await item.controller.flush();
    let rejectedFile = false;
    try {
      item.controller.edit({ file: new File(["bytes"], "evidence.pdf") });
    } catch {
      rejectedFile = true;
    }
    const secret = await f.recoveryApi
      .save(crypto.randomUUID(), {
        ...item.identity,
        expectedRevision: 0,
        idempotencyKey: crypto.randomUUID(),
        payload: { password: "must not persist" },
      })
      .then(
        () => false,
        () => true,
      );
    await item.controller.discard();
    return { failed, rejectedFile, secret, status: item.controller.getSnapshot().record?.status };
  });
  expect(keys[0]).toBe(keys[1]);
  expect(result).toEqual({
    failed: "failed",
    rejectedFile: true,
    secret: true,
    status: "discarded",
  });
});

test("source changed since save blocks dispatch; errors distinguish validation and conflict", async ({
  page,
}) => {
  const result = await page.evaluate(async () => {
    const f = window.recoveryFixture;
    const item = await f.setup();
    await item.controller.flush();
    await f.mutation(() =>
      f.api.PATCH("/api/tasks/{task_id}", {
        params: { path: { task_id: item.task.id } },
        body: {
          title: "Concurrent official change",
          expectedRevision: item.task.revision,
          idempotencyKey: crypto.randomUUID(),
        },
      }),
    );
    let dispatches = 0;
    await item.controller
      .submit((record) => {
        dispatches++;
        return f.dispatch(record);
      })
      .catch(() => undefined);
    return {
      dispatches,
      state: item.controller.getSnapshot().command,
      validation: f.normalizeApiError(422, {
        detail: [{ loc: ["body", "title"], msg: "Required" }],
      }),
      conflict: f.normalizeApiError(409, {
        detail: { code: "idempotency_conflict", message: "Changed payload" },
      }),
      provider: f.normalizeApiError(503, {
        detail: { code: "file_provider_unavailable", message: "Provider unavailable" },
      }),
      stable:
        f.canonicalRequest({ b: 1, a: { z: 2 } }) === f.canonicalRequest({ a: { z: 2 }, b: 1 }),
    };
  });
  expect(result.dispatches).toBe(0);
  expect(result.state).toBe("rejected");
  expect(result.validation.fieldErrors.title).toEqual(["Required"]);
  expect(result.conflict.code).toBe("idempotency_conflict");
  expect(result.provider.code).toBe("file_provider_unavailable");
  expect(result.stable).toBe(true);
});

test("managed session rotation requires an explicit claim and ignores delayed authority", async ({
  page,
}) => {
  let claims = 0;
  let staged = () => {};
  const entered = new Promise<void>((resolve) => {
    staged = resolve;
  });
  let release = () => {};
  const pending = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route("**/api/hosted/drafts/*/lease", async (route) => {
    if (++claims === 1) {
      staged();
      await pending;
    }
    await route.fulfill({
      json: {
        expiresAt: new Date(Date.now() + 300_000).toISOString(),
        renewedAt: new Date().toISOString(),
      },
    });
  });
  const result = page.evaluate(async () => {
    const fixture = window.recoveryFixture;
    const { controller, scope, id, identity, initial } = await fixture.setup();
    await controller.flush();
    const saved = controller.getSnapshot().record!;
    const deployment = document.createElement("meta");
    deployment.name = "epm-deployment";
    deployment.content = "hosted_managed";
    document.head.append(deployment);
    fixture.admitHostedSession("first-session");
    const editor = new fixture.RecoveryController(scope, id, identity, initial, saved);
    editor.activate();
    await editor.claimEditing();
    const afterRotation = editor.getSnapshot().editAuthority;
    editor.edit({ ...initial, changes: { title: "Retained across rotation" } }, 10_000);
    await editor.flush().catch(() => undefined);
    const revisionWhilePaused = editor.getSnapshot().record?.revision;
    await editor.claimEditing();
    await editor.flush();
    const edited = editor.getSnapshot();
    editor.dispose();
    return { afterRotation, revisionWhilePaused, initialRevision: saved.revision, edited };
  });
  await entered;
  await page.evaluate(() => {
    window.recoveryFixture.pauseHostedSession();
    window.recoveryFixture.admitHostedSession("replacement-session");
  });
  release();
  const state = await result;
  expect(claims).toBe(2);
  expect(state.afterRotation).toBe("required");
  expect(state.revisionWhilePaused).toBe(state.initialRevision);
  expect(state.edited.editAuthority).toBe("held");
  expect(state.edited.record?.payload.changes).toEqual({ title: "Retained across rotation" });
});

test("reclaiming editing during a delayed save never resumes the earlier submit", async ({
  page,
}) => {
  let markStaged = () => {};
  const staged = new Promise<void>((resolve) => {
    markStaged = resolve;
  });
  let release = () => {};
  const pending = new Promise<void>((resolve) => {
    release = resolve;
  });
  let saves = 0;
  await page.route("**/api/operator/recovery/*", async (route) => {
    if (route.request().method() !== "PUT" || ++saves !== 2) return route.continue();
    const saved = await route.fetch();
    markStaged();
    await pending;
    await route.fulfill({ response: saved });
  });
  await page.route("**/api/hosted/drafts/*/lease", (route) =>
    route.fulfill({
      json: {
        expiresAt: new Date(Date.now() + 300_000).toISOString(),
        renewedAt: new Date().toISOString(),
      },
    }),
  );
  const result = page.evaluate(async () => {
    const fixture = window.recoveryFixture;
    const { controller, scope, id, identity, initial } = await fixture.setup();
    await controller.flush();
    const deployment = document.createElement("meta");
    deployment.name = "epm-deployment";
    deployment.content = "hosted_managed";
    document.head.append(deployment);
    fixture.admitHostedSession("first-session");
    const editor = new fixture.RecoveryController(
      scope,
      id,
      identity,
      initial,
      controller.getSnapshot().record,
    );
    editor.activate();
    await editor.claimEditing();
    editor.edit({ ...initial, changes: { title: "Review before resubmitting" } }, 10_000);
    let dispatches = 0;
    const submit = editor
      .submit(() => {
        dispatches++;
        return Promise.resolve();
      })
      .catch(() => undefined);
    await new Promise<void>((resolve, reject) => {
      window.addEventListener(
        "epm-test-reclaim",
        () => {
          fixture.pauseHostedSession();
          fixture.admitHostedSession("replacement-session");
          void editor.claimEditing().then(resolve, reject);
        },
        { once: true },
      );
    });
    document.body.dataset.reclaimed = "true";
    await submit;
    const state = editor.getSnapshot();
    editor.dispose();
    return { dispatches, state };
  });

  try {
    await staged;
    await page.evaluate(() => window.dispatchEvent(new Event("epm-test-reclaim")));
    await page.waitForFunction(() => document.body.dataset.reclaimed === "true");
  } finally {
    release();
  }

  const { dispatches, state } = await result;
  expect(dispatches).toBe(0);
  expect(state.record?.status).toBe("active");
  expect(state.record?.attemptKey).toBeNull();
  expect(state.record?.payload.changes).toEqual({ title: "Review before resubmitting" });
});
