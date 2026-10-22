import { expect, type APIRequestContext } from "@playwright/test";
import type { components } from "@epm/contracts/generated";

export type Schema = components["schemas"];

export async function post<T>(request: APIRequestContext, path: string, data: unknown): Promise<T> {
  const response = await request.post(path, { data });
  expect(response.ok(), await response.text()).toBe(true);
  return (await response.json()) as T;
}

export function property(request: APIRequestContext) {
  return post<Schema["PropertyMutationResponse"]>(request, "/api/properties", {
    displayName: `Contract house ${crypto.randomUUID().slice(0, 8)}`,
    addressLine1: "20 Maple Street",
    city: "Portland",
    region: "OR",
    countryCode: "US",
    propertyType: "single_family_home",
    expectedPropertyRevision: 0,
    idempotencyKey: crypto.randomUUID(),
    ownerships: [
      {
        ownerKind: "client_owner",
        inlineParty: {
          partyKind: "individual",
          displayName: `Contract owner ${crypto.randomUUID().slice(0, 8)}`,
        },
      },
    ],
  });
}

export async function lease(request: APIRequestContext) {
  const home = await property(request);
  const tenant = await post<Schema["TenantMutationResponse"]>(request, "/api/tenants", {
    partyKind: "individual",
    displayName: `Contract tenant ${crypto.randomUUID().slice(0, 8)}`,
    officialIds: [{ documentType: "passport", issuingCountry: "US", lastFour: "TEST" }],
    expectedRevision: 0,
    idempotencyKey: crypto.randomUUID(),
  });
  const today = home.effectiveLocalDate;
  const item = await post<Schema["LeaseMutationResponse"]>(request, "/api/leases", {
    expectedLeaseRevision: 0,
    idempotencyKey: crypto.randomUUID(),
    spaceId: home.spaces[0].id,
    leaseKind: "residential",
    contractStartsOn: `${today.slice(0, 7)}-01`,
    occupancyStartsOn: today,
    initialTerm: {
      baseRentMinor: 195000,
      currencyCode: "USD",
      paymentFrequency: "monthly",
      paymentDueDay: 1,
      agreedSecurityDepositMinor: 0,
    },
    participants: [{ tenantPartyId: tenant.id, participantRole: "primary_tenant" }],
  });
  return { property: home, tenant, lease: item, today };
}

export async function rent(request: APIRequestContext) {
  const f = await lease(request);
  await post(request, `/api/leases/${f.lease.id}/execute`, {
    expectedLeaseRevision: f.lease.leaseRevision,
    expectedRevision: f.property.spaces[0].revision,
    idempotencyKey: crypto.randomUUID(),
    confirmed: true,
    executedOn: f.today,
  });
  const schedule = await post<Schema["SynchronizeResponse"]>(
    request,
    `/api/leases/${f.lease.id}/rent-expectations/synchronize`,
    {
      expectedRevision: 0,
      idempotencyKey: crypto.randomUUID(),
      leaseTermId: f.lease.terms[0].id,
      scheduleAnchorOn: `${f.today.slice(0, 7)}-01`,
      throughOn: new Date(Date.UTC(Number(f.today.slice(0, 4)), Number(f.today.slice(5, 7)) + 1, 0))
        .toISOString()
        .slice(0, 10),
    },
  );
  expect(schedule.items.length).toBeGreaterThan(0);
  return { ...f, expectation: schedule.items[0], rentLedgerRevision: schedule.rentLedgerRevision };
}

export async function issue(request: APIRequestContext) {
  const home = await property(request);
  const item = await post<Schema["IssueCommandResponse"]>(request, "/api/maintenance-issues", {
    propertyId: home.id,
    summary: "Contract repair",
    description: "Check the kitchen tap",
    category: "plumbing",
    priority: "normal",
    reportedAtUtc: home.asOf,
    reporter: { role: "manager", subjectKind: "local_operator" },
    expectedRevision: 0,
    idempotencyKey: crypto.randomUUID(),
  });
  return { property: home, issue: item };
}

export function aiDraft(sourceId: string): Schema["DraftDetailResponse"] {
  return {
    id: "00000000-0000-4000-8000-000000000191",
    runId: "00000000-0000-4000-8000-000000000192",
    entityKind: "summary",
    status: "proposed",
    version: 1,
    sourceEntityType: "maintenance_issue",
    sourceEntityId: sourceId,
    actionType: "maintenance.summary",
    owningModule: "maintenance",
    updatedAt: "2026-10-12T12:00:00Z",
    draftPayload: { summary: "Navigation draft" },
    confidence: { label: "medium", provenance: "synthetic assessment" },
    governedInput: { description: "Synthetic source" },
    sourceRevision: "1",
    sourceFingerprint: "a".repeat(64),
    currentSource: {
      revision: "1",
      fingerprint: "a".repeat(64),
      tombstoned: false,
      availability: "available",
      comparisonState: "unchanged",
    },
    approvalAvailable: false,
    reviewHistory: [],
    supersedesDraftId: null,
    createdAt: "2026-10-12T12:00:00Z",
    terminalAt: null,
    provenance: {
      executionKind: "provider_generation",
      transportProvider: "synthetic-provider",
      adapterVersion: "1",
      modelIdentifier: "summary-model",
      executionLocation: "on_device",
      modelArtifactDigest: "sha256:local",
      quantization: "Q4",
      runtimeId: "runtime",
      runtimeVersion: "1",
      promptTemplateId: "maintenance.summary",
      promptTemplateVersion: 1,
      outputSchemaVersion: 1,
      redactionProfile: "maintenance-summary",
      redactionProfileVersion: 1,
      promptTokens: 12,
      completionTokens: 8,
      correlationId: "00000000-0000-4000-8000-000000000193",
    },
  };
}
