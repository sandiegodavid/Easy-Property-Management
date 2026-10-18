import { DynamicFilterForm } from "../shared/dynamic-filter-form";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "@epm/contracts";
import { record, scalar, workflows } from "@epm/contracts/workflows";
import { useWorkspace } from "../app/workspace-gate";
import { readResult } from "./reads";
import { cents, MoneyFacts } from "./money-presentation";
import { moneyRecordUrl } from "./money-records";
import { ParentBackLink } from "../shared/home-navigation";
import { CommandLoader } from "./command";

function minor(value: unknown) {
  const text = scalar(value, "");
  if (!/^(?:0|[1-9][0-9]{0,7})\.[0-9]{2}$/.test(text)) return undefined;
  return BigInt(text.replace(".", ""));
}
const calculatorFields = ["calculatorPrincipal", "annualRateBasisPoints", "startsOn", "endsOn"];
export function interestPreview(values: Record<string, unknown>) {
  const principal = minor(values.calculatorPrincipal),
    rate = Number(values.annualRateBasisPoints);
  const startText = scalar(values.startsOn, ""),
    endText = scalar(values.endsOn, "");
  if (![startText, endText].every((value) => /^\d{4}-\d{2}-\d{2}$/.test(value))) return undefined;
  const start = Date.parse(`${startText}T00:00:00Z`),
    end = Date.parse(`${endText}T00:00:00Z`);
  if (
    !Number.isFinite(start) ||
    !Number.isFinite(end) ||
    new Date(start).toISOString().slice(0, 10) !== startText ||
    new Date(end).toISOString().slice(0, 10) !== endText
  )
    return undefined;
  const days = (end - start) / 86_400_000;
  if (
    !principal ||
    !Number.isInteger(rate) ||
    rate < 1 ||
    rate > 100_000 ||
    days < 1 ||
    days > 36_600
  )
    return undefined;
  const denominator = 10_000n * 365n;
  const rounded = (principal * BigInt(rate) * BigInt(days) + denominator / 2n) / denominator;
  return { days, amount: cents(rounded), overflow: rounded > 9_999_999_999n };
}
export function interestReviewKey(values: Record<string, unknown>) {
  return JSON.stringify([
    values.expectedRevision,
    ...["kind", ...calculatorFields, "amount", "overrideReason"].map((key) => values[key]),
  ]);
}
export function creditReady(values: Record<string, unknown>, confirmed: string | undefined) {
  if (!calculatorFields.some((field) => values[field] !== undefined && values[field] !== ""))
    return !values.overrideReason;
  const preview = interestPreview(values);
  return (
    values.kind === "interest" &&
    !!preview &&
    !preview.overflow &&
    confirmed === interestReviewKey(values) &&
    (minor(values.amount) !== minor(preview.amount)
      ? !!scalar(values.overrideReason, "").trim()
      : !values.overrideReason)
  );
}
export function InterestCreditReview({
  values,
  locked,
  onChange,
  onConfirm,
  confirmed,
}: {
  values: Record<string, unknown>;
  locked: boolean;
  onChange: (values: Record<string, unknown>) => void;
  onConfirm: (key: string) => void;
  confirmed: string | undefined;
}) {
  const preview = interestPreview(values);
  return (
    <section aria-label="Simple interest review">
      <h3>Review simple interest</h3>
      <p>
        Optional convenience only, not a statutory rate or legal determination. Principal × annual
        rate × days ÷ 365; inclusive start, exclusive end; rounded once, half-up, to cents.
      </p>
      {preview ? (
        <>
          <p>
            {preview.days} days · Calculated interest: USD {preview.amount}
          </p>
          <p>
            Principal: USD {scalar(values.calculatorPrincipal)} · Annual rate:{" "}
            {scalar(values.annualRateBasisPoints)} basis points · {scalar(values.startsOn)} to{" "}
            {scalar(values.endsOn)}
          </p>
          {preview.overflow ? (
            <p role="alert">Calculation exceeds the permitted credit amount.</p>
          ) : (
            <>
              <button
                type="button"
                disabled={locked || preview.amount === "0.00"}
                onClick={() =>
                  onChange({ ...values, amount: preview.amount, overrideReason: undefined })
                }
              >
                Use calculated interest
              </button>
              {minor(values.amount) !== minor(preview.amount) && (
                <p role="alert">
                  Applied credit differs from the calculation. Enter an override reason and confirm
                  the review.
                </p>
              )}
              <button
                type="button"
                disabled={
                  locked ||
                  !minor(values.amount) ||
                  (minor(values.amount) !== minor(preview.amount) &&
                    !scalar(values.overrideReason, "").trim())
                }
                onClick={() => onConfirm(interestReviewKey(values))}
              >
                Confirm interest calculation and applied credit
              </button>
              {confirmed === interestReviewKey(values) && (
                <p>Interest calculation reviewed. Changes require confirmation again.</p>
              )}
            </>
          )}
        </>
      ) : (
        <p>
          Enter positive principal, 1–100,000 integer basis points and a valid period of 1–36,600
          days to calculate.
        </p>
      )}
    </section>
  );
}

