import { DynamicFilterForm } from "../shared/dynamic-filter-form";
import { Link, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "@epm/contracts";
import { useWorkspace } from "../app/workspace-gate";
import { readResult } from "./reads";
import { record, scalar } from "@epm/contracts/workflows";
import { MoneyFacts } from "./money-presentation";

export function CheckContext({
  check,
  lease,
}: {
  check?: Record<string, unknown>;
  lease?: Record<string, unknown>;
}) {
  const { scope } = useWorkspace();
  const propertyId = scalar(check?.propertyId ?? lease?.propertyId, "");
  const property = useQuery({
    queryKey: scope.key("check-property-context", propertyId),
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
    <section aria-label="Prepaid check review">
      <h3>Physical check, not received income</h3>
      <p>
        Scheduling records custody only. No receipt or income exists until an explicit deposit.
        Deposit records what happened outside this application; it does not contact a bank.
      </p>
      <p>
        One check covers exactly one complete USD expectation period. The printed date must follow
        the custody date. Eligibility uses the Property local date, not your browser clock.
      </p>
      {property.data && (
        <MoneyFacts value={property.data} fields={["timeZone", "effectiveLocalDate"]} />
      )}
      {property.error && (
        <p role="alert">
          Property clock context unavailable. Eligibility is still rechecked by the server.
        </p>
      )}
      {check && (
        <>
          <MoneyFacts
            value={check}
            fields={[
              "status",
              "depositEligibility",
              "payerPartyId",
              "amountMinor",
              "checkDatedOn",
              "reminderStatus",
              "depositedOn",
              "returnedOn",
              "returnedReason",
              "replacementReason",
            ]}
          />
          <MoneyFacts
            value={record(check.expectation)}
            fields={["periodStartsOn", "periodEndsOn", "dueOn", "amountMinor"]}
          />
          {check.depositEligibility === "not_yet_eligible" && (
            <p>
              Not yet eligible: deposit is unavailable until the Property local date reaches the
              printed date.
            </p>
          )}
          {check.reminderTaskId && (
            <Link to={`/tasks/${scalar(check.reminderTaskId)}`}>Deposit reminder Task</Link>
          )}
          {check.receiptId && (
            <Link to={`/money?record=receipt&id=${scalar(check.receiptId)}`}>
              Correlated rent receipt
            </Link>
          )}
          <p>
            Acknowledging a reminder does not deposit the check. Returning a deposited check voids
            its linked receipt together; voiding a scheduled check creates no income. Replacement
            preserves the original check and reasons.
          </p>
        </>
      )}
      <p>
        Use only a safe masked reference, such as Check •••• 9182. Never enter raw check, account or
        routing numbers or upload a check image.
      </p>
      <p>
        On deposit, leave Existing receipt ID empty to create one receipt and its full allocation,
        or explicitly select a compatible existing check receipt. The server rechecks compatibility
        and duplicate protection; it never adopts a receipt automatically.
      </p>
    </section>
  );
}

export function CheckFilters() {
  const [params, setParams] = useSearchParams();
  return (
    <DynamicFilterForm
      className="directory-filters"
      aria-label="Prepaid check filters"
      onSubmit={(event) => {
        event.preventDefault();
        const data = new FormData(event.currentTarget),
          next = new URLSearchParams(params);
        for (const key of ["status", "eligibility", "spaceId", "payerPartyId", "expectationId"]) {
          const entry = data.get(key);
          const value = typeof entry === "string" ? entry : "";
          if (value) next.set(key, value);
          else next.delete(key);
        }
        next.delete("cursor");
        setParams(next, { replace: true, preventScrollReset: true });
      }}
    >
      <p>
        Scheduled checks are not received rent. Filter each deposit queue explicitly; viewing a
        queue never changes a check.
      </p>
      <label>
        Check lifecycle
        <select name="status" defaultValue={params.get("status") ?? ""}>
          <option value="">Any</option>
          {["scheduled", "deposited", "returned", "voided", "replaced"].map((value) => (
            <option key={value}>{value}</option>
          ))}
        </select>
      </label>
      <label>
        Deposit eligibility
        <select name="eligibility" defaultValue={params.get("eligibility") ?? ""}>
          <option value="">Any</option>
          {["eligible", "not_yet_eligible", "not_applicable"].map((value) => (
            <option key={value} value={value}>
              {value.replaceAll("_", " ")}
            </option>
          ))}
        </select>
      </label>
      {[
        ["spaceId", "Space ID"],
        ["payerPartyId", "Payer"],
        ["expectationId", "Expectation ID"],
      ].map(([key, label]) => (
        <label key={key}>
          {label}
          <input name={key} maxLength={36} defaultValue={params.get(key) ?? ""} />
        </label>
      ))}
    </DynamicFilterForm>
  );
}
