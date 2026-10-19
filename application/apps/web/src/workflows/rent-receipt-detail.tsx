import { useQuery } from "@tanstack/react-query";
import { api } from "@epm/contracts";
import { record, scalar } from "@epm/contracts/workflows";
import { useWorkspace } from "../app/workspace-gate";
import { SourceWorkflowLink as Link } from "../shared/home-navigation";
import { formatHomeTime } from "../shared/home-time";
import { cents, MoneyFacts } from "./money-presentation";
import { readResult } from "./reads";

export function RentReceiptDetail({ item }: { item: Record<string, unknown> }) {
  const { scope } = useWorkspace();
  const leaseId = scalar(item.leaseId, "");
  const receiverId = scalar(item.receivedByPartyId, "");
  const context = useQuery({
    queryKey: scope.key("money-property-contexts", [], [leaseId]),
    enabled: !!leaseId,
    retry: false,
    queryFn: async ({ signal }) =>
      readResult(
        await api.GET("/api/money/property-contexts", {
          signal,
          params: { query: { leaseIds: [leaseId] } },
        }),
      ),
  });
  const receiver = useQuery({
    queryKey: scope.key("receipt-receiver", receiverId),
    enabled: !!receiverId,
    retry: false,
    queryFn: async ({ signal }) =>
      readResult(
        await api.GET("/api/parties/{party_id}", {
          signal,
          params: { path: { party_id: receiverId } },
        }),
      ),
  });
  const propertyId = context.data?.leaseProperties[leaseId];
  const allocations = Array.isArray(item.allocations) ? item.allocations.map(record) : [];
  return (
    <>
      {propertyId && (
        <p className="record-context-link">
          <Link to={`/properties/${propertyId}/overview`}>
            {context.data?.propertyNames[propertyId] ?? "View property"}
          </Link>
        </p>
      )}
      {context.error && (
        <p role="status">Property context is unavailable. The payment record is shown below.</p>
      )}
      <section className="record-detail-panel" aria-label="Payment summary">
        <MoneyFacts
          value={{ ...item, receiptStatus: item.voidedAt ? "Voided" : "Recorded" }}
          fields={[
            "amountMinor",
            "receivedOn",
            "receiptStatus",
            "paymentMethodKind",
            "paymentMethodLabel",
            "maskedReference",
            "otherPaymentMethodNote",
          ].filter((key) => key === "receiptStatus" || item[key] != null)}
          labels={{
            amountMinor: "Amount received",
            receivedOn: "Date received",
            receiptStatus: "Status",
            paymentMethodKind: "Payment method",
            paymentMethodLabel: "Method details",
            maskedReference: "Payment reference",
            otherPaymentMethodNote: "Payment method note",
          }}
        />
        {!!item.notes && <p className="receipt-notes">{scalar(item.notes)}</p>}
        {!!item.voidedAt && (
          <p className="record-detail-note">
            <strong>This payment was voided.</strong> It no longer counts toward received rent.{" "}
            {item.voidReason ? `Reason: ${scalar(item.voidReason)}` : ""}
          </p>
        )}
      </section>
      <section className="record-detail-section" aria-label="Applied to rent">
        <h3>Applied to rent</h3>
        <p>
          {item.voidedAt
            ? "Original allocations are retained below for history; they no longer reduce the rent balance."
            : "This payment was applied to the following rent periods."}
        </p>
        {allocations.length ? (
          <div className="receipt-allocation-scroll">
            <table className="receipt-allocation-table">
              <caption>{item.voidedAt ? "Original rent allocations" : "Rent allocations"}</caption>
              <thead>
                <tr>
                  <th scope="col">Rental period</th>
                  <th scope="col">Due date</th>
                  <th scope="col">{item.voidedAt ? "Originally applied" : "Amount applied"}</th>
                </tr>
              </thead>
              <tbody>
                {allocations.map((allocation) => (
                  <tr key={scalar(allocation.id)}>
                    <th scope="row">
                      <Link to={`/money?record=expectation&id=${scalar(allocation.expectationId)}`}>
                        {scalar(allocation.expectationPeriodStartsOn)} –{" "}
                        {scalar(allocation.expectationPeriodEndsOn)}
                      </Link>
                    </th>
                    <td>{scalar(allocation.expectationDueOn)}</td>
                    <td>
                      {typeof allocation.amountMinor === "number"
                        ? `USD ${cents(allocation.amountMinor)}`
                        : "Amount unavailable"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p>No rent allocations recorded.</p>
        )}
      </section>
      {!!item.replacesReceiptId && (
        <p>
          <Link to={`/money?record=receipt&id=${scalar(item.replacesReceiptId)}`}>
            View the original voided payment
          </Link>
        </p>
      )}
      <details className="record-detail-section">
        <summary>Record details</summary>
        <MoneyFacts
          value={{
            createdAt: item.createdAt ? formatHomeTime(scalar(item.createdAt)) : null,
            voidedAt: item.voidedAt ? formatHomeTime(scalar(item.voidedAt)) : null,
            receivedBy: receiverId
              ? (receiver.data?.displayName ??
                (receiver.error ? "Recipient details unavailable" : "Loading recipient…"))
              : null,
          }}
          fields={[
            "createdAt",
            ...(item.voidedAt ? ["voidedAt"] : []),
            ...(receiverId ? ["receivedBy"] : []),
          ]}
          labels={{ createdAt: "Recorded", voidedAt: "Voided", receivedBy: "Received by" }}
        />
      </details>
    </>
  );
}