export function depositDuplicates(
  formKey: string,
  values: Record<string, unknown>,
  children: Record<string, unknown>[],
) {
  const receipt = formKey === "finance.deposit_receipt.create",
    refund = formKey === "finance.deposit_refund.create";
  if (!receipt && !refund) return [];
  if (!minor(values.amount) || !values[receipt ? "receivedOn" : "paidOn"]) return [];
  return children
    .filter(
      (item) =>
        !item.voidedAt &&
        item[receipt ? "receivedOn" : "paidOn"] === values[receipt ? "receivedOn" : "paidOn"] &&
        item.amount === values.amount &&
        (item[receipt ? "receivedFromPartyId" : "recipientPartyId"] ?? null) ===
          (values[receipt ? "receivedFromPartyId" : "recipientPartyId"] || null),
    )
    .slice(0, 10);
}

export function DepositContext({
  formKey,
  account,
  selected,
  children,
  values,
  locked,
  onChange,
}: {
  formKey: string;
  account: Record<string, unknown>;
  selected: Record<string, unknown> | undefined;
  children: Record<string, unknown>[];
  values: Record<string, unknown>;
  locked: boolean;
  onChange: (values: Record<string, unknown>) => void;
}) {
  const { scope } = useWorkspace();
  const [search, setSearch] = useState(""),
    [query, setQuery] = useState<string>();
  const [cursor, setCursor] = useState<string>();
  const historical =
    values.historicalPartyConfirmed === true && !!scalar(values.historicalPartyReason, "").trim();
  const parties = useQuery({
    queryKey: scope.key("deposit-party-selection", query, historical, cursor),
    enabled: query !== undefined,
    queryFn: async ({ signal }) =>
      readResult(
        await api.GET("/api/parties/selection", {
          signal,
          params: {
            query: { search: query!, includeArchived: historical, limit: 10, cursor },
          },
        }),
      ),
  });
  const propertyId = scalar(account.propertyId, "");
  const property = useQuery({
    queryKey: scope.key("deposit-property-context", propertyId),
    enabled: !!propertyId,
    queryFn: async ({ signal }) =>
      readResult(
        await api.GET("/api/properties/{property_id}", {
          signal,
          params: { path: { property_id: propertyId } },
        }),
      ),
  });
  const candidates = depositDuplicates(formKey, values, children);
  const payerField =
    formKey === "finance.deposit_refund.create" ? "recipientPartyId" : "receivedFromPartyId";
  const partyCommand =
    formKey === "finance.deposit_receipt.create" || formKey === "finance.deposit_refund.create";
  const settlement = selected?.status
    ? selected
    : children.find((item) => item.id === account.settlementId);
  const lines = (key: string) =>
    Array.isArray(settlement?.[key]) ? (settlement[key] as unknown[]).map(record) : [];
  const received = minor(account.activeReceivedAmount) ?? 0n;
  const credits = lines("credits").reduce((sum, item) => sum + (minor(item.amount) ?? 0n), 0n);
  const deductions = lines("deductions").reduce(
    (sum, item) => sum + (minor(item.amount) ?? 0n),
    0n,
  );
  return (
    <section aria-label="Deposit review">
      <h3>Review held deposit and proposed settlement</h3>
      <p>
        Deposits are not rent income. Deductions do not create expenses. Refund recording does not
        send money.
      </p>
      {property.data && (
        <p>
          {property.data.displayName} · Property local time zone: {property.data.timeZone}
        </p>
      )}
      {property.error && <p role="alert">Property context unavailable: {property.error.message}</p>}
      <MoneyFacts
        value={account}
        fields={[
          "agreedAmount",
          "activeReceivedAmount",
          "activeRefundedAmount",
          "varianceAmount",
          "deadlineState",
          "unresolvedBalance",
        ]}
      />
      {settlement && (
        <>
          <MoneyFacts
            value={settlement}
            fields={[
              "settlementDueOn",
              "legalRuleReference",
              "reviewNotes",
              "refundDue",
              "unsettledReceiptAmount",
              "sourceWarnings",
              "inspectionWarnings",
            ]}
          />
          {settlement.status === "draft" && (
            <p>
              Proposed arithmetic: USD {cents(received)} receipts + USD {cents(credits)} credits −
              USD {cents(deductions)} deductions = USD {cents(received + credits - deductions)}{" "}
              refund due. Approval rechecks and freezes the exact receipt set and sources.
            </p>
          )}
          <p>
            Draft deductions may lack evidence, but every deduction needs an allowed active source
            before approval. Inspection classifications and rent/expense amounts are evidence, never
            automatic deductions. The recorded deadline is operator-entered, not a legal-compliance
            determination.
          </p>
        </>
      )}
      {partyCommand && (
        <fieldset disabled={locked}>
          <legend>
            {payerField === "recipientPartyId" ? "Refund recipient" : "Deposit payer"} selection
          </legend>
          <label>
            Party search
            <input
              maxLength={240}
              value={search}
              onChange={(event) => setSearch(event.target.value)}
            />
          </label>
          <button
            type="button"
            onClick={() => {
              setQuery(search);
              setCursor(undefined);
            }}
          >
            Search deposit Parties
          </button>
          {parties.error && <p role="alert">Party search unavailable: {parties.error.message}</p>}
          {parties.data?.items.map((item) => (
            <p key={item.id}>
              {item.displayName} {item.archivedAt && "· Archived historical Party"}{" "}
              <button type="button" onClick={() => onChange({ ...values, [payerField]: item.id })}>
                Use Party {item.displayName}
              </button>
              {formKey === "finance.deposit_receipt.create" && (
                <button
                  type="button"
                  onClick={() =>
                    onChange({
                      ...values,
                      receivedByKind: "party",
                      receivedByPartyId: item.id,
                    })
                  }
                >
                  Received by {item.displayName}
                </button>
              )}
            </p>
          ))}
          {parties.data?.nextCursor && (
            <button type="button" onClick={() => setCursor(parties.data?.nextCursor ?? undefined)}>
              Next deposit Party results
            </button>
          )}
          {cursor && (
            <button type="button" onClick={() => setCursor(undefined)}>
              First deposit Party results
            </button>
          )}
          <p>
            Normal search excludes archived Parties. Historical selection requires confirmation and
            a reason; recipient and overage exceptions remain separate operator decisions.
          </p>
        </fieldset>
      )}
      {candidates.length > 0 && (
        <section aria-label="Possible duplicate deposit payments">
          <h3>Review possible duplicate payments</h3>
          {candidates.map((item) => (
            <article key={scalar(item.id)}>
              <MoneyFacts
                value={item}
                fields={["receivedOn", "paidOn", "amount", "receivedFromName", "recipientName"]}
              />
            </article>
          ))}
          <Link to={moneyRecordUrl("deposit", scalar(account.id))}>
            Open existing deposit history
          </Link>{" "}
          <button
            type="button"
            disabled={locked}
            onClick={() => onChange({ ...values, duplicateConfirmed: true })}
          >
            Record separate deposit payment
          </button>
          <p>No automatic merging. Confirm a separate actual payment before saving.</p>
        </section>
      )}
    </section>
  );
}

