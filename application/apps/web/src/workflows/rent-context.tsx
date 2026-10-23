import { useState } from "react";
import { api } from "@epm/contracts";
import type { components } from "@epm/contracts/generated";
import { record, scalar, fieldSchema, type RequestSchema } from "@epm/contracts/workflows";
import { readResult } from "./reads";
import { MoneyFacts } from "./money-presentation";
import { cents } from "./money-presentation";
import { formatUsd } from "../shared/presentation";

type Preview = components["schemas"]["SchedulePreviewResponse"];
function scheduleRequest(values: Record<string, unknown>) {
  return {
    leaseTermId: scalar(values.leaseTermId, ""),
    throughOn: scalar(values.throughOn, ""),
    scheduleAnchorOn: values.scheduleAnchorOn ? scalar(values.scheduleAnchorOn) : undefined,
    responsibilityEndsOnOverride: values.responsibilityEndsOnOverride
      ? scalar(values.responsibilityEndsOnOverride)
      : undefined,
    overrideReason: values.overrideReason ? scalar(values.overrideReason) : undefined,
    overrideConfirmed: values.overrideConfirmed === true,
  };
}
export function scheduleKey(values: Record<string, unknown>) {
  return JSON.stringify([values.expectedRevision, scheduleRequest(values)]);
}
export function RentScheduleContext({
  leaseId,
  lease,
  values,
  locked,
  onChange,
  onConfirm,
}: {
  leaseId: string;
  lease: Record<string, unknown>;
  values: Record<string, unknown>;
  locked: boolean;
  onChange: (values: Record<string, unknown>) => void;
  onConfirm: (key: string | undefined) => void;
}) {
  const [preview, setPreview] = useState<{ key: string; data: Preview }>();
  const [error, setError] = useState<string>();
  const [loading, setLoading] = useState(false);
  const [confirmed, setConfirmed] = useState<string>();
  const key = scheduleKey(values);
  const current = preview?.key === key ? preview.data : undefined;
  const term = (Array.isArray(lease.terms) ? lease.terms : [])
    .map(record)
    .find((term) => term.id === values.leaseTermId);
  let suggestion = term ? scalar(term.effectiveOn) : undefined;
  if (term?.paymentFrequency === "monthly" && suggestion) {
    const [year, month] = suggestion.split("-").map(Number);
    let anchor = new Date(
      Date.UTC(
        year,
        month - 1,
        Math.min(Number(term.paymentDueDay), new Date(Date.UTC(year, month, 0)).getUTCDate()),
      ),
    );
    if (anchor.toISOString().slice(0, 10) < suggestion)
      anchor = new Date(
        Date.UTC(
          year,
          month,
          Math.min(Number(term.paymentDueDay), new Date(Date.UTC(year, month + 1, 0)).getUTCDate()),
        ),
      );
    suggestion = anchor.toISOString().slice(0, 10);
  }
  return (
    <section aria-label="Rent schedule preview">
      <h3>Review the rent schedule</h3>
      {term && (
        <MoneyFacts
          value={term}
          fields={["effectiveOn", "endsOn", "baseRentMinor", "paymentFrequency", "paymentDueDay"]}
        />
      )}
      {suggestion && (
        <p>
          Suggested recurrence anchor: {suggestion}{" "}
          <button
            type="button"
            disabled={locked}
            onClick={() => onChange({ ...values, scheduleAnchorOn: suggestion })}
          >
            Use suggested anchor
          </button>
        </p>
      )}
      <p>
        A responsibility override changes the covered boundary. It requires its own confirmation and
        reason.
      </p>
      <button
        type="button"
        disabled={locked || loading || !values.leaseTermId || !values.throughOn}
        onClick={() => {
          void (async () => {
            setLoading(true);
            setError(undefined);
            onConfirm(undefined);
            setConfirmed(undefined);
            try {
              const data = readResult(
                await api.POST("/api/leases/{lease_id}/rent-expectations/preview", {
                  params: { path: { lease_id: leaseId } },
                  body: scheduleRequest(values),
                }),
              );
              if (data.rentLedgerRevision !== values.expectedRevision)
                throw new Error(
                  "The rent ledger changed. Review the current source before confirming.",
                );
              setPreview({ key, data });
            } catch (error) {
              setError(error instanceof Error ? error.message : "Schedule preview unavailable.");
            } finally {
              setLoading(false);
            }
          })();
        }}
      >
        Preview rent schedule
      </button>
      {loading && <p role="status">Loading exact schedule…</p>}
      {error && <p role="alert">{error}</p>}
      {!current && <p>Preview and confirm the current inputs before synchronizing.</p>}
      {current && (
        <>
          <MoneyFacts
            value={current}
            fields={[
              "timeZone",
              "termStartsOn",
              "termEndsOn",
              "responsibilityEndsOn",
              "actualMoveOutOn",
              "scheduleAnchorOn",
            ]}
          />
          <p>{current.items.length} new expectations. Existing snapshots remain retained.</p>
          {[...current.existingItems, ...current.items].map((item, index) => (
            <article key={index}>
              <p>
                {index < current.existingItems.length ? "Retained snapshot" : "New expectation"}
              </p>
              <MoneyFacts
                value={item}
                fields={[
                  "lifecycleStatus",
                  "periodStartsOn",
                  "periodEndsOn",
                  "dueOn",
                  "expectedAmountMinor",
                  "responsibilityBoundaryOn",
                ]}
              />
              <p>
                {item.isProrated
                  ? `Prorated: ${item.prorationNumeratorDays}/${item.prorationDenominatorDays} covered days; rounded half up.`
                  : "Full period"}
              </p>
            </article>
          ))}
          <label>
            <input
              type="checkbox"
              disabled={locked}
              checked={confirmed === key}
              onChange={(event) => {
                setConfirmed(event.target.checked ? key : undefined);
                onConfirm(event.target.checked ? key : undefined);
              }}
            />
            I confirm this anchor and every previewed period
          </label>
        </>
      )}
    </section>
  );
}

