import { useQuery } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
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
export function MoneyWorkspace() {
  const [params] = useSearchParams();
  if (params.get("workflow") === "file.link.archive")
    return params.has("accountId") ? (
      <DepositEvidenceArchive key={params.toString()} />
    ) : (
      <ExpenseEvidenceArchive key={params.toString()} />
    );
  if (params.has("workflow")) return <MoneyCommand key={params.toString()} />;
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
      <p>
        Recorded payments, paid expenses and held deposits are separate records. Scheduled checks
        and pending owner reports are not received income.
      </p>
      <nav aria-label="Money views">
        {tabs.map((item) => {
          const next = new URLSearchParams(params);
          next.set("tab", item);
          next.delete("cursor");
          next.delete("metric");
          next.delete("sourceRevision");
          return (
            <Link key={item} to={`/money?${next}`}>
              {
                {
                  rent: "Rent",
                  receipts: "Received rent",
                  expenses: "Expenses",
                  deposits: "Deposits",
                  checks: "Scheduled checks",
                  reports: "Owner reports",
                  categories: "Expense categories",
                  reporting: "Reporting",
                }[item]
              }
            </Link>
          );
        })}
      </nav>
      {tab === "reporting" ? <MoneyReporting /> : <MoneyDirectory key={tab} tab={tab} />}
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
      <h2>Evidence metadata and history</h2>
      <Link to="/money">Return to Money</Link>
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
              "contentSha256",
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
  return (
    <section aria-label={`${tab} records`}>
      <MoneyScope />
      {tab === "expenses" && <ExpenseFilters />}
      {tab === "deposits" && <DepositFilters />}
      {tab === "checks" && <CheckFilters />}
      {tab === "reports" && <OwnerReportFilters />}
      {tab === "receipts" && (
        <form
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
            setParams(next);
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
          <button>Apply receipt filters</button>
        </form>
      )}
      {tab === "rent" && (
        <form
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
            setParams(next);
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
          <button>Apply rent filters</button>
        </form>
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
      {result.data?.items.map((value) => {
        const item = record(value),
          id = scalar(item.id);
        return (
          <article key={id}>
            <Link to={moneyRecordUrl(kinds[tab], id)}>
              {scalar(
                item.displayName ?? item.payeeName ?? item.ownerDisplayNameSnapshot,
                `${tab} record`,
              )}{" "}
              · {scalar(item.dueOn ?? item.paidOn ?? item.receivedOn ?? item.checkDatedOn)} ·{" "}
              {scalar(item.status ?? item.lifecycleStatus ?? item.settlementStatus, "recorded")}
            </Link>
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
                          ? `Party ${scalar(item.paidByPartyId)}`
                          : "Local operator",
                      evidence: Array.isArray(item.activeEvidence) ? item.activeEvidence.length : 0,
                    }
                  : item
              }
              labels={
                tab === "rent"
                  ? {
                      expectedAmountMinor: "Expected",
                      receivedAmountMinor: "Money received",
                      outstandingAmountMinor: "Still due",
                      timelinessStatus: "Needs attention",
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
              <p>
                Due date: {scalar(item.dueOn)} · Covered period: {scalar(item.periodStartsOn)} –{" "}
                {scalar(item.periodEndsOn)}.{" "}
                <Link to={moneyRecordUrl("expectation", id)}>
                  Review amounts and receipt allocations
                </Link>
              </p>
            )}
          </article>
        );
      })}
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
  return (
    <>
      {["propertyId", "leaseId", "ownerId"].map(
        (key) =>
          params.get(key) && (
            <p key={key}>
              {key}: {params.get(key)}{" "}
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