export function sourceReviewKey(values: Record<string, unknown>) {
  return JSON.stringify([
    values.expectedRevision,
    values.sourceKind,
    values.sourceId,
    values.historicalConfirmed,
    values.historicalReason,
  ]);
}

export function DepositEvidenceArchive() {
  const [params] = useSearchParams();
  const target = params.get("target"),
    accountId = params.get("accountId"),
    settlementId = params.get("settlementId");
  const { scope } = useWorkspace();
  const context = useQuery({
    queryKey: scope.key("deposit-evidence-archive", target, accountId, settlementId),
    enabled: !!target && !!accountId && !!settlementId,
    queryFn: async ({ signal }) => {
      const link = readResult(
        await api.GET("/api/file-links/{link_id}", {
          signal,
          params: { path: { link_id: target! } },
        }),
      );
      const settlement = readResult(
        await api.GET("/api/security-deposit-settlements/{settlement_id}", {
          signal,
          params: { path: { settlement_id: settlementId! } },
        }),
      );
      if (
        settlement.accountId !== accountId ||
        !(
          (link.entityType === "security_deposit_settlement" && link.entityId === settlement.id) ||
          (link.entityType === "security_deposit_deduction" &&
            settlement.deductions.some((item) => item.id === link.entityId))
        )
      )
        throw new Error("Evidence does not belong to this deposit settlement.");
      return link;
    },
  });
  if (!target || !accountId || !settlementId)
    return <p role="alert">Select evidence from its deposit settlement.</p>;
  if (context.isPending) return <p role="status">Loading deposit evidence association…</p>;
  if (context.error) return <p role="alert">{context.error.message}</p>;
  if (context.data.archivedAt && !params.has("resume"))
    return <p>This association is already archived. Its file and history remain retained.</p>;
  return (
    <>
      <ParentBackLink to={moneyRecordUrl("settlement", settlementId)} />
      <p>
        Archive only this evidence association. The file, deposit records and contextual reason
        remain retained.
      </p>
      <CommandLoader
        definition={workflows.find((item) => item.formKey === "file.link.archive")!}
        sourceId={target}
        revision={context.data.revision}
        showParentLink={false}
        returnTo={moneyRecordUrl("settlement", settlementId)}
        reviewSource={async () => {
          const current = readResult(
            await api.GET("/api/file-links/{link_id}", { params: { path: { link_id: target } } }),
          );
          return { revision: current.revision, value: current };
        }}
      />
    </>
  );
}