function integer(value: unknown): bigint | undefined {
  return typeof value === "number" && Number.isSafeInteger(value) ? BigInt(value) : undefined;
}
export function receiptBalance(values: Record<string, unknown>) {
  const amount = integer(values.amountMinor);
  const entries = Array.isArray(values.allocations) ? values.allocations.map(record) : [];
  const amounts = entries.map((entry) => integer(entry.amountMinor));
  const allocated = amounts.every((amount) => amount !== undefined)
    ? amounts.reduce<bigint>((sum, amount) => sum + amount, 0n)
    : undefined;
  return {
    amount,
    allocated,
    remaining: amount === undefined || allocated === undefined ? undefined : amount - allocated,
  };
}
export function ReceiptAllocationContext({ values }: { values: Record<string, unknown> }) {
  const totals = receiptBalance(values);
  return (
    <section aria-label="Receipt allocation totals" aria-live="polite">
      <h3>Receipt allocation totals</h3>
      <dl>
        {(
          [
            ["Receipt total", totals.amount],
            ["Allocated total", totals.allocated],
            ["Remaining balance", totals.remaining],
          ] as const
        ).map(([label, value]) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd>
              {value === undefined
                ? "Enter valid integer cents"
                : formatUsd(cents(value.toString()))}
            </dd>
          </div>
        ))}
      </dl>
      <p>
        All money must be allocated to 1–100 open expectations from this Lease. An omitted recipient
        means the local operator; a Party recipient must use an existing shared identity.
      </p>
    </section>
  );
}

export function paymentMethodProblem(values: Record<string, unknown>, schema: RequestSchema) {
  if (!values.paymentMethodKind) return "Select the actual method of a payment already received.";
  const note = scalar(values.otherPaymentMethodNote, "").trim();
  if (values.paymentMethodKind === "other" && (!note || note.length > 200))
    return "Other requires a 1–200 character explanation of the actual method.";
  if (values.paymentMethodKind !== "other" && note)
    return "An Other explanation belongs only to the Other method.";
  const reference = scalar(values.maskedReference, "").trim();
  const pattern = fieldSchema(schema.properties?.maskedReference ?? {}).pattern;
  if (reference && (reference.length > 80 || !pattern || !new RegExp(pattern).test(reference)))
    return "Use a safe masked reference, such as Check •••• 9182; never enter raw account, routing or card numbers.";
  return undefined;
}

export function PaymentMethodReview({
  values,
  suggestion,
  replacement,
}: {
  values: Record<string, unknown>;
  suggestion: Record<string, unknown> | undefined;
  replacement: boolean;
}) {
  return (
    <section aria-label="Actual payment method review">
      <h3>How was this rent actually received?</h3>
      <p>
        This records a payment already received. It does not collect, initiate, schedule or
        authorize a payment.
      </p>
      {suggestion?.paymentMethodKind ? (
        <>
          <p>
            {replacement
              ? "Replacement starts with the voided receipt's method."
              : "Editable suggestion from the latest non-voided receipt."}{" "}
            This is not an expected method or recurring instruction. Review and change it for this
            payment.
          </p>
        </>
      ) : (
        <p>No prior method is suggested. Select the actual method explicitly.</p>
      )}
      <details>
        <summary>Payment method and reference guidance</summary>
        <ul>
          <li>
            <strong>Automatic bank payment:</strong> Choose this for a payment arranged outside the
            app. It does not connect to a bank or authorize a debit.
          </li>
          <li>
            <strong>Method description (optional):</strong> Add a short label to help recognize the
            payment, up to 100 characters.
          </li>
          <li>
            <strong>Payment reference (optional):</strong> Leave it blank if not needed, especially
            for cash. For a reference, use at least two • or * characters to hide the number and
            show no more than its last four digits—for example, <strong>Check •••• 9182</strong>.
            Any label before the masked number must use English letters and spaces only.
          </li>
          <li>
            <strong>Changing the method:</strong> Clears the previous description, reference and
            Other explanation. Add new details only if needed for this payment.
          </li>
        </ul>
        <p>
          <strong>Keep sensitive details out:</strong> Never enter full bank account, card or
          routing numbers, passwords, access tokens or payment-service credentials.
        </p>
      </details>
      {values.paymentMethodKind === "other" && (
        <p>
          Explain Other in the required 1–200 character note; it is retained with this receipt only.
        </p>
      )}
    </section>
  );
}
