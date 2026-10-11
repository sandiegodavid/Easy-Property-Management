import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import type { components } from "@epm/contracts/generated";

type Schemas = components["schemas"];
test.use({ extraHTTPHeaders: { Origin: "http://127.0.0.1:18744" } });

async function fixture(request: APIRequestContext, futureOccupancy = false) {
  expect((await request.post("/__test__/lease-clock", { data: { days: 0 } })).ok()).toBe(true);
  const propertyResponse = await request.post("/api/properties", {
    data: {
      displayName: "Slice51 home",
      addressLine1: "10 Maple Street",
      city: "Portland",
      region: "OR",
      postalCode: "97201",
      countryCode: "US",
      propertyType: "single_family_home",
      ownerships: [{ ownerKind: "local_operator" }],
      expectedPropertyRevision: 0,
      idempotencyKey: crypto.randomUUID(),
    },
  });
  expect(propertyResponse.status(), await propertyResponse.text()).toBe(201);
  const property = (await propertyResponse.json()) as Schemas["PropertyMutationResponse"];
  const tenantResponse = await request.post("/api/tenants", {
    data: {
      partyKind: "individual",
      displayName: `Slice51 tenant ${crypto.randomUUID()}`,
      expectedRevision: 0,
      idempotencyKey: crypto.randomUUID(),
    },
  });
  expect(tenantResponse.status(), await tenantResponse.text()).toBe(201);
  const tenant = (await tenantResponse.json()) as Schemas["TenantMutationResponse"];
  const today = property.effectiveLocalDate;
  const startsOn = futureOccupancy
    ? new Date(Date.parse(`${today}T12:00:00Z`) + 86400000).toISOString().slice(0, 10)
    : today;
  const created = await request.post("/api/leases", {
    data: {
      expectedLeaseRevision: 0,
      idempotencyKey: crypto.randomUUID(),
      spaceId: property.spaces[0].id,
      leaseKind: "residential",
      contractStartsOn: startsOn,
      occupancyStartsOn: startsOn,
      initialTerm: {
        baseRentMinor: 100000,
        currencyCode: "USD",
        paymentFrequency: "monthly",
        paymentDueDay: 1,
        agreedSecurityDepositMinor: 100000,
      },
      participants: [{ tenantPartyId: tenant.id, participantRole: "primary_tenant" }],
    },
  });
  expect(created.status(), await created.text()).toBe(201);
  const lease = (await created.json()) as Schemas["LeaseMutationResponse"];
  return { property, tenant, lease, today };
}
async function save(page: Page, title: string) {
  await page.getByRole("button", { name: `Save ${title.toLowerCase()}`, exact: true }).click();
  await expect(page.getByRole("region", { name: "Committed result" })).toBeVisible();
}
async function execute(request: APIRequestContext, f: Awaited<ReturnType<typeof fixture>>) {
  const response = await request.post(`/api/leases/${f.lease.id}/execute`, {
    data: {
      expectedLeaseRevision: f.lease.leaseRevision,
      expectedRevision: f.property.spaces[0].revision,
      idempotencyKey: crypto.randomUUID(),
      confirmed: true,
      executedOn: f.today,
    },
  });
  expect(response.status(), await response.text()).toBe(200);
  return (await response.json()) as Schemas["TimelineLeaseResponse"];
}
async function report(
  request: APIRequestContext,
  f: Awaited<ReturnType<typeof fixture>>,
  walkthroughOn = f.today,
) {
  await execute(request, f);
  const response = await request.post(`/api/leases/${f.lease.id}/condition-reports`, {
    data: {
      expectedRevision: 0,
      idempotencyKey: crypto.randomUUID(),
      reportKind: "pre_move_in",
      walkthroughOn,
      conductedBy: "Operator",
      areas: [
        {
          displayName: "Kitchen",
          observations: [{ itemName: "Counter", conditionState: "good", isCompleted: true }],
        },
      ],
    },
  });
  expect(response.status(), await response.text()).toBe(201);
  return (await response.json()) as Schemas["ReportCommandResponse"];
}

