import { record, scalar } from "@epm/contracts/workflows";
import { SourceWorkflowLink } from "../shared/home-navigation";
import { formatDate, formatUsd } from "../shared/presentation";
import { cents, MoneyFacts } from "./money-presentation";

/** Financial effects are frozen in the owning command receipt at commit. */
export function SavedRentReceipt({ value, leaseId }: { value: unknown; leaseId: string }) {
  const receipt = record(value);
  const outcomes = Array.isArray(receipt.periodOutcomes) ? receipt.periodOutcomes.map(record) : [];
  return (
    <>
      <MoneyFacts
        value={receipt}
        fields={[
          "amountMinor",
          "receivedOn",
          "paymentMethodKind",
          "paymentMethodLabel",
          "maskedReference",
          "notes",
        ]}
        labels={{
          amountMinor: "Amount received",
          receivedOn: "Date received",
          paymentMethodKind: "Payment method",
          paymentMethodLabel: "Method details",
          maskedReference: "Payment reference",
        }}
      />
      <section className="saved-item-section" aria-label="Rent after this payment">
        <h3>Rent after this payment</h3>
        {outcomes.map((period) => (
          <p key={scalar(period.expectationId)}>
            <strong>
              {formatDate(scalar(period.periodStartsOn))} –{" "}
              {formatDate(scalar(period.periodEndsOn))} rent:
            </strong>{" "}
            {period.outstandingAmountMinor === 0
              ? "Paid in full"
              : `Still due ${formatUsd(cents(scalar(period.outstandingAmountMinor)))}`}
          </p>
        ))}
      </section>
      <SourceWorkflowLink
        className="button-link"
        to={`/money?workflow=finance.rent_receipt.create&target=${leaseId}`}
      >
        Record another payment
      </SourceWorkflowLink>
    </>
  );
}
