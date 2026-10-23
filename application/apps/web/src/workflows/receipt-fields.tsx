import { useState } from "react";
import { useInfiniteQuery } from "@tanstack/react-query";
import { api } from "@epm/contracts";
import type { components } from "@epm/contracts/generated";
import { record, scalar, type RequestSchema } from "@epm/contracts/workflows";
import { useWorkspace } from "../app/workspace-gate";
import { formatDate, formatUsd } from "../shared/presentation";
import { Fields, type Choices } from "./fields";
import { cents } from "./money-presentation";
import { readResult } from "./reads";
import { receiptBalance } from "./rent-context";

type Period = components["schemas"]["ExpectationResponse"];
export type ReceiptPeriods = components["schemas"]["ExpectationPageResponse"];

/** Parse dollars exactly; never round extra decimal places or use float multiplication. */
export function dollarCents(text: string): number | undefined {
  if (!/^(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d{0,2})?$/.test(text.trim())) return;
  const [whole, fraction = ""] = text.trim().replaceAll(",", "").split(".");
  const amount = BigInt(whole) * 100n + BigInt(fraction.padEnd(2, "0"));
  return amount <= BigInt(Number.MAX_SAFE_INTEGER) ? Number(amount) : undefined;
}

function Dollars({
  name,
  value,
  onChange,
  disabled,
}: {
  name: string;
  value: unknown;
  onChange: (value: number | string) => void;
  disabled: boolean;
}) {
  const display = typeof value === "number" ? formatUsd(cents(value)).slice(4) : scalar(value);
  // Preserve the typing cursor and trailing decimal until blur. External edits
  // (e.g. Allocate remaining) still replace the displayed value immediately.
  const [editing, setEditing] = useState<{ text: string; value: unknown }>();
  return (
    <label>
      {name}
      <input
        name={name}
        type="text"
        inputMode="decimal"
        required
        maxLength={40}
        disabled={disabled}
        value={editing && editing.value === value ? editing.text : display}
        onChange={(event) => {
          const text = event.target.value;
          if (!/^[0-9,.\s-]*$/.test(text)) return;
          const next = dollarCents(text) ?? text;
          setEditing({ text, value: next });
          onChange(next);
        }}
        onBlur={() => setEditing(undefined)}
      />
    </label>
  );
}

export function receiptPeriodName(period: { periodStartsOn: string; periodEndsOn: string }) {
  return `${formatDate(period.periodStartsOn)} – ${formatDate(period.periodEndsOn)}`;
}

export function receiptProblem(values: Record<string, unknown>) {
  if (
    typeof values.amountMinor !== "number" ||
    !Number.isSafeInteger(values.amountMinor) ||
    values.amountMinor <= 0
  )
    return "Enter a payment amount greater than zero in USD, with no more than two decimal places.";
  const allocations = Array.isArray(values.allocations) ? values.allocations.map(record) : [];
  if (!allocations.length) return "Select at least one rent period in Apply payment to rent.";
  if (
    allocations.some(
      (row) =>
        typeof row.amountMinor !== "number" ||
        !Number.isSafeInteger(row.amountMinor) ||
        row.amountMinor <= 0,
    )
  )
    return "Enter an allocation greater than zero for each selected rent period, with no more than two decimal places.";
  if (receiptBalance(values).remaining !== 0n)
    return "Check Receipt allocation totals: allocate the full payment before recording it.";
}