test("draft edits resume and execution uses independent Lease and Space revisions", async ({
  page,
  request,
}) => {
  const f = await fixture(request);
  await page.goto(`/leasing?workflow=lease.patch&target=${f.lease.id}`);
  await page.getByLabel("Notes", { exact: true }).fill("Saved lease draft");
  await page.getByRole("button", { name: "Save unfinished form", exact: true }).click();
  await expect(page.getByText("Draft saved · Command editing", { exact: true })).toBeVisible();
  await page.goto("/settings/recovery");
  await page.getByRole("link", { name: "Resume lease.patch", exact: true }).last().click();
  await expect(page.getByRole("textbox", { name: "Notes", exact: true })).toHaveValue(
    "Saved lease draft",
  );
  await save(page, "Edit lease draft");
  await page.goto(`/leasing?workflow=lease.execute&target=${f.lease.id}`);
  await expect(page.getByText(/Space timeline revision:/)).toContainText(
    String(f.property.spaces[0].revision),
  );
  await page.getByLabel("Executed on (required)").fill(f.today);
  await page.getByLabel("I confirm this lifecycle change", { exact: true }).check();
  await save(page, "Execute lease");
  const latest = await request.get(`/api/leases/${f.lease.id}`);
  const item = (await latest.json()) as Schemas["LeaseResponse"];
  expect(item.status).toBe("executed");
  expect(item.leaseRevision).toBe(f.lease.leaseRevision + 2);
  await page.goto(`/leases/${f.lease.id}/inspections`);
  await expect(page.getByRole("region", { name: "Related rent setup" })).toContainText(
    "Rent schedule needs review",
  );
});

test("foreign lease children fail closed and incomplete drafts never dispatch", async ({
  page,
  request,
}) => {
  const f = await fixture(request),
    other = await fixture(request);
  await page.goto(
    `/leasing?workflow=lease.participant.update&target=${f.lease.id}&child=${other.lease.participants[0].id}`,
  );
  await expect(page.getByRole("alert")).toContainText("does not belong");
  await expect(page.getByRole("button", { name: /Save edit lease participant/ })).toHaveCount(0);
  let dispatched = 0;
  page.on("request", (request) => {
    if (request.method() === "POST" && request.url().endsWith("/api/leases")) dispatched++;
  });
  await page.goto("/leasing?workflow=lease.create");
  await page.getByRole("button", { name: "Save create lease draft", exact: true }).click();
  await expect(page.getByRole("alert")).toBeVisible();
  expect(dispatched).toBe(0);
});

test("a complete Lease draft is created through its saved command contract", async ({
  page,
  request,
}) => {
  const f = await fixture(request);
  await page.goto(`/leasing?workflow=lease.create&spaceId=${f.property.spaces[0].id}`);
  await page.getByLabel("Contract starts on (required)").fill(f.today);
  await page.getByLabel("Occupancy starts on (required)").fill(f.today);
  await page.getByLabel("Base rent minor (required)").fill("123456");
  await page.getByLabel("Payment due day", { exact: true }).fill("1");
  await page.getByLabel("Tenant party id (required)").fill(f.tenant.id);
  await page.getByLabel("Participant role (required)").selectOption("primary_tenant");
  await save(page, "Create lease draft");
  await page.getByRole("link", { name: "Open committed Lease and related setup" }).click();
  await expect(page.getByRole("region", { name: "Lease workspace" })).toContainText("123456");
});

test("renewal editing and decisions use different request shapes", async ({ page, request }) => {
  const f = await fixture(request);
  await execute(request, f);
  const future = new Date(`${f.today}T12:00:00Z`);
  future.setUTCDate(future.getUTCDate() + 30);
  const futureDate = future.toISOString().slice(0, 10);
  await page.goto(`/leasing?workflow=lease.renewal.add&target=${f.lease.id}`);
  await page.getByLabel("Proposed starts on (required)").fill(futureDate);
  await save(page, "Add renewal option");
  const response = await request.get(`/api/leases/${f.lease.id}`);
  const lease = (await response.json()) as Schemas["LeaseResponse"];
  const option = lease.renewalOptions[0];
  await page.goto(`/leasing?workflow=lease.renewal.update&target=${f.lease.id}&child=${option.id}`);
  await expect(page.getByLabel("Status", { exact: true })).toHaveCount(0);
  await page.getByLabel("Notes", { exact: true }).fill("Review renewal offer");
  await save(page, "Edit renewal option");
  await page.goto(`/leasing?workflow=lease.renewal.decide&target=${f.lease.id}&child=${option.id}`);
  await page.getByLabel("Status (required)").selectOption("declined");
  await page.getByLabel("Decided on (required)").fill(f.today);
  await save(page, "Decide renewal option");
  const current = await request.get(`/api/leases/${f.lease.id}`);
  expect(((await current.json()) as Schemas["LeaseResponse"]).renewalOptions[0].status).toBe(
    "declined",
  );
});

