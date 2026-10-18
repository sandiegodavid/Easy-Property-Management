import { useQuery } from "@tanstack/react-query";
import { api } from "@epm/contracts";
import { scalar } from "@epm/contracts/workflows";
import { useWorkspace } from "../app/workspace-gate";
import { SourceWorkflowLink as Link } from "../shared/home-navigation";
import { readResult } from "./reads";
import { MoneyFacts } from "./money-presentation";
import { formatHomeTime } from "../shared/home-time";

export function RentExpectationDetail({ item }: { item: Record<string, unknown> }) {
  const { scope } = useWorkspace();
  const propertyId = scalar(item.propertyId, "");
  const displayed = {
    ...item,
    ...Object.fromEntries(
      ["createdAt", "updatedAt", "voidedAt"]
        .filter((key) => item[key])
        .map((key) => [key, formatHomeTime(scalar(item[key]))]),
    ),
  };
  const property = useQuery({
    queryKey: scope.key("expectation-property-context", propertyId),
    enabled: !!propertyId,
    queryFn: async ({ signal }) =>
      readResult(
        await api.GET("/api/properties/{property_id}", {
          signal,
          params: { path: { property_id: propertyId } },
        }),
      ),
  });
  return (
    <>
      {property.data && (
        <p className="record-context-link">
          <Link to={`/properties/${propertyId}/overview`}>{property.data.displayName}</Link>
        </p>
      )}
      {property.error && (
        <p role="status">Property context is unavailable. The rent record is shown below.</p>
      )}
      <section className="record-detail-panel" aria-label="Rent balance">
        <MoneyFacts
          value={displayed}
          fields={["expectedAmountMinor", "receivedAmountMinor", "outstandingAmountMinor"]}
          labels={{
            expectedAmountMinor: "Rent expected",
            receivedAmountMinor: "Paid toward this rent",
            outstandingAmountMinor: "Still due",
          }}
        />
        <MoneyFacts
          value={displayed}
          fields={[
            "settlementStatus",
            "lifecycleStatus",
            "timelinessStatus",
            "dueOn",
            "periodStartsOn",
            "periodEndsOn",
            "voidedAt",
            "voidReason",
          ].filter((key) => displayed[key] != null)}
          labels={{
            settlementStatus: "Payment status",
            lifecycleStatus: "Record status",
            timelinessStatus: "Payment timing",
            dueOn: "Due date",
            periodStartsOn: "Rental period starts",
            periodEndsOn: "Rental period ends",
          }}
        />
      </section>
      <details className="record-detail-section">
        <summary>Calculation and record details</summary>
        <MoneyFacts
          value={displayed}
          fields={[
            "scheduleAnchorOn",
            "isProrated",
            "prorationNumeratorDays",
            "prorationDenominatorDays",
            "responsibilityBoundaryOn",
            "responsibilityOverrideReason",
            "createdAt",
            "updatedAt",
          ].filter((key) => displayed[key] != null)}
        />
        <p className="record-detail-note">
          Payment status reflects recorded allocations. Payment timing uses the property’s local
          date. Late or missed is a record for your review, not a legal determination.
        </p>
      </details>
    </>
  );
}
