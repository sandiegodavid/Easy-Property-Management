import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { useId } from "react";
import { api } from "@epm/contracts";
import { record, scalar } from "@epm/contracts/workflows";
import { useWorkspace } from "../app/workspace-gate";
import { Facts, readResult } from "./reads";
import { InstantFilter } from "../shared/instant-filter";

export function MaintenanceContext({
  formKey,
  values,
  source,
}: {
  formKey: string;
  values: Record<string, unknown>;
  source: Record<string, unknown>;
}) {
  const { scope } = useWorkspace();
  const propertyId = scalar(source.propertyId ?? values.propertyId, "");
  const property = useQuery({
    queryKey: scope.key("maintenance-property-clock", propertyId),
    enabled: !!propertyId,
    queryFn: async ({ signal }) =>
      readResult(
        await api.GET("/api/properties/{property_id}", {
          signal,
          params: { path: { property_id: propertyId } },
        }),
      ),
  });
  if (formKey === "maintenance.issue.patch")
    return (
      <div className="record-detail-note" role="note">
        {property.data && <p>{property.data.displayName}</p>}
        <p>
          Editing does not move or resolve the issue. Reporter corrections require a reason. Urgent
          priority does not contact emergency services.
        </p>
        {property.error && (
          <p role="alert">Property details are unavailable. The issue can still be reviewed.</p>
        )}
      </div>
    );
  if (formKey === "maintenance.issue.create")
    return (
      <div className="maintenance-create-note" role="note" aria-label="Reporting guidance">
        {property.data && (
          <p>
            {property.data.displayName} · {property.data.timeZone}
          </p>
        )}
        {property.error && (
          <p role="alert">
            Property details are unavailable. Check your property selection before saving.
          </p>
        )}
        <p>
          The time is recorded automatically when you save a new issue. Urgent priority records the
          issue; it does not contact emergency services.
        </p>
      </div>
    );
  return (
    <section aria-label="Maintenance command review">
      {property.data && (
        <p>
          <strong>{property.data.displayName}</strong> · {property.data.timeZone}
        </p>
      )}
      <details>
        <summary>About this action</summary>
        {property.error && (
          <p role="alert">
            Property context unavailable. The server still validates source membership and time
            zone.
          </p>
        )}
        <p>
          Appointment times use the selected time zone. Saved times are displayed in your browser’s
          local time. The selected home, unit or suite must belong to the property; editing an issue
          cannot move it to another property.
        </p>
        <Facts
          value={source}
          fields={["status", "revision", "reportedTimezone", "resolutionSummary"]}
        />
        <p>
          Issue status, appointment completion, reported work and operator-verified repair are
          separate facts. Resolving requires explicit confirmation and a summary; finish or cancel
          scheduled appointments first. Urgent classification does not contact emergency services.
        </p>
        {formKey.includes("appointment") && (
          <p>
            Scheduling does not create a calendar event or a mirrored Task. Rescheduling preserves
            the previous times and requires a reason; completing the appointment never resolves the
            issue.
          </p>
        )}
        {formKey.includes("cost.") && (
          <>
            <p>
              Operator estimate and work-reported amounts are non-financial context, not money paid.
              They are never added to Finance totals or summed here; confirm actual spending only in
              Finance.
            </p>
            {values.replacesCostContextId && (
              <Facts
                value={record(
                  (Array.isArray(source.costContexts) ? source.costContexts : []).find(
                    (item) => record(item).id === values.replacesCostContextId,
                  ),
                )}
                fields={["contextKind", "label", "amountMinor", "voidedAt"]}
              />
            )}
          </>
        )}
        {formKey.includes("expense.") && (
          <p>
            Select an existing paid Finance Expense from this Property. Linking stores a
            relationship only, not a copied amount; archiving it does not void, refund or rewrite
            that Expense. One Expense can have only one active issue association.
          </p>
        )}
        {formKey.includes("follow_up") && (
          <p>
            This creates one independently managed Task. Completing it does not verify a repair or
            resolve this issue; issue changes do not complete it automatically.
          </p>
        )}
        <p>
          Descriptions, access instructions, outcomes and reasons are sensitive contextual history.
          Evidence upload is separate: an attachment failure must leave the truthful issue or child
          record saved.
        </p>
      </details>
    </section>
  );
}