test("draft participants and rent terms retain child membership and explicit removal", async ({
  page,
  request,
}) => {
  const f = await fixture(request),
    other = await fixture(request);
  await page.goto(`/leasing?workflow=lease.participant.add&target=${f.lease.id}`);
  await page.getByLabel("Tenant party id (required)").fill(other.tenant.id);
  await page.getByLabel("Participant role (required)").selectOption("co_tenant");
  await save(page, "Add lease participant");
  const response = await request.get(`/api/leases/${f.lease.id}`);
  const child = ((await response.json()) as Schemas["LeaseResponse"]).participants.find(
    (p) => p.tenantPartyId === other.tenant.id,
  )!;
  await page.goto(
    `/leasing?workflow=lease.participant.update&target=${f.lease.id}&child=${child.id}`,
  );
  await page.getByLabel("Notes", { exact: true }).fill("Reviewed participant dates");
  await save(page, "Edit lease participant");
  await page.goto(
    `/leasing?workflow=lease.participant.remove&target=${f.lease.id}&child=${child.id}`,
  );
  await page.getByLabel("I confirm removal of this Lease participant").check();
  await save(page, "Remove lease participant");
  await page.goto(`/leasing?workflow=lease.term.replace&target=${f.lease.id}`);
  await page.getByLabel("Base rent minor (required)").fill("234567");
  await save(page, "Replace draft rent terms");
  const updated = await request.get(`/api/leases/${f.lease.id}`);
  const lease = (await updated.json()) as Schemas["LeaseResponse"];
  expect(lease.participants).toHaveLength(1);
  expect(lease.terms[0].baseRentMinor).toBe(234567);
  expect(lease.leaseRevision).toBe(5);
});

test("removed participants resume original-result recovery without another removal", async ({
  page,
  request,
}) => {
  const f = await fixture(request),
    other = await fixture(request);
  const added = await request.post(`/api/leases/${f.lease.id}/participants`, {
    data: {
      tenantPartyId: other.tenant.id,
      participantRole: "co_tenant",
      expectedLeaseRevision: 1,
      idempotencyKey: crypto.randomUUID(),
    },
  });
  expect(added.ok(), await added.text()).toBe(true);
  const child = ((await added.json()) as Schemas["LeaseMutationResponse"]).participants.find(
    (p) => p.tenantPartyId === other.tenant.id,
  )!;
  let calls = 0;
  let receipt: Schemas["LeaseMutationResponse"] | undefined;
  await page.route(`**/api/leases/${f.lease.id}/participants/${child.id}`, async (route) => {
    if (route.request().method() !== "DELETE") return route.continue();
    calls++;
    const response = await route.fetch();
    expect(response.ok(), await response.text()).toBe(true);
    receipt = (await response.json()) as Schemas["LeaseMutationResponse"];
    await route.abort("failed");
  });
  await page.goto(
    `/leasing?workflow=lease.participant.remove&target=${f.lease.id}&child=${child.id}`,
  );
  await page.getByLabel("I confirm removal of this Lease participant").check();
  await page.getByRole("button", { name: "Save remove lease participant", exact: true }).click();
  await expect(
    page.getByText("Draft saved · Command outcome_unknown", { exact: true }),
  ).toBeVisible();
  await page.goto("/settings/recovery");
  await page.getByRole("link", { name: "Resume lease.participant.remove", exact: true }).click();
  await page.getByRole("button", { name: "Check original result", exact: true }).click();
  await expect(page.getByRole("region", { name: "Committed result" })).toContainText(
    receipt!.operationId,
  );
  await expect(
    page.getByRole("link", { name: "Open committed Lease and related setup" }),
  ).toBeVisible();
  expect(calls).toBe(1);
  await page.reload();
  await expect(page.getByRole("region", { name: "Committed result" })).toContainText(
    receipt!.operationId,
  );
  expect(calls).toBe(1);
  await page.goto(
    `/leasing?workflow=lease.participant.remove&target=${f.lease.id}&child=${child.id}`,
  );
  await expect(page.getByRole("alert")).toContainText("does not belong");
});

