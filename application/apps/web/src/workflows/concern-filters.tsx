import { useEffect, useId, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useLocation, useSearchParams } from "react-router-dom";
import { api } from "@epm/contracts";
import { useWorkspace } from "../app/workspace-gate";
import { DynamicFilterForm } from "../shared/dynamic-filter-form";
import { leaseLastCoveredOn } from "../shared/lease-dates";
import { readResult } from "./reads";

function NameFilter({
  name,
  label,
  group,
  selected,
}: {
  name: string;
  label: string;
  group: "properties" | "owners" | "tenants";
  selected: string;
}) {
  const { scope } = useWorkspace();
  const inputId = useId();
  const [choice, setChoice] = useState({ id: selected, label: "" });
  const [text, setText] = useState("");
  const [search, setSearch] = useState("");
  const [looking, setLooking] = useState(false);
  useEffect(() => {
    const timer = setTimeout(() => setSearch(text.trim()), 250);
    return () => clearTimeout(timer);
  }, [text]);
  const current = useQuery({
    queryKey: scope.key("concern-filter-name", group, selected),
    enabled: !!selected,
    queryFn: async ({ signal }) =>
      group === "properties"
        ? readResult(
            await api.GET("/api/properties/{property_id}", {
              signal,
              params: { path: { property_id: selected } },
            }),
          )
        : readResult(
            await api.GET("/api/parties/{party_id}", {
              signal,
              params: { path: { party_id: selected } },
            }),
          ),
  });
  const results = useQuery({
    queryKey: scope.key("concern-filter-search", group, search),
    enabled: looking && search.length >= 2 && search === text.trim(),
    queryFn: async ({ signal }) =>
      readResult(
        await api.GET("/api/operator/search", {
          signal,
          params: { query: { q: search, group, includeArchived: true, limit: 10 } },
        }),
      ),
  });
  return (
    <div className="maintenance-property-filter">
      <label htmlFor={inputId}>{label}</label>
      <input type="hidden" name={name} value={choice.id} />
      <input
        id={inputId}
        type="search"
        maxLength={240}
        autoComplete="off"
        placeholder={`Find ${label.toLowerCase()} by name`}
        value={looking ? text : choice.label || (choice.id ? current.data?.displayName : "") || ""}
        onChange={(event) => {
          event.stopPropagation();
          setText(event.target.value);
          setLooking(!!event.target.value.trim());
          if (!event.target.value.trim() && choice.id) {
            const form = event.currentTarget.form;
            setChoice({ id: "", label: "" });
            requestAnimationFrame(() => form?.requestSubmit());
          }
        }}
      />
      {current.error && <p role="alert">Selected {label.toLowerCase()} details are unavailable.</p>}
      {looking && (
        <div className="maintenance-property-results">
          {text.trim().length < 2 && <p>Enter at least 2 characters.</p>}
          {results.isFetching && <p role="status">Searching…</p>}
          {results.error && <p role="alert">Search unavailable. Try again.</p>}
          {search === text.trim() && search.length >= 2 && results.data && (
            <>
              {results.data.groups[group]?.availability === "unavailable" ? (
                <p role="alert">Search unavailable. Try again.</p>
              ) : (
                <>
                  {results.data.groups[group]?.items?.map((item) => (
                    <button
                      key={item.sourceId}
                      type="button"
                      onClick={(event) => {
                        const form = event.currentTarget.form;
                        setChoice({ id: item.sourceId, label: item.label });
                        setLooking(false);
                        requestAnimationFrame(() => form?.requestSubmit());
                      }}
                    >
                      {item.label}
                      {item.archived ? " · Archived" : ""}
                    </button>
                  ))}
                  {!results.data.groups[group]?.items?.length && <p>No matching names.</p>}
                  {!!results.data.groups[group]?.nextCursor && (
                    <p>Showing 10 matches. Refine the name to narrow the results.</p>
                  )}
                </>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}

export function ConcernFilters() {
  const { scope } = useWorkspace();
  const [params, setParams] = useSearchParams();
  const location = useLocation();
  const propertyId = params.get("propertyId") ?? "";
  const ownerId = params.get("ownerId") ?? "";
  const spaceId = params.get("spaceId") ?? "";
  const leaseId = params.get("leaseId") ?? "";
  const type = params.get("concernType") ?? "";
  const [leasePage, setLeasePage] = useState<{ key: string; cursor?: string }>({ key: "" });
  const contextKey = `${propertyId}:${ownerId}`;
  const cursor = leasePage.key === contextKey ? leasePage.cursor : undefined;
  const property = useQuery({
    queryKey: scope.key("concern-filter-property", propertyId),
    enabled: !!propertyId,
    queryFn: async ({ signal }) =>
      readResult(
        await api.GET("/api/properties/{property_id}", {
          signal,
          params: { path: { property_id: propertyId } },
        }),
      ),
  });
  const showSuite = property.data?.propertyType === "office";
  const showLease = type === "lease" || type === "tenant";
  const leases = useQuery({
    queryKey: scope.key("concern-filter-leases", propertyId, ownerId, cursor),
    retry: false,
    enabled: showLease && !!propertyId,
    queryFn: async ({ signal }) =>
      readResult(
        await api.GET(
          ownerId
            ? "/api/operator/owners/{subject_id}/overview"
            : "/api/operator/properties/{subject_id}/overview",
          {
            signal,
            params: {
              path: { subject_id: ownerId || propertyId },
              query: { section: "leases", relationshipScope: "all", sectionLimit: 25, cursor },
            },
          },
        ),
      ),
  });
  const rawSection = leases.data?.sections.leases;
  const section = rawSection?.kind === "leases" ? rawSection : undefined;
  const periods =
    section?.kind === "leases"
      ? (section.items?.filter(
          (item) => item.propertyId === propertyId && (!spaceId || item.spaceId === spaceId),
        ) ?? [])
      : [];
  const selectedLease = useQuery({
    queryKey: scope.key("concern-filter-selected-lease", leaseId),
    enabled: showLease && !!leaseId,
    queryFn: async ({ signal }) =>
      readResult(
        await api.GET("/api/leases/{lease_id}", {
          signal,
          params: { path: { lease_id: leaseId } },
        }),
      ),
  });
  function periodLabel(item: {
    contractStartsOn: string;
    contractEndsOn: string | null;
    spaceId: string;
    status: string;
  }) {
    return `${item.contractStartsOn} – ${leaseLastCoveredOn(item.contractEndsOn) ?? "Open-ended"} · ${property.data?.spaces.find((rental) => rental.id === item.spaceId)?.displayName ?? "Rental"} · ${item.status}`;
  }
  return (
    <DynamicFilterForm
      className="maintenance-directory-filters"
      aria-label="Owner concern filters"
      onSubmit={(event) => {
        event.preventDefault();
        const next = new URLSearchParams({ tab: "concerns" });
        new FormData(event.currentTarget).forEach((value, key) => {
          if (typeof value === "string" && value) next.set(key, value);
        });
        if (next.get("propertyId") !== params.get("propertyId")) {
          next.delete("spaceId");
          next.delete("leaseId");
          next.delete("tenantPartyId");
        }
        if (next.get("ownerId") !== params.get("ownerId")) {
          next.delete("leaseId");
          next.delete("tenantPartyId");
        }
        if (next.get("spaceId") !== params.get("spaceId")) {
          next.delete("leaseId");
          next.delete("tenantPartyId");
        }
        if (next.get("leaseId") !== params.get("leaseId")) next.delete("tenantPartyId");
        if (next.get("concernType") !== params.get("concernType")) {
          next.delete("leaseId");
          next.delete("tenantPartyId");
        }
        setParams(next, {
          replace: true,
          preventScrollReset: true,
          state: location.state as unknown,
        });
      }}
      onReset={(event) => {
        event.preventDefault();
        setParams(
          { tab: "concerns" },
          { replace: true, preventScrollReset: true, state: location.state as unknown },
        );
      }}
    >
      <NameFilter
        key={`owner:${ownerId}`}
        name="ownerId"
        label="Owner"
        group="owners"
        selected={ownerId}
      />
      <div className="concern-filter-group">
        <NameFilter
          key={`property:${propertyId}`}
          name="propertyId"
          label="Property"
          group="properties"
          selected={propertyId}
        />
        {showSuite && (
          <label>
            Suite
            <select name="spaceId" key={`${propertyId}:${spaceId}`} defaultValue={spaceId}>
              <option value="">All suites</option>
              {property.data?.spaces.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.displayName}
                  {item.status === "archived" ? " · Archived" : ""}
                </option>
              ))}
            </select>
          </label>
        )}
        {property.error && <p role="alert">Property details are unavailable. Try again.</p>}
      </div>
      <div className="concern-filter-group">
        <label>
          Concern type
          <select name="concernType" defaultValue={type}>
            <option value="">Any type</option>
            {[
              ["general_rental", "General rental"],
              ["lease", "Lease"],
              ["tenant", "Tenant"],
              ["vacancy", "Vacancy"],
            ].map(([value, title]) => (
              <option key={value} value={value}>
                {title}
              </option>
            ))}
          </select>
        </label>
        {showLease && (
          <div>
            <label>
              Lease period
              <select name="leaseId" key={leaseId} defaultValue={leaseId} disabled={!propertyId}>
                <option value="">All lease periods</option>
                {leaseId && !periods.some((item) => item.id === leaseId) && (
                  <option value={leaseId}>
                    {selectedLease.data ? periodLabel(selectedLease.data) : "Selected lease period"}
                  </option>
                )}
                {periods.map((item) => (
                  <option key={item.id} value={item.id}>
                    {periodLabel(item)}
                  </option>
                ))}
              </select>
            </label>
            {!propertyId ? (
              <p>Select a property to see lease periods.</p>
            ) : leases.isFetching ? (
              <p role="status">Loading lease periods…</p>
            ) : leases.error || section?.availability === "unavailable" ? (
              <p role="alert">Lease periods are unavailable. Try again.</p>
            ) : (
              !periods.length && <p>No matching lease periods on this page.</p>
            )}
            {!!section?.nextCursor && (
              <button
                type="button"
                onClick={() => setLeasePage({ key: contextKey, cursor: section.nextCursor! })}
              >
                More lease periods
              </button>
            )}
            {!!cursor && (
              <button type="button" onClick={() => setLeasePage({ key: contextKey })}>
                First lease periods
              </button>
            )}
            {ownerId && propertyId && (
              <p>Lease choices use this owner’s current and former property relationships.</p>
            )}
            {(leases.error || section?.availability === "unavailable") && (
              <button type="button" onClick={() => void leases.refetch()}>
                Retry lease periods
              </button>
            )}
            {selectedLease.error && <p role="alert">Selected lease details are unavailable.</p>}
          </div>
        )}
      </div>
      <NameFilter
        key={`tenant:${params.get("tenantPartyId") ?? ""}`}
        name="tenantPartyId"
        label="Tenant"
        group="tenants"
        selected={params.get("tenantPartyId") ?? ""}
      />
      <label>
        Status
        <select
          name="status"
          key={params.get("status") ?? ""}
          defaultValue={params.get("status") ?? ""}
        >
          <option value="">All statuses</option>
          {[
            ["open", "Open"],
            ["in_progress", "In progress"],
            ["resolved", "Resolved"],
            ["dismissed", "Dismissed"],
          ].map(([value, title]) => (
            <option key={value} value={value}>
              {title}
            </option>
          ))}
        </select>
      </label>
      <label>
        Priority
        <select name="priority" defaultValue={params.get("priority") ?? ""}>
          <option value="">Any priority</option>
          {["low", "normal", "high", "urgent"].map((value) => (
            <option key={value}>{value}</option>
          ))}
        </select>
      </label>
      <label>
        Raised from
        <input
          type="date"
          name="raisedLocalOnOrAfter"
          defaultValue={params.get("raisedLocalOnOrAfter") ?? ""}
        />
      </label>
      <label>
        Raised through
        <input
          type="date"
          name="raisedLocalOnOrBefore"
          defaultValue={params.get("raisedLocalOnOrBefore") ?? ""}
        />
      </label>
      <button type="reset">Clear filters</button>
    </DynamicFilterForm>
  );
}