export function ReceiptFields({
  schema,
  values,
  onChange,
  locked,
  choices,
  leaseId,
  periods,
  selected,
  revision,
}: {
  schema: RequestSchema;
  values: Record<string, unknown>;
  onChange: (values: Record<string, unknown>) => void;
  locked: boolean;
  choices: Choices;
  leaseId: string;
  periods: ReceiptPeriods;
  selected?: Period;
  revision: number;
}) {
  const { scope } = useWorkspace();
  const pages = useInfiniteQuery({
    queryKey: scope.key("receipt-period-choices", leaseId, revision),
    initialPageParam: null as string | null,
    initialData: { pages: [periods], pageParams: [null] },
    staleTime: Infinity,
    queryFn: async ({ pageParam, signal }) =>
      readResult(
        await api.GET("/api/rent-expectations", {
          signal,
          params: { query: { leaseId, pageSize: 100, cursor: pageParam ?? undefined } },
        }),
      ),
    getNextPageParam: (page) => page.nextCursor ?? undefined,
  });
  const all = new Map(
    pages.data.pages.flatMap((page) => page.items).map((period) => [period.id, period]),
  );
  if (selected && !all.has(selected.id)) all.set(selected.id, selected);
  const allocations = Array.isArray(values.allocations) ? values.allocations.map(record) : [];
  const open = [...all.values()]
    .sort((a, b) => a.periodStartsOn.localeCompare(b.periodStartsOn) || a.id.localeCompare(b.id))
    .filter(
      (period) =>
        !period.voidedAt &&
        (period.outstandingAmountMinor > 0 ||
          allocations.some((row) => row.expectationId === period.id)),
    );
  const unknown = allocations.filter((row) => !all.has(scalar(row.expectationId)));
  const totals = receiptBalance(values);
  const remaining = totals.remaining;
  const next =
    remaining !== undefined && remaining > 0n
      ? open.find((period) => {
          const allocation = allocations.find((row) => row.expectationId === period.id);
          return !allocation && allocations.length >= 100
            ? false
            : BigInt(period.outstandingAmountMinor) -
                BigInt(typeof allocation?.amountMinor === "number" ? allocation.amountMinor : 0) >=
                remaining;
        })
      : undefined;
  function allocate(id: string, amount: unknown) {
    onChange({
      ...values,
      allocations: [
        ...allocations.filter((row) => row.expectationId !== id),
        { expectationId: id, amountMinor: amount },
      ],
    });
  }
  function fields(keys: string[]) {
    return (
      <Fields
        schema={{
          ...schema,
          properties: Object.fromEntries(
            keys
              .filter((key) => schema.properties?.[key])
              .map((key) => [key, schema.properties![key]]),
          ),
        }}
        value={values}
        onChange={(next) => onChange(record(next))}
        choices={choices}
        disabled={locked}
      />
    );
  }
  return (
    <div className="tidy-form-sections">
      <section className="tidy-form-section" aria-label="Payment received">
        <h3>Payment received</h3>
        <div className="tidy-form-grid">
          <Dollars
            name="Amount (USD)"
            value={values.amountMinor}
            onChange={(amountMinor) => onChange({ ...values, amountMinor })}
            disabled={locked}
          />
          {fields(["receivedOn", "paymentMethodKind"])}
        </div>
        {values.paymentMethodKind === "other" && fields(["otherPaymentMethodNote"])}
      </section>
      <section className="tidy-form-section" aria-label="Apply payment to rent">
        <h3>Apply payment to rent</h3>
        <p>
          Select the periods covered by this payment. Change an allocation for a partial payment.
        </p>
        <div className="receipt-periods">
          {open.map((period) => {
            const row = allocations.find((row) => row.expectationId === period.id);
            return (
              <div className="receipt-period" key={period.id}>
                <label>
                  <input
                    type="checkbox"
                    checked={!!row}
                    disabled={locked || (!row && allocations.length >= 100)}
                    onChange={(event) => {
                      if (event.target.checked) allocate(period.id, period.outstandingAmountMinor);
                      else
                        onChange({
                          ...values,
                          allocations: allocations.filter(
                            (item) => item.expectationId !== period.id,
                          ),
                        });
                    }}
                  />
                  {receiptPeriodName(period)} — {formatUsd(cents(period.outstandingAmountMinor))}{" "}
                  due
                </label>
                {row && (
                  <Dollars
                    name={`Allocation (USD) for ${receiptPeriodName(period)}`}
                    value={row.amountMinor}
                    disabled={locked}
                    onChange={(amount) => allocate(period.id, amount)}
                  />
                )}
              </div>
            );
          })}
        </div>
        {!open.length && <p>No open rent periods on this page.</p>}
        {unknown.map((row, index) => (
          <div className="receipt-period" key={scalar(row.expectationId)}>
            <p>
              A saved rent period is not on this page. Load more periods or review the current rent
              ledger. Your allocation is preserved.
            </p>
            <Dollars
              name={`Allocation (USD) for saved period ${index + 1}`}
              value={row.amountMinor}
              disabled={locked}
              onChange={(amount) => allocate(scalar(row.expectationId), amount)}
            />
            <button
              type="button"
              disabled={locked}
              onClick={() =>
                onChange({ ...values, allocations: allocations.filter((item) => item !== row) })
              }
            >
              Remove saved period {index + 1}
            </button>
          </div>
        ))}
        {pages.error && (
          <p role="alert">More rent periods could not be loaded. Your entries are unchanged.</p>
        )}
        {pages.hasNextPage && (
          <button
            type="button"
            disabled={locked || pages.isFetchingNextPage}
            onClick={() => void pages.fetchNextPage()}
          >
            Load more rent periods
          </button>
        )}
      </section>
      <section
        className="tidy-form-section"
        aria-label="Receipt allocation totals"
        aria-live="polite"
      >
        <h3>Receipt allocation totals</h3>
        <p>
          {remaining === undefined
            ? "Enter the payment and allocation amounts in USD."
            : remaining === 0n
              ? "Fully allocated"
              : remaining > 0n
                ? `${formatUsd(cents(remaining))} not yet allocated`
                : `Allocations exceed the payment by ${formatUsd(cents(-remaining))}`}
        </p>
        {next && (
          <button
            type="button"
            disabled={locked}
            onClick={() => {
              const row = allocations.find((row) => row.expectationId === next.id);
              allocate(
                next.id,
                Number(remaining) + (typeof row?.amountMinor === "number" ? row.amountMinor : 0),
              );
            }}
          >
            Allocate remaining {formatUsd(cents(remaining!))} to {receiptPeriodName(next)}
          </button>
        )}
      </section>
      <details className="tidy-form-section">
        <summary>Additional details</summary>
        {fields([
          "paymentMethodLabel",
          "maskedReference",
          "receivedByPartyId",
          "notes",
          "duplicateConfirmed",
          "duplicateReason",
        ])}
        <p>
          Use only a masked reference, such as Check •••• 9182. Never enter full bank or card
          details.
        </p>
      </details>
    </div>
  );
}