test("acknowledgments require only walkthrough-active participants at exclusive boundaries", async ({
  page,
  request,
}) => {
  const f = await fixture(request),
    former = await fixture(request),
    future = await fixture(request);
  const shift = (days: number) =>
    new Date(Date.parse(`${f.today}T12:00:00Z`) + days * 86400000).toISOString().slice(0, 10);
  for (const [party, startsOn, endsOn] of [
    [former.tenant.id, f.today, shift(1)],
    [future.tenant.id, shift(2), null],
  ] as const) {
    const added = await request.post(`/api/leases/${f.lease.id}/participants`, {
      data: {
        tenantPartyId: party,
        participantRole: "co_tenant",
        startsOn,
        endsOn,
        expectedLeaseRevision: f.lease.leaseRevision,
        idempotencyKey: crypto.randomUUID(),
      },
    });
    expect(added.ok(), await added.text()).toBe(true);
    f.lease = (await added.json()) as Schemas["LeaseMutationResponse"];
  }
  const draft = await report(request, f, shift(1));
  await page.goto(`/leasing?workflow=inspection.report.acknowledge&target=${draft.id}`);
  await expect(page.getByLabel("Status (required)")).toHaveCount(1);
  await expect(page.getByRole("group", { name: new RegExp(f.tenant.id) })).toBeVisible();
  await expect(page.getByText(new RegExp(former.tenant.id))).toHaveCount(0);
  await expect(page.getByText(new RegExp(future.tenant.id))).toHaveCount(0);
  await page.getByLabel("Status (required)").selectOption("not_requested");
  await save(page, "Record inspection acknowledgments");
  const current = await request.get(`/api/condition-reports/${draft.id}`);
  const acknowledgments = ((await current.json()) as Schemas["ReportResponse"]).acknowledgments;
  expect(acknowledgments.map((a) => a.leaseParticipantId)).toEqual([f.lease.participants[0].id]);
});