export function DepositFilters() {
  const [params, setParams] = useSearchParams();
  return (
    <DynamicFilterForm
      className="directory-filters"
      onSubmit={(event) => {
        event.preventDefault();
        const data = new FormData(event.currentTarget),
          next = new URLSearchParams(params);
        for (const key of ["spaceId", "settlementStatus", "deadlineState", "unresolvedBalance"]) {
          const value = data.get(key);
          if (typeof value === "string" && value) next.set(key, value);
          else next.delete(key);
        }
        next.delete("cursor");
        setParams(next, { replace: true, preventScrollReset: true });
      }}
    >
      <label>
        Deposit Space ID
        <input name="spaceId" maxLength={36} defaultValue={params.get("spaceId") ?? ""} />
      </label>
      {[
        ["settlementStatus", "Settlement state", ["draft", "approved", "completed"]],
        ["deadlineState", "Recorded deadline state", ["due", "due_today", "overdue", "complete"]],
        ["unresolvedBalance", "Unresolved deposit balance", ["true", "false"]],
      ].map(([key, label, options]) => (
        <label key={key as string}>
          {label as string}
          <select name={key as string} defaultValue={params.get(key as string) ?? ""}>
            <option value="">Any</option>
            {(options as string[]).map((option) => (
              <option key={option} value={option}>
                {option.replaceAll("_", " ")}
              </option>
            ))}
          </select>
        </label>
      ))}
    </DynamicFilterForm>
  );
}
export function DeductionSourceReview({
  accountId,
  values,
  locked,
  onConfirm,
  confirmed,
}: {
  accountId: string;
  values: Record<string, unknown>;
  locked: boolean;
  onConfirm: (key: string) => void;
  confirmed: string | undefined;
}) {
  const [preview, setPreview] = useState<{
    key: string;
    summary: string;
    active: boolean;
    outstanding: string | null;
  }>();
  const [error, setError] = useState<string>();
  const [loading, setLoading] = useState(false);
  const key = sourceReviewKey(values);
  return (
    <section aria-label="Deduction source review">
      <h3>Review explicitly selected evidence</h3>
      <p>
        An inspection classification, rent balance or paid Expense does not decide a deduction
        amount or legal liability.
      </p>
      <button
        type="button"
        disabled={locked || loading}
        onClick={() => {
          setLoading(true);
          setError(undefined);
          void api
            .GET("/api/security-deposits/{account_id}/deduction-source-preview", {
              params: {
                path: { account_id: accountId },
                query: {
                  sourceKind: values.sourceKind as
                    | "inspection_comparison"
                    | "inspection_observation"
                    | "rent_expectation"
                    | "expense",
                  sourceId: scalar(values.sourceId),
                },
              },
            })
            .then((response) => {
              const result = readResult(response);
              setPreview({
                key,
                summary: result.sourceSummary,
                active: result.active,
                outstanding: result.outstandingAmount,
              });
            })
            .catch((cause: unknown) =>
              setError(cause instanceof Error ? cause.message : "Source review unavailable."),
            )
            .finally(() => setLoading(false));
        }}
      >
        Preview deduction source
      </button>
      {error && <p role="alert">{error}</p>}
      {preview?.key === key && (
        <>
          <p>
            {preview.summary} ·{" "}
            {preview.active
              ? "Active source"
              : "Historical source — confirmation and reason required"}
          </p>
          {preview.outstanding !== null && (
            <p>
              Recorded outstanding rent: USD {preview.outstanding}. The deduction remains
              operator-entered.
            </p>
          )}
          <button
            type="button"
            disabled={
              locked ||
              (!preview.active &&
                !(
                  values.historicalConfirmed === true && scalar(values.historicalReason, "").trim()
                ))
            }
            onClick={() => onConfirm(key)}
          >
            Confirm reviewed deduction source
          </button>
          {confirmed === key && (
            <p>Selected source reviewed. Changed selection requires review again.</p>
          )}
        </>
      )}
    </section>
  );
}
