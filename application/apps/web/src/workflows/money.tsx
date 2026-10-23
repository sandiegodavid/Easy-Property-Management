import { DynamicFilterForm } from "../shared/dynamic-filter-form";
import { useQuery } from "@tanstack/react-query";
import { useLocation, useSearchParams } from "react-router-dom";
import { ParentBackLink, SourceWorkflowLink as Link } from "../shared/home-navigation";
import { api } from "@epm/contracts";
import { record, scalar } from "@epm/contracts/workflows";
import { useWorkspace } from "../app/workspace-gate";
import { CommandLinks } from "./command";
import { readResult } from "./reads";
import { MoneyCommand } from "./money-command";
import { MoneyRecord, MoneyFacts, moneyRecordUrl, type MoneyKind } from "./money-records";
import { MoneyReporting } from "./money-reporting";
import { ExpenseEvidenceArchive, ExpenseFilters } from "./expense-context";
import { DepositFilters, DepositEvidenceArchive } from "./deposit-context";
import { CheckFilters } from "./check-context";
import { OwnerReportFilters } from "./owner-report-context";
import { partyNames } from "../shared/party-names";
import { formatDate } from "../shared/presentation";

const tabs = [
  "rent",
  "receipts",
  "expenses",
  "deposits",
  "checks",
  "reports",
  "categories",
  "reporting",
] as const;
const tabLabels: Record<(typeof tabs)[number], string> = {
  rent: "Rent",
  receipts: "Received rent",
  expenses: "Expenses",
  deposits: "Deposits",
  checks: "Scheduled checks",
  reports: "Owner reports",
  categories: "Expense categories",
  reporting: "Reporting",
};
export function MoneyWorkspace() {
  const [params] = useSearchParams();
  const location = useLocation();
  if (params.get("workflow") === "file.link.archive")
    return params.has("accountId") ? (
      <DepositEvidenceArchive key={params.toString()} />
    ) : (
      <ExpenseEvidenceArchive key={params.toString()} />
    );
  if (params.has("workflow"))
    return (
      <MoneyCommand
        key={
          params.get("workflow") === "finance.rent_receipt.create"
            ? location.key
            : params.toString()
        }
      />
    );
  const kind = params.get("record") as MoneyKind | null;
  if (kind && params.get("id")) {
    if (
      ![
        "expectation",
        "receipt",
        "expense",
        "check",
        "report",
        "deposit",
        "settlement",
        "category",
      ].includes(kind)
    )
      return <p role="alert">Unknown money record kind.</p>;
    return <MoneyRecord kind={kind} id={params.get("id")!} />;
  }
  if (params.get("file")) return <FileMetadata id={params.get("file")!} />;
  const tab = tabs.find((item) => item === params.get("tab")) ?? "rent";
  return (
    <section aria-label="Money workspace">
      <h2>Money</h2>
      {params.get("propertyId") ? (
        <MoneyPropertyContext id={params.get("propertyId")!} />
      ) : params.get("leaseId") ? (
        <MoneyLeasePropertyContext leaseId={params.get("leaseId")!} />
      ) : null}
      <p>
        Recorded payments, paid expenses and held deposits are separate records. Scheduled checks
        and pending owner reports are not received income.
      </p>
      <nav className="page-tabs" aria-label="Money views">
        {tabs.map((item) => {
          const next = new URLSearchParams(params);
          next.set("tab", item);
          next.delete("cursor");
          next.delete("metric");
          next.delete("sourceRevision");
          return (
            <Link key={item} to={`/money?${next}`} aria-current={tab === item ? "page" : undefined}>
              {tabLabels[item]}
            </Link>
          );
        })}
      </nav>
      {tab === "reporting" ? <MoneyReporting /> : <MoneyDirectory key={tab} tab={tab} />}
    </section>
  );
}