test("changed Lease directory continuation restarts with its filters retained", async ({
  page,
  request,
}) => {
  const f = await fixture(request);
  for (let index = 0; index < 25; index++) {
    const added = await request.post("/api/leases", {
      data: {
        spaceId: f.lease.spaceId,
        leaseKind: "residential",
        contractStartsOn: f.today,
        occupancyStartsOn: f.today,
        initialTerm: {
          baseRentMinor: 100000,
          currencyCode: "USD",
          paymentFrequency: "monthly",
          paymentDueDay: 1,
          agreedSecurityDepositMinor: 0,
        },
        participants: [{ tenantPartyId: f.tenant.id, participantRole: "primary_tenant" }],
        expectedLeaseRevision: 0,
        idempotencyKey: crypto.randomUUID(),
      },
    });
    expect(added.ok(), await added.text()).toBe(true);
  }
  await page.goto(`/leasing?status=draft&propertyId=${f.property.id}`);
  await expect(page.getByText(/26 matching leases/)).toBeVisible();
  await request.patch(`/api/leases/${f.lease.id}`, {
    data: {
      notes: "Directory changed",
      expectedLeaseRevision: 1,
      idempotencyKey: crypto.randomUUID(),
    },
  });
  await page.getByRole("button", { name: "Next lease page", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("changed or expired");
  await page.getByRole("button", { name: "Restart Lease directory with these filters" }).click();
  await expect(page).not.toHaveURL(/cursor=/);
  await expect(page).toHaveURL(/status=draft/);
  await expect(page).toHaveURL(new RegExp(`propertyId=${f.property.id}`));
  await expect(page.getByText(/26 matching leases/)).toBeVisible();
});

test("termination negotiation and completion preserve the Lease and Space contracts", async ({
  page,
  request,
}) => {
  const f = await fixture(request);
  await execute(request, f);
  const advanced = await request.post("/__test__/lease-clock", { data: { days: 1 } });
  f.today = ((await advanced.json()) as { effectiveOn: string }).effectiveOn;
  await page.goto(`/leasing?workflow=lease.termination.create&target=${f.lease.id}`);
  await page.getByLabel("Reason (required)").selectOption("mutual");
  for (const name of [
    "Notice received on (required)",
    "Requested termination on (required)",
    "Expected move out on (required)",
  ])
    await page.getByLabel(name).fill(f.today);
  await save(page, "Request termination");
  const cases = await request.get(`/api/leases/${f.lease.id}/termination-cases`);
  const item = ((await cases.json()) as Schemas["TerminationCaseResponse"][])[0];
  await page.goto(
    `/leasing?workflow=lease.termination.proposal.add&target=${f.lease.id}&child=${item.id}`,
  );
  await page.getByLabel("Proposed termination on (required)").fill(f.today);
  await page.getByLabel("Expected move out on (required)").fill(f.today);
  await save(page, "Add termination proposal");
  const proposalResponse = await request.get(`/api/leases/${f.lease.id}/termination-cases`);
  const proposal = ((await proposalResponse.json()) as Schemas["TerminationCaseResponse"][])[0]
    .proposals[0];
  await page.goto(
    `/leasing?workflow=lease.termination.proposal.accept&target=${f.lease.id}&child=${item.id}`,
  );
  await page.getByLabel("Proposal id (required)").selectOption(proposal.id);
  await page.getByLabel("Accepted on (required)").fill(f.today);
  await page.getByLabel("I confirm this lifecycle change", { exact: true }).check();
  await save(page, "Accept termination proposal");
  await page.goto(
    `/leasing?workflow=lease.termination.complete&target=${f.lease.id}&child=${item.id}`,
  );
  await page.getByLabel("Actual move out on (required)").fill(f.today);
  await page.getByLabel("I confirm this lifecycle change", { exact: true }).check();
  await save(page, "Complete termination");
  const leaseResponse = await request.get(`/api/leases/${f.lease.id}`);
  expect(((await leaseResponse.json()) as Schemas["LeaseResponse"]).status).toBe("terminated");
});

for (const action of ["end", "terminate", "void"] as const) {
  test(`${action} Lease returns its original recorded lifecycle result`, async ({
    page,
    request,
  }) => {
    const f = await fixture(request, action === "void");
    await execute(request, f);
    if (action !== "void") {
      const advanced = await request.post("/__test__/lease-clock", { data: { days: 1 } });
      f.today = ((await advanced.json()) as { effectiveOn: string }).effectiveOn;
    }
    if (action === "terminate") {
      const created = await request.post(`/api/leases/${f.lease.id}/termination-cases`, {
        data: {
          reason: "mutual",
          noticeReceivedOn: f.today,
          requestedTerminationOn: f.today,
          expectedMoveOutOn: f.today,
          expectedLeaseRevision: 2,
          idempotencyKey: crypto.randomUUID(),
        },
      });
      expect(created.ok(), await created.text()).toBe(true);
      const termination = (await created.json()) as Schemas["TerminationCaseMutationResponse"];
      const proposed = await request.post(`/api/termination-cases/${termination.id}/proposals`, {
        data: {
          proposedTerminationOn: f.today,
          expectedMoveOutOn: f.today,
          expectedLeaseRevision: 3,
          idempotencyKey: crypto.randomUUID(),
        },
      });
      expect(proposed.ok(), await proposed.text()).toBe(true);
      const proposal = (await proposed.json()) as Schemas["TerminationCaseMutationResponse"];
      const accepted = await request.post(`/api/termination-cases/${termination.id}/accept`, {
        data: {
          proposalId: proposal.proposals[0].id,
          acceptedOn: f.today,
          confirmed: true,
          expectedLeaseRevision: 4,
          idempotencyKey: crypto.randomUUID(),
        },
      });
      expect(accepted.ok(), await accepted.text()).toBe(true);
    }
    await page.goto(`/leasing?workflow=lease.${action}&target=${f.lease.id}`);
    if (action !== "void") await page.getByLabel("Actual move out on (required)").fill(f.today);
    if (action === "terminate")
      await page.getByLabel("End reason (required)").selectOption("mutual_termination");
    await page.getByLabel("I confirm this lifecycle change", { exact: true }).check();
    await save(page, `${action[0].toUpperCase()}${action.slice(1)} lease`);
    const current = await request.get(`/api/leases/${f.lease.id}`);
    expect(((await current.json()) as Schemas["LeaseResponse"]).status).toBe(
      action === "end" ? "ended" : action === "terminate" ? "terminated" : "void",
    );
  });
}

test("inspection template, correction and comparison forms preserve their own lifecycles", async ({
  page,
  request,
}) => {
  await page.goto("/leasing?workflow=inspection.template.create");
  await page.getByLabel("Display name (required)").fill("Slice51 walk-through checklist");
  await page
    .getByRole("combobox", { name: "Applicability", exact: true })
    .selectOption("residential");
  await save(page, "Create inspection template");
  const templates = await request.get("/api/condition-checklist-templates");
  const template = ((await templates.json()) as Schemas["TemplateResponse"][]).find(
    (t) => t.displayName === "Slice51 walk-through checklist",
  )!;
  await page.goto(`/leasing?workflow=inspection.template.patch&target=${template.id}`);
  await page.getByLabel("Display name", { exact: true }).fill("Slice51 revised checklist");
  await save(page, "Edit inspection template");
  const f = await fixture(request),
    draft = await report(request, f);
  const acknowledged = await request.put(`/api/condition-reports/${draft.id}/acknowledgments`, {
    data: {
      expectedRevision: draft.revision,
      idempotencyKey: crypto.randomUUID(),
      acknowledgments: { [f.lease.participants[0].id]: { status: "not_requested" } },
    },
  });
  expect(acknowledged.status(), await acknowledged.text()).toBe(200);
  const finalized = await request.post(`/api/condition-reports/${draft.id}/finalize`, {
    data: {
      expectedRevision: ((await acknowledged.json()) as Schemas["ReportCommandResponse"]).revision,
      idempotencyKey: crypto.randomUUID(),
      confirmed: true,
    },
  });
  expect(finalized.status(), await finalized.text()).toBe(200);
  await page.goto(`/leasing?workflow=inspection.report.correct&target=${draft.id}`);
  await page.getByLabel("Correction reason (required)").fill("Correct the operator attribution");
  await page.getByLabel("Conducted by (required)").fill("Corrected operator");
  await save(page, "Correct finalized inspection");
  const reports = await request.get(`/api/leases/${f.lease.id}/condition-reports`);
  const items = ((await reports.json()) as Schemas["ReportListResponse"]).reports;
  expect(items.find((r) => r.id === draft.id)?.status).toBe("finalized");
  expect(items.find((r) => r.supersedesReportId === draft.id)?.status).toBe("draft");
  expect(items.find((r) => r.supersedesReportId === draft.id)?.conductedBy).toBe(
    "Corrected operator",
  );
  await page.goto(`/leasing?workflow=inspection.comparison.review&target=${f.lease.id}`);
  await expect(
    page.getByText(
      /Review condition evidence; comparisons do not create deductions\.|The report pair changed; review the current evidence again\./,
    ),
  ).toBeVisible();
});

test("move-out inspection setup, checklist and comparison remain explicit steps", async ({
  page,
  request,
}) => {
  const f = await fixture(request),
    pre = await report(request, f);
  const acknowledged = await request.put(`/api/condition-reports/${pre.id}/acknowledgments`, {
    data: {
      expectedRevision: pre.revision,
      idempotencyKey: crypto.randomUUID(),
      acknowledgments: { [f.lease.participants[0].id]: { status: "not_requested" } },
    },
  });
  expect(acknowledged.ok()).toBe(true);
  const finalized = await request.post(`/api/condition-reports/${pre.id}/finalize`, {
    data: {
      expectedRevision: ((await acknowledged.json()) as Schemas["ReportCommandResponse"]).revision,
      idempotencyKey: crypto.randomUUID(),
      confirmed: true,
    },
  });
  expect(finalized.ok(), await finalized.text()).toBe(true);
  const advanced = await request.post("/__test__/lease-clock", { data: { days: 1 } });
  const moveOut = ((await advanced.json()) as { effectiveOn: string }).effectiveOn;
  const ended = await request.post(`/api/leases/${f.lease.id}/end`, {
    data: {
      expectedLeaseRevision: 2,
      expectedRevision: 1,
      idempotencyKey: crypto.randomUUID(),
      actualMoveOutOn: moveOut,
      confirmed: true,
    },
  });
  expect(ended.ok(), await ended.text()).toBe(true);
  await page.goto(`/leasing?workflow=inspection.report.create&target=${f.lease.id}`);
  await page.getByLabel("Report kind (required)").selectOption("post_move_out");
  await page.getByLabel("Walkthrough on (required)").fill(moveOut);
  await page.getByLabel("Conducted by (required)").fill("Move-out operator");
  await save(page, "Create inspection draft");
  const reports = await request.get(`/api/leases/${f.lease.id}/condition-reports`);
  const post = ((await reports.json()) as Schemas["ReportListResponse"]).reports.find(
    (r) => r.reportKind === "post_move_out",
  )!;
  await page.goto(`/leasing?workflow=inspection.report.patch&target=${post.id}`);
  await page.getByLabel("Conducted by", { exact: true }).fill("Reviewed operator");
  await save(page, "Edit inspection draft");
  await page.goto(`/leasing?workflow=inspection.report.areas.replace&target=${post.id}`);
  await page.getByRole("button", { name: "Add areas entry", exact: true }).click();
  await page.getByLabel("Display name (required)").fill("Kitchen");
  await page.getByRole("button", { name: "Add observations entry", exact: true }).click();
  await page.getByLabel("Item name (required)").fill("Counter");
  await page.getByLabel("Condition state (required)").selectOption("good");
  await page.getByLabel("Is completed", { exact: true }).check();
  await save(page, "Edit inspection checklist");
  await page.goto(`/leasing?workflow=inspection.report.acknowledge&target=${post.id}`);
  await page.getByLabel("Status (required)").selectOption("not_requested");
  await save(page, "Record inspection acknowledgments");
  await page.goto(`/leasing?workflow=inspection.report.finalize&target=${post.id}`);
  await page.getByLabel("I confirm this lifecycle change", { exact: true }).check();
  await save(page, "Finalize inspection");
  await page.goto(`/leasing?workflow=inspection.comparison.review&target=${f.lease.id}`);
  await page.getByRole("button", { name: "Add comparisons entry", exact: true }).click();
  await page
    .getByRole("combobox", { name: "Pre observation id", exact: true })
    .selectOption(pre.areas[0].observations[0].id);
  const postDetail = await request.get(`/api/condition-reports/${post.id}`);
  await page
    .getByRole("combobox", { name: "Post observation id", exact: true })
    .selectOption(
      ((await postDetail.json()) as Schemas["ReportResponse"]).areas[0].observations[0].id,
    );
  await page.getByLabel("Comparison state (required)").selectOption("unchanged");
  await save(page, "Review condition comparison");
  const current = await request.get(`/api/leases/${f.lease.id}`);
  expect(((await current.json()) as Schemas["LeaseResponse"]).status).toBe("ended");
});

test("a stale Space timeline preserves lease inputs for explicit review", async ({
  page,
  request,
}) => {
  const f = await fixture(request);
  await page.goto(`/leasing?workflow=lease.execute&target=${f.lease.id}`);
  await page.getByLabel("Executed on (required)").fill(f.today);
  await page.getByLabel("I confirm this lifecycle change", { exact: true }).check();
  const changed = await request.put(`/api/spaces/${f.property.spaces[0].id}/availability`, {
    data: {
      availabilityStatus: "not_available",
      expectedRevision: f.property.spaces[0].revision,
      idempotencyKey: crypto.randomUUID(),
    },
  });
  expect(changed.status(), await changed.text()).toBe(200);
  await page.getByRole("button", { name: "Save execute lease", exact: true }).click();
  await expect(page.getByRole("alert")).toBeVisible();
  await expect(page.getByLabel("Executed on (required)")).toHaveValue(f.today);
  await page.getByRole("button", { name: "Review current source", exact: true }).click();
  await page.getByRole("button", { name: "Keep my edits with this reviewed revision" }).click();
  await save(page, "Execute lease");
});

test("inspection evidence resumes with original bytes and reconciles a lost response", async ({
  page,
  request,
}) => {
  const f = await fixture(request),
    draft = await report(request, f);
  const observation = draft.areas[0].observations[0];
  await page.goto(`/inspections/${draft.id}`);
  await page.getByRole("link", { name: "Attach evidence for Counter" }).click();
  await page.getByLabel("Evidence file (required)").setInputFiles({
    name: "counter.txt",
    mimeType: "text/plain",
    buffer: Buffer.from("Condition evidence"),
  });
  await page.getByLabel("Purpose (required)").selectOption("supporting_document");
  await page.getByRole("button", { name: "Save unfinished form" }).click();
  await expect(page.getByText("Draft saved · Command editing", { exact: true })).toBeVisible();
  await page.goto("/settings/recovery");
  await page.getByRole("link", { name: "Resume inspection.evidence.attach", exact: true }).click();
  await page.getByLabel("Evidence file (required)").setInputFiles({
    name: "counter.txt",
    mimeType: "text/plain",
    buffer: Buffer.from("Changed bytes"),
  });
  await expect(page.getByRole("alert")).toContainText("does not match");
  await page.getByLabel("Evidence file (required)").setInputFiles({
    name: "counter.txt",
    mimeType: "text/plain",
    buffer: Buffer.from("Condition evidence"),
  });
  let calls = 0;
  await page.route(`**/api/condition-observations/${observation.id}/evidence`, async (route) => {
    calls++;
    await route.fetch();
    await route.abort("failed");
  });
  await page.getByRole("button", { name: "Save attach inspection evidence", exact: true }).click();
  await expect(page.getByRole("button", { name: "Check original result" })).toBeVisible();
  await page.getByRole("button", { name: "Check original result" }).click();
  await expect(page.getByRole("region", { name: "Committed result" })).toBeVisible();
  expect(calls).toBe(1);
  const retained = await request.get(`/api/condition-observations/${observation.id}/report`);
  const item = (await retained.json()) as Schemas["ReportResponse"];
  expect(item.areas[0].observations[0].files).toHaveLength(1);
  expect(item.areas[0].observations[0].files[0].originalName).toBe("counter.txt");
});

test("inspection acknowledgments and finalization remain distinct from move-out", async ({
  page,
  request,
}) => {
  const f = await fixture(request),
    draft = await report(request, f);
  await page.goto(`/leasing?workflow=inspection.report.acknowledge&target=${draft.id}`);
  await page.getByLabel("Status (required)").selectOption("not_requested");
  await save(page, "Record inspection acknowledgments");
  await page.goto(`/leasing?workflow=inspection.report.finalize&target=${draft.id}`);
  await page.getByLabel("I confirm this lifecycle change", { exact: true }).check();
  await save(page, "Finalize inspection");
  await page.goto(`/inspections/${draft.id}`);
  await expect(page.getByRole("link", { name: "Attach evidence for Counter" })).toHaveCount(0);
  await page.getByText("Report actions", { exact: true }).click();
  await expect(page.getByRole("link", { name: "Correct finalized inspection" })).toBeVisible();
  const lease = await request.get(`/api/leases/${f.lease.id}`);
  expect(((await lease.json()) as Schemas["LeaseResponse"]).status).toBe("executed");
});

test("draft evidence archival preserves contextual history and unavailable files cannot open", async ({
  page,
  request,
}) => {
  const f = await fixture(request),
    draft = await report(request, f);
  const observation = draft.areas[0].observations[0];
  const uploaded = await request.post(`/api/condition-observations/${observation.id}/evidence`, {
    multipart: {
      purpose: "supporting_document",
      expected_revision: draft.revision,
      idempotency_key: crypto.randomUUID(),
      file: {
        name: "archive-evidence.txt",
        mimeType: "text/plain",
        buffer: Buffer.from("Evidence to retain"),
      },
    },
  });
  expect(uploaded.status(), await uploaded.text()).toBe(201);
  const file = (await uploaded.json()) as Schemas["EvidenceCommandResponse"];
  await page.route(`**/api/condition-reports/${draft.id}`, async (route) => {
    const response = await route.fetch();
    const data = (await response.json()) as Schemas["ReportResponse"];
    data.areas[0].observations[0].files[0].storageState = "missing";
    data.areas[0].observations[0].files[0].available = false;
    await route.fulfill({ response, json: data });
  });
  await page.goto(`/inspections/${draft.id}`);
  await expect(page.getByText("Content unavailable; opening disabled.")).toBeVisible();
  await expect(page.getByRole("link", { name: "Download archive-evidence.txt" })).toHaveCount(0);
  await page.unroute(`**/api/condition-reports/${draft.id}`);
  await page
    .getByRole("link", { name: "Archive evidence association for archive-evidence.txt" })
    .click();
  await page.getByLabel("Reason (required)").fill("Duplicate context evidence");
  await page.getByLabel("I confirm this lifecycle change", { exact: true }).check();
  await save(page, "Archive evidence link");
  await page.goto(`/inspections/${draft.id}`);
  await expect(page.getByRole("link", { name: "Download archive-evidence.txt" })).toHaveCount(0);
  const retained = await request.get(`/api/files/${file.id}`);
  const metadata = (await retained.json()) as Schemas["FileMetadataResponse"];
  expect(metadata.links[0].archiveReason).toBe("Duplicate context evidence");
  expect(metadata.links[0].archivedAt).not.toBeNull();
});

test("inspection section failure preserves the committed Lease and unavailable evidence cannot open", async ({
  page,
  request,
}) => {
  const f = await fixture(request);
  await execute(request, f);
  await page.route(`**/api/leases/${f.lease.id}/condition-reports`, (route) =>
    route.fulfill({ status: 503, json: { detail: { message: "Inspection read unavailable" } } }),
  );
  await page.goto(`/leases/${f.lease.id}/details`);
  await expect(page.getByRole("alert")).toContainText("Lease result remains committed");
  await expect(page.getByRole("region", { name: "Related rent setup" })).toBeVisible();
});
