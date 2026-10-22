import { record, scalar } from "@epm/contracts/workflows";
import { useQuery } from "@tanstack/react-query";
import { api } from "@epm/contracts";
import { useWorkspace } from "../app/workspace-gate";
import { SourceWorkflowLink as Link } from "../shared/home-navigation";
import { formatHomeTime } from "../shared/home-time";
import { readResult } from "./reads";
import { MoneyFacts } from "./money-presentation";

export function ExpenseDetail({ item }: { item: Record<string, unknown> }) {
  const { scope } = useWorkspace();
  const payerId = scalar(item.paidByPartyId);
  const payer = useQuery({
    queryKey: scope.key("expense-payer", payerId),
    enabled: !!payerId,
    retry: false,
    queryFn: async ({ signal }) =>
      readResult(
        await api.GET("/api/parties/{party_id}", {
          signal,
          params: { path: { party_id: payerId } },
        }),
      ),
  });
  return (
    <>
      <p className="record-detail-subtitle">
        <Link to={`/properties/${scalar(item.propertyId)}/overview`}>
          {scalar(record(item.property).displayName, "Property")}
        </Link>
        {record(item.space).displayName ? ` · ${scalar(record(item.space).displayName)}` : ""}
      </p>
      <section className="record-detail-panel" aria-label="Expense summary">
        <h3>{scalar(item.description, "Recorded payment")}</h3>
        <MoneyFacts
          value={item}
          fields={["amount", "activeRefundedAmount", "netAmount"]}
          labels={{ amount: "Paid", activeRefundedAmount: "Refunded", netAmount: "Net expense" }}
        />
        <MoneyFacts
          value={{
            ...item,
            category: record(item.category).displayName,
            paidBy:
              item.paidByKind === "local_operator"
                ? "You"
                : (payer.data?.displayName ??
                  (payer.error ? "Payer details unavailable" : "Loading payer…")),
          }}
          fields={[
            "payeeName",
            "paidOn",
            "category",
            "paidBy",
            "lifecycleStatus",
            "reference",
            ...(item.notes ? ["notes"] : []),
            ...(item.voidedAt ? ["voidReason"] : []),
          ]}
          labels={{ payeeName: "Paid to", lifecycleStatus: "Record status" }}
        />
      </section>
      <details className="record-detail-section">
        <summary>Record details</summary>
        <MoneyFacts
          value={{
            ...item,
            createdAt: formatHomeTime(scalar(item.createdAt)),
            updatedAt: formatHomeTime(scalar(item.updatedAt)),
          }}
          fields={["createdAt", "updatedAt"]}
        />
      </details>
    </>
  );
}

export function ExpenseCategoryDetail({ item }: { item: Record<string, unknown> }) {
  return (
    <section className="record-detail-panel" aria-label="Expense category details">
      <p className="record-status-label">
        {item.archivedAt ? "Archived category" : "Active category"}
      </p>
      <p>{scalar(item.description, "No description recorded.")}</p>
      <MoneyFacts value={item} fields={["displayOrder"]} labels={{ displayOrder: "List order" }} />
      <p className="record-detail-note">
        This category groups paid expenses. Editing it does not change recorded amounts.
      </p>
      <details>
        <summary>Record details</summary>
        <MoneyFacts
          value={{
            ...item,
            createdAt: formatHomeTime(scalar(item.createdAt)),
            updatedAt: formatHomeTime(scalar(item.updatedAt)),
            archivedAt: item.archivedAt ? formatHomeTime(scalar(item.archivedAt)) : null,
          }}
          fields={["createdAt", "updatedAt", ...(item.archivedAt ? ["archivedAt"] : [])]}
        />
      </details>
    </section>
  );
}