export function MaintenanceFilters() {
  const [params] = useSearchParams();
  return (
    <>
      <label>
        Issue category
        <select name="category" defaultValue={params.get("category") ?? ""}>
          <option value="">Any</option>
          {[
            "plumbing",
            "electrical",
            "heating_cooling",
            "appliance",
            "structural",
            "safety_security",
            "pest",
            "exterior_grounds",
            "cleaning",
            "other",
          ].map((value) => (
            <option key={value} value={value}>
              {filterLabel(value)}
            </option>
          ))}
        </select>
      </label>
      <label>
        Issue priority
        <select name="priority" defaultValue={params.get("priority") ?? ""}>
          <option value="">Any</option>
          {["low", "normal", "high", "urgent"].map((value) => (
            <option key={value} value={value}>
              {filterLabel(value)}
            </option>
          ))}
        </select>
      </label>
      {["spaceId", "reporterPartyId"].map((key) => (
        <input key={key} type="hidden" name={key} value={params.get(key) ?? ""} />
      ))}
      {(params.has("spaceId") || params.has("reporterPartyId")) && (
        <p className="maintenance-date-hint">
          Limited to the selected {params.has("spaceId") ? "home, unit or suite" : "reporter"}
          {params.has("spaceId") && params.has("reporterPartyId") ? " and reporter" : ""}. Use Clear
          filters to see other issues.
        </p>
      )}
      <details className="maintenance-more-filters">
        <summary>More filters</summary>
        <div className="maintenance-filter-details">
          <label>
            Reporter role
            <select name="reporterRole" defaultValue={params.get("reporterRole") ?? ""}>
              <option value="">Any</option>
              {["owner", "tenant", "manager", "staff"].map((role) => (
                <option key={role} value={role}>
                  {filterLabel(role)}
                </option>
              ))}
            </select>
          </label>
          <label>
            Reporter subject
            <select
              name="reporterSubjectKind"
              defaultValue={params.get("reporterSubjectKind") ?? ""}
            >
              <option value="">Any</option>
              <option value="party">Named contact</option>
              <option value="local_operator">You</option>
            </select>
          </label>
          {[
            ["hasEvidence", "Issue evidence"],
            ["hasLinkedExpense", "Linked paid Expense"],
            ["hasActiveTask", "Active follow-up Task"],
          ].map(([key, title]) => (
            <label key={key}>
              {title}
              <select name={key} defaultValue={params.get(key) ?? ""}>
                <option value="">Any</option>
                <option value="true">Yes</option>
                <option value="false">No</option>
              </select>
            </label>
          ))}
          {[
            ["reportedFrom", "Recorded from"],
            ["reportedTo", "Recorded through"],
            ["appointmentFrom", "Appointment from"],
            ["appointmentTo", "Appointment through"],
          ].map(([key, title]) => (
            <InstantFilter key={key} name={key} label={title} value={params.get(key) ?? ""} />
          ))}
        </div>
      </details>
      <button className="maintenance-clear-filters" type="reset">
        Clear filters
      </button>
    </>
  );
}

function filterLabel(value: string) {
  return value.replaceAll("_", " ").replace(/^\w/, (letter) => letter.toUpperCase());
}

export function MaintenancePropertyFilter() {
  const { scope } = useWorkspace();
  const [params] = useSearchParams();
  const selected = params.get("propertyId") ?? "";
  const id = useId();
  const property = useQuery({
    queryKey: scope.key("maintenance-filter-property", selected),
    enabled: !!selected,
    queryFn: async ({ signal }) =>
      readResult(
        await api.GET("/api/properties/{property_id}", {
          signal,
          params: { path: { property_id: selected } },
        }),
      ),
  });
  const results = useInfiniteQuery({
    queryKey: scope.key("maintenance-filter-properties"),
    staleTime: 30_000,
    initialPageParam: undefined as string | undefined,
    queryFn: async ({ signal, pageParam }) =>
      readResult(
        await api.GET("/api/operator/properties", {
          signal,
          params: { query: { status: "all", limit: 50, cursor: pageParam } },
        }),
      ),
    getNextPageParam: (page) => page.nextCursor ?? undefined,
  });
  const choices = results.data?.pages.flatMap((page) => page.items) ?? [];
  return (
    <div className="maintenance-property-filter">
      <label htmlFor={id}>Property</label>
      <select id={id} name="propertyId" defaultValue={selected} aria-busy={results.isFetching}>
        <option value="">All properties</option>
        {selected && !choices.some((item) => item.id === selected) && (
          <option value={selected}>{property.data?.displayName ?? "Selected property"}</option>
        )}
        {choices.map((item) => (
          <option key={item.id} value={item.id}>
            {item.displayName}
            {item.status === "archived" ? " · Archived" : ""}
          </option>
        ))}
      </select>
      {results.isPending && <p role="status">Loading properties…</p>}
      {results.error && (
        <p role="alert">
          Properties unavailable.{" "}
          <button type="button" onClick={() => void results.refetch()}>
            Retry properties
          </button>
        </p>
      )}
      {results.hasNextPage && (
        <button
          type="button"
          disabled={results.isFetching}
          onClick={() => void results.fetchNextPage()}
        >
          Load more properties
        </button>
      )}
      {selected && property.isError && <span role="alert">Selected property is unavailable.</span>}
    </div>
  );
}