function MoneyLeasePropertyContext({ leaseId }: { leaseId: string }) {
  const { scope } = useWorkspace();
  const context = useQuery({
    queryKey: scope.key("money-property-contexts", [], [leaseId]),
    retry: false,
    queryFn: async ({ signal }) =>
      readResult(
        await api.GET("/api/money/property-contexts", {
          signal,
          params: { query: { leaseIds: [leaseId] } },
        }),
      ),
  });
  const propertyId = context.data?.leaseProperties[leaseId];
  if (propertyId) return <MoneyPropertyContext id={propertyId} />;
  return (
    <section className="money-property-context" aria-label="Property context">
      <p className="money-property-label">Property</p>
      {context.isPending ? (
        <p role="status">Loading property…</p>
      ) : (
        <p role="alert">
          The property for this lease could not be loaded.{" "}
          <button type="button" onClick={() => void context.refetch()}>
            Retry
          </button>
        </p>
      )}
    </section>
  );
}

function MoneyPropertyContext({ id }: { id: string }) {
  const { scope } = useWorkspace();
  const property = useQuery({
    queryKey: scope.key("portfolio-record", id),
    queryFn: async ({ signal }) =>
      readResult(
        await api.GET("/api/properties/{property_id}", {
          signal,
          params: { path: { property_id: id } },
        }),
      ),
  });
  return (
    <section className="money-property-context" aria-label="Property context">
      <p className="money-property-label">Property</p>
      {property.isPending && <p role="status">Loading property…</p>}
      {property.error && (
        <p role="alert">
          Property details are unavailable.{" "}
          <button type="button" onClick={() => void property.refetch()}>
            Retry
          </button>
        </p>
      )}
      {property.data && (
        <>
          <h3>
            <Link to={`/properties/${id}/overview`}>{property.data.displayName}</Link>
          </h3>
          <p>
            {property.data.addressLine1}, {property.data.city}
          </p>
        </>
      )}
    </section>
  );
}

function FileMetadata({ id }: { id: string }) {
  const { scope } = useWorkspace();
  const file = useQuery({
    queryKey: scope.key("money-file", id),
    queryFn: async ({ signal }) =>
      readResult(
        await api.GET("/api/files/{file_id}", { signal, params: { path: { file_id: id } } }),
      ),
  });
  return (
    <section aria-label="Evidence metadata">
      <ParentBackLink to="/money">← Back to Money</ParentBackLink>
      <h2>Evidence metadata and history</h2>
      {file.isPending && <p role="status">Loading retained evidence…</p>}
      {file.error && <p role="alert">{file.error.message}</p>}
      {file.data && (
        <>
          <MoneyFacts
            value={file.data}
            fields={[
              "originalName",
              "mediaType",
              "sizeBytes",
              "storageState",
              "verifiedAt",
              "createdAt",
            ]}
          />
          {file.data.storageState === "available" ? (
            <a href={`/api/files/${id}/content`}>Download {file.data.originalName}</a>
          ) : (
            <p>Content unavailable; opening disabled.</p>
          )}
          {file.data.links.map((link) => (
            <MoneyFacts
              key={link.id}
              value={link}
              fields={[
                "entityType",
                "entityId",
                "purpose",
                "archivedAt",
                "archiveReason",
                "createdAt",
              ]}
            />
          ))}
        </>
      )}
    </section>
  );
}

