import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { useEffect, useState } from "react";
import { api } from "@epm/contracts";
import { record, scalar } from "@epm/contracts/workflows";
import { useWorkspace } from "../app/workspace-gate";
import { Facts, readResult } from "./reads";

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
          Editing these details does not move the issue, change its reporter or resolve it. Urgent
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
          Reported times are checked in the property’s time zone. Urgent priority records the issue;
          it does not contact emergency services.
        </p>
      </div>
    );
  return (
    <section aria-label="Maintenance command review">
      <h3>Review the physical issue and independent records</h3>
      {property.data && (
        <Facts value={property.data} fields={["displayName", "timeZone", "effectiveLocalDate"]} />
      )}
      {property.error && (
        <p role="alert">
          Property context unavailable. The server still validates source membership and time zone.
        </p>
      )}
      <p>
        Reported and appointment instants must include an offset. The Property IANA zone controls
        local presentation, not your browser clock. Space selection must belong to that Property;
        Property and Space cannot be moved by editing an issue.
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
          Scheduling does not create a calendar event or a mirrored Task. Rescheduling preserves the
          previous times and requires a reason; completing the appointment never resolves the issue.
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
          Select an existing paid Finance Expense from this Property. Linking stores a relationship
          only, not a copied amount; archiving it does not void, refund or rewrite that Expense. One
          Expense can have only one active issue association.
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
            ["reportedFrom", "Reported from"],
            ["reportedTo", "Reported through"],
            ["appointmentFrom", "Appointment from"],
            ["appointmentTo", "Appointment through"],
          ].map(([key, title]) => (
            <label key={key}>
              {title}
              <input
                name={key}
                maxLength={40}
                placeholder="2026-10-13T12:00:00-07:00"
                defaultValue={params.get(key) ?? ""}
              />
            </label>
          ))}
          <p className="maintenance-date-hint">
            Dates and times must include a time-zone offset, for example 2026-10-18T09:00:00-07:00.
          </p>
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
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  useEffect(() => {
    const timer = setTimeout(() => setQuery(search.trim()), 300);
    return () => clearTimeout(timer);
  }, [search]);
  const [choice, setChoice] = useState({ id: selected, label: "" });
  const [looking, setLooking] = useState(false);
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
  const results = useQuery({
    queryKey: scope.key("maintenance-property-search", query),
    enabled: looking && query.length >= 2 && query === search.trim(),
    queryFn: async ({ signal }) =>
      readResult(
        await api.GET("/api/operator/search", {
          signal,
          params: { query: { q: query, group: "properties", limit: 10 } },
        }),
      ),
  });
  return (
    <div className="maintenance-property-filter">
      <label htmlFor="maintenance-property-search">Property</label>
      <input type="hidden" name="propertyId" value={choice.id} />
      <input
        id="maintenance-property-search"
        type="search"
        placeholder="Find a property by name"
        autoComplete="off"
        value={looking ? search : choice.label || property.data?.displayName || ""}
        onChange={(event) => {
          event.stopPropagation();
          setSearch(event.target.value);
          setLooking(true);
        }}
      />
      {looking && (
        <div className="maintenance-property-results">
          {search.trim().length < 2 && <p>Enter at least 2 characters.</p>}
          {results.isFetching && search.trim().length >= 2 && (
            <p role="status">Finding properties…</p>
          )}
          {results.error && <p role="alert">Property search unavailable. Try another search.</p>}
          {query === search.trim() &&
            query.length >= 2 &&
            results.data?.groups.properties?.items?.map((item) => (
              <button
                type="button"
                key={item.sourceId}
                onClick={(event) => {
                  const form = event.currentTarget.form;
                  setChoice({ id: item.sourceId, label: item.label });
                  setLooking(false);
                  requestAnimationFrame(() => form?.requestSubmit());
                }}
              >
                {item.label}
              </button>
            ))}
          {query === search.trim() &&
            query.length >= 2 &&
            results.data?.groups.properties?.items?.length === 0 && <p>No matching properties.</p>}
        </div>
      )}
      {selected && property.isError && <span role="alert">Selected property is unavailable.</span>}
    </div>
  );
}