function MoneyDirectory({ tab }: { tab: Exclude<(typeof tabs)[number], "reporting"> }) {
  const { scope } = useWorkspace();
  const [params, setParams] = useSearchParams();
  const leaseId = params.get("leaseId") ?? undefined,
    propertyId = params.get("propertyId") ?? undefined;
  const ownerId = params.get("ownerId") ?? undefined,
    cursor = params.get("cursor") ?? undefined;
  const result = useQuery({
    queryKey: scope.key("money-directory", tab, params.toString()),
    retry: false,
    queryFn: async ({ signal }) => {
      const query = { leaseId, propertyId, cursor, pageSize: 25 };
      switch (tab) {
        case "rent":
          return readResult(
            await api.GET("/api/rent-expectations", {
              signal,
              params: {
                query: {
                  ...query,
                  includeVoided: params.get("history") === "true",
                  status: ["unpaid", "partial", "paid"].includes(params.get("status") ?? "")
                    ? (params.get("status") as "unpaid" | "partial" | "paid")
                    : undefined,
                  timelinessStatus: [
                    "upcoming",
                    "due",
                    "late",
                    "missed",
                    "paid_on_time",
                    "paid_late",
                  ].includes(params.get("timeliness") ?? "")
                    ? (params.get("timeliness") as
                        "upcoming" | "due" | "late" | "missed" | "paid_on_time" | "paid_late")
                    : undefined,
                  dueFrom: params.get("dueFrom") ?? undefined,
                  dueTo: params.get("dueTo") ?? undefined,
                },
              },
            }),
          );
        case "receipts":
          return readResult(
            await api.GET("/api/rent-receipts", {
              signal,
              params: {
                query: {
                  ...query,
                  includeVoided: params.get("history") === "true",
                  receivedFrom: params.get("receivedFrom") ?? undefined,
                  receivedTo: params.get("receivedTo") ?? undefined,
                  receivedByPartyId: params.get("receivedByPartyId") ?? undefined,
                  replacesReceiptId: params.get("replacesReceiptId") ?? undefined,
                },
              },
            }),
          );
        case "expenses":
          return readResult(
            await api.GET("/api/expenses", {
              signal,
              params: {
                query: {
                  propertyId,
                  spaceId: params.get("spaceId") ?? undefined,
                  categoryId: params.get("categoryId") ?? undefined,
                  providerPartyId: params.get("providerPartyId") ?? undefined,
                  paidByKind:
                    params.get("paidByKind") === "party"
                      ? "party"
                      : params.get("paidByKind") === "local_operator"
                        ? "local_operator"
                        : undefined,
                  paidByPartyId: params.get("paidByPartyId") ?? undefined,
                  paidFrom: params.get("paidFrom") ?? undefined,
                  paidTo: params.get("paidTo") ?? undefined,
                  hasEvidence:
                    params.get("hasEvidence") === "true"
                      ? true
                      : params.get("hasEvidence") === "false"
                        ? false
                        : undefined,
                  cursor,
                  pageSize: 25,
                  includeVoided: params.get("history") === "true",
                },
              },
            }),
          );
        case "checks":
          return readResult(
            await api.GET("/api/prepaid-checks", {
              signal,
              params: {
                query: {
                  ...query,
                  spaceId: params.get("spaceId") ?? undefined,
                  payerPartyId: params.get("payerPartyId") ?? undefined,
                  expectationId: params.get("expectationId") ?? undefined,
                  status: ["scheduled", "deposited", "returned", "voided", "replaced"].includes(
                    params.get("status") ?? "",
                  )
                    ? (params.get("status") as
                        "scheduled" | "deposited" | "returned" | "voided" | "replaced")
                    : undefined,
                  eligibility: ["eligible", "not_yet_eligible", "not_applicable"].includes(
                    params.get("eligibility") ?? "",
                  )
                    ? (params.get("eligibility") as
                        "eligible" | "not_yet_eligible" | "not_applicable")
                    : undefined,
                },
              },
            }),
          );
        case "reports":
          return readResult(
            await api.GET("/api/owner-rent-reports", {
              signal,
              params: {
                query: {
                  ...query,
                  ownerPartyId: ownerId,
                  status: ["pending", "verified", "rejected"].includes(params.get("status") ?? "")
                    ? (params.get("status") as "pending" | "verified" | "rejected")
                    : undefined,
                  receivedFrom: params.get("receivedFrom") ?? undefined,
                  receivedTo: params.get("receivedTo") ?? undefined,
                  hasEvidence: params.has("hasEvidence")
                    ? params.get("hasEvidence") === "true"
                    : undefined,
                  receiptLifecycle: ["active", "voided"].includes(
                    params.get("receiptLifecycleStatus") ?? "",
                  )
                    ? (params.get("receiptLifecycleStatus") as "active" | "voided")
                    : undefined,
                },
              },
            }),
          );
        case "deposits":
          return readResult(
            await api.GET("/api/security-deposits", {
              signal,
              params: {
                query: {
                  ...query,
                  spaceId: params.get("spaceId") ?? undefined,
                  settlementStatus:
                    (params.get("settlementStatus") as
                      "draft" | "approved" | "completed" | undefined) ?? undefined,
                  deadlineState:
                    (params.get("deadlineState") as
                      "due" | "due_today" | "overdue" | "complete" | undefined) ?? undefined,
                  unresolvedBalance: params.has("unresolvedBalance")
                    ? params.get("unresolvedBalance") === "true"
                    : undefined,
                },
              },
            }),
          );
        case "categories":
          return {
            items: readResult(
              await api.GET("/api/expense-categories", {
                signal,
                params: { query: { includeArchived: true } },
              }),
            ),
            nextCursor: null,
          };
      }
    },
    enabled:
      (!ownerId || tab === "reports" || !!propertyId) &&
      !(tab === "receipts" && propertyId && !leaseId) &&
      !(tab === "expenses" && leaseId),
  });
  const kinds: Record<typeof tab, MoneyKind> = {
    rent: "expectation",
    receipts: "receipt",
    expenses: "expense",
    checks: "check",
    reports: "report",
    deposits: "deposit",
    categories: "category",
  };
  const actions: Record<typeof tab, string[]> = {
    rent: leaseId
      ? [
          "finance.rent_expectation.synchronize",
          "finance.rent_receipt.create",
          "finance.prepaid_check.create",
        ]
      : [],
    receipts: leaseId ? ["finance.rent_receipt.create"] : [],
    expenses: ["finance.expense.create"],
    checks: leaseId ? ["finance.prepaid_check.create"] : [],
    reports: ["owner_rent_report.create"],
    deposits: ["finance.deposit_account.create"],
    categories: ["finance.expense_category.create"],
  };
  const items = (result.data?.items ?? []).map(record);
  const propertyIds = [
    ...new Set(
      items.flatMap((item) => {
        const id = item.propertyId ?? record(item.property).id ?? propertyId;
        return typeof id === "string" ? [id] : [];
      }),
    ),
  ].sort();
  const leaseIds = [
    ...new Set(
      items.flatMap((item) =>
        !item.propertyId &&
        !record(item.property).id &&
        !propertyId &&
        typeof item.leaseId === "string"
          ? [item.leaseId]
          : [],
      ),
    ),
  ].sort();
  const contexts = useQuery({
    queryKey: scope.key("money-property-contexts", propertyIds, leaseIds),
    enabled: tab !== "categories" && propertyIds.length + leaseIds.length > 0,
    queryFn: async ({ signal }) =>
      readResult(
        await api.GET("/api/money/property-contexts", {
          signal,
          params: { query: { propertyIds, leaseIds } },
        }),
      ),
  });
  const groups = new Map<string, Record<string, unknown>[]>();
  const payerIds = [
    ...new Set(
      items.flatMap((item) => (typeof item.paidByPartyId === "string" ? [item.paidByPartyId] : [])),
    ),
  ].sort();
  const payers = useQuery({
    queryKey: scope.key("expense-payer-names", payerIds),
    enabled: tab === "expenses" && payerIds.length > 0,
    queryFn: ({ signal }) => partyNames(payerIds, signal),
  });
  for (const item of items) {
    const group =
      tab === "categories"
        ? "categories"
        : scalar(
            item.propertyId ??
              record(item.property).id ??
              propertyId ??
              contexts.data?.leaseProperties[scalar(item.leaseId)],
            "unassigned",
          );
    groups.set(group, [...(groups.get(group) ?? []), item]);
  }
  return (
    <section aria-label={`${tabLabels[tab]} records`}>
      <MoneyScope />
      {tab === "expenses" && <ExpenseFilters />}
      {tab === "deposits" && <DepositFilters />}
      {tab === "checks" && <CheckFilters />}
      {tab === "reports" && <OwnerReportFilters />}
      {tab === "receipts" && (
        <DynamicFilterForm
          className="directory-filters"
          onSubmit={(event) => {
            event.preventDefault();
            const data = new FormData(event.currentTarget);
            const next = new URLSearchParams(params);
            for (const key of [
              "receivedFrom",
              "receivedTo",
              "receivedByPartyId",
              "replacesReceiptId",
            ]) {
              const value = data.get(key);
              if (typeof value === "string" && value) next.set(key, value);
              else next.delete(key);
            }
            next.delete("cursor");
            setParams(next, { replace: true, preventScrollReset: true });
          }}
        >
          <label>
            Received from
            <input
              type="date"
              name="receivedFrom"
              defaultValue={params.get("receivedFrom") ?? ""}
            />
          </label>
          <label>
            Received to
            <input type="date" name="receivedTo" defaultValue={params.get("receivedTo") ?? ""} />
          </label>
          <label>
            Recipient Party ID
            <input
              name="receivedByPartyId"
              maxLength={36}
              defaultValue={params.get("receivedByPartyId") ?? ""}
            />
          </label>
          <label>
            Replaces receipt ID
            <input
              name="replacesReceiptId"
              maxLength={36}
              defaultValue={params.get("replacesReceiptId") ?? ""}
            />
          </label>
        </DynamicFilterForm>
      )}
      {tab === "rent" && (
        <DynamicFilterForm
          className="directory-filters"
          onSubmit={(event) => {
            event.preventDefault();
            const data = new FormData(event.currentTarget);
            const next = new URLSearchParams(params);
            for (const key of ["status", "timeliness", "dueFrom", "dueTo"]) {
              const value = data.get(key);
              if (typeof value === "string" && value) next.set(key, value);
              else next.delete(key);
            }
            next.delete("cursor");
            setParams(next, { replace: true, preventScrollReset: true });
          }}
        >
          <label>
            Settlement
            <select name="status" defaultValue={params.get("status") ?? ""}>
              <option value="">Any</option>
              {["unpaid", "partial", "paid"].map((status) => (
                <option key={status} value={status}>
                  {status}
                </option>
              ))}
            </select>
          </label>
          <label>
            Timeliness
            <select name="timeliness" defaultValue={params.get("timeliness") ?? ""}>
              <option value="">Any</option>
              {["upcoming", "due", "late", "missed", "paid_on_time", "paid_late"].map((status) => (
                <option key={status} value={status}>
                  {status.replaceAll("_", " ")}
                </option>
              ))}
            </select>
          </label>
          <label>
            Due from
            <input type="date" name="dueFrom" defaultValue={params.get("dueFrom") ?? ""} />
          </label>
          <label>
            Due to
            <input type="date" name="dueTo" defaultValue={params.get("dueTo") ?? ""} />
          </label>
        </DynamicFilterForm>
      )}
      {tab === "receipts" && propertyId && !leaseId && (
        <p>
          Select a Lease for its receipt ledger, or use Reporting with an explicit period for
          Property receipt sources.
        </p>
      )}
      {tab === "expenses" && leaseId && (
        <p>
          Expenses belong to Properties. Remove the Lease filter and select the owning Property to
          read paid spending.
        </p>
      )}
      {tab === "categories" && <p>The Expense category catalog is shared across the workspace.</p>}
      {ownerId && tab !== "reports" && !propertyId && (
        <p>
          Select a related Property to view its whole-property records. Ownership does not establish
          amounts due to this owner.{" "}
          <Link to={`/owners/${ownerId}/money`}>Owner money context</Link>
        </p>
      )}
      {leaseId && <Link to={`/leases/${leaseId}/details`}>Lease and rent terms</Link>}
      {(tab === "rent" || tab === "checks") && !leaseId && (
        <p>
          Open a Lease from <Link to="/leasing">Leasing</Link> to review its schedule and record
          payments or checks.
        </p>
      )}
      <CommandLinks
        keys={actions[tab]}
        target={tab === "rent" || tab === "receipts" || tab === "checks" ? leaseId : undefined}
        title="Money actions"
        asButtons
        collapsible={false}
      />
      {(tab === "expenses" || tab === "rent" || tab === "receipts") && (
        <label>
          <input
            type="checkbox"
            checked={params.get("history") === "true"}
            onChange={(event) => {
              const next = new URLSearchParams(params);
              next.set("history", String(event.target.checked));
              next.delete("cursor");
              setParams(next);
            }}
          />
          Include voided history
        </label>
      )}
      {result.isFetching && <p role="status">Loading money records…</p>}
      {result.error && (
        <div role="alert">
          <p>{result.error.message} Money information is unavailable.</p>
          <button
            onClick={() => {
              const next = new URLSearchParams(params);
              next.delete("cursor");
              setParams(next);
              void result.refetch();
            }}
          >
            Restart with these filters
          </button>
        </div>
      )}
      {result.data?.items.length === 0 && <p>No records match these filters.</p>}
      {[...groups].map(([groupId, records]) => (
        <section
          key={groupId}
          className="money-property-group"
          aria-label={
            groupId === "categories"
              ? "Shared expense categories"
              : (contexts.data?.propertyNames[groupId] ??
                scalar(record(records[0]?.property).displayName, "Property records"))
          }
        >
          <header className="money-property-group-heading">
            <h3>
              {groupId === "categories" ? (
                "Shared expense categories"
              ) : groupId === "unassigned" ? (
                contexts.isFetching ? (
                  "Loading property…"
                ) : (
                  "Property unavailable"
                )
              ) : (
                <Link to={`/properties/${groupId}/overview`}>
                  {contexts.data?.propertyNames[groupId] ??
                    scalar(
                      record(records[0]?.property).displayName,
                      contexts.isFetching ? "Loading property…" : "Property name unavailable",
                    )}
                </Link>
              )}
            </h3>
            <span>
              {records.length} {records.length === 1 ? "record" : "records"} on this page
            </span>
          </header>
          {contexts.error && tab !== "categories" && (
            <p role="status">
              Property names could not be loaded.{" "}
              <button type="button" onClick={() => void contexts.refetch()}>
                Retry property names
              </button>
            </p>
          )}
          <div className="money-record-list">
            {records.map((item) => {
              const id = scalar(item.id),
                status = scalar(
                  item.status ?? item.lifecycleStatus ?? item.settlementStatus,
                  tab === "categories" ? (item.archivedAt ? "archived" : "active") : "recorded",
                ),
                date = scalar(
                  item.dueOn ?? item.paidOn ?? item.receivedOn ?? item.checkDatedOn,
                  "",
                );
              return (
                <article key={id} className="money-record-card">
                  <header className="money-record-header">
                    <h4>
                      <Link to={moneyRecordUrl(kinds[tab], id)}>
                        {scalar(
                          item.displayName ?? item.payeeName ?? item.ownerDisplayNameSnapshot,
                          {
                            rent: "Rent due",
                            receipts: "Rent received",
                            expenses: "Expense",
                            checks: "Scheduled check",
                            reports: "Owner rent report",
                            deposits: "Security deposit",
                            categories: "Expense category",
                          }[tab],
                        )}
                      </Link>
                    </h4>
                    <span className="money-record-status" data-status={status}>
                      {status
                        .replaceAll("_", " ")
                        .replace(/^./, (character) => character.toUpperCase())}
                    </span>
                  </header>
                  {date && (
                    <p className="money-record-date">
                      {tab === "rent"
                        ? "Due"
                        : tab === "expenses"
                          ? "Paid"
                          : tab === "checks"
                            ? "Check dated"
                            : "Received"}{" "}
                      <time dateTime={date}>{formatDate(date)}</time>
                    </p>
                  )}
                  <MoneyFacts
                    value={
                      tab === "expenses"
                        ? {
                            ...item,
                            datePaid: item.paidOn,
                            property: record(item.property).displayName,
                            space: record(item.space).displayName ?? "Whole Property",
                            category: record(item.category).displayName,
                            paidTo: item.payeeName,
                            paidBy:
                              item.paidByKind === "party"
                                ? (payers.data?.get(scalar(item.paidByPartyId)) ??
                                  (payers.error ? "Payer name unavailable" : "Loading payer…"))
                                : "You",
                            evidence: Array.isArray(item.activeEvidence)
                              ? item.activeEvidence.length
                              : 0,
                          }
                        : item
                    }
                    labels={
                      tab === "rent"
                        ? {
                            expectedAmountMinor: "Expected",
                            receivedAmountMinor: "Money received",
                            outstandingAmountMinor: "Still due",
                            timelinessStatus: "Payment timing",
                            settlementStatus: "Settlement",
                          }
                        : undefined
                    }
                    fields={[
                      ...(tab === "expenses"
                        ? [
                            "datePaid",
                            "property",
                            "space",
                            "category",
                            "paidTo",
                            "paidBy",
                            "evidence",
                            "lifecycleStatus",
                          ]
                        : []),
                      "expectedAmountMinor",
                      "receivedAmountMinor",
                      "outstandingAmountMinor",
                      "amountMinor",
                      "amount",
                      "activeReceivedAmount",
                      "activeRefundedAmount",
                      "settlementStatus",
                      "timelinessStatus",
                      "receiptLifecycleStatus",
                      "financiallyEffective",
                      ...(tab === "checks"
                        ? ["depositEligibility", "reminderStatus", "checkDatedOn"]
                        : []),
                      ...(tab === "expenses" ? ["activeRefundedAmount", "netAmount"] : []),
                    ]}
                  />
                  {tab === "rent" && (
                    <p className="money-record-period">
                      Due date: {formatDate(scalar(item.dueOn))} · Covered period:{" "}
                      {formatDate(scalar(item.periodStartsOn))} –{" "}
                      {formatDate(scalar(item.periodEndsOn))}.{" "}
                      <Link to={moneyRecordUrl("expectation", id)}>
                        Review amounts and receipt allocations
                      </Link>
                    </p>
                  )}
                </article>
              );
            })}
          </div>
        </section>
      ))}
      {result.data?.nextCursor && (
        <button
          onClick={() => {
            const next = new URLSearchParams(params);
            next.set("cursor", result.data.nextCursor!);
            setParams(next);
          }}
        >
          Next money page
        </button>
      )}
      {cursor && (
        <button
          onClick={() => {
            const next = new URLSearchParams(params);
            next.delete("cursor");
            setParams(next);
          }}
        >
          First money page
        </button>
      )}
    </section>
  );
}

export function MoneyScope() {
  const [params, setParams] = useSearchParams();
  const { scope } = useWorkspace();
  const ownerId = params.get("ownerId");
  const owner = useQuery({
    queryKey: scope.key("money-owner-name", ownerId),
    enabled: !!ownerId,
    queryFn: ({ signal }) => partyNames([ownerId!], signal),
  });
  return (
    <>
      {["propertyId", "leaseId", "ownerId"].map(
        (key) =>
          params.get(key) && (
            <p key={key}>
              {key === "propertyId"
                ? "Showing this property’s records."
                : key === "leaseId"
                  ? "Showing this lease’s records."
                  : `Showing ${owner.data?.get(ownerId!) ?? "this owner"}’s records.`}{" "}
              <button
                onClick={() => {
                  const next = new URLSearchParams(params);
                  next.delete(key);
                  next.delete("cursor");
                  next.delete("sourceRevision");
                  setParams(next);
                }}
              >
                Remove {key.replace("Id", "")} filter
              </button>
            </p>
          ),
      )}
    </>
  );
}
