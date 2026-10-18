import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useLocation, useSearchParams } from "react-router-dom";
import { SourceWorkflowLink as Link } from "../shared/home-navigation";
import { api } from "@epm/contracts";
import { useWorkspace } from "../app/workspace-gate";
import { DynamicFilterForm } from "../shared/dynamic-filter-form";
import { PageAsOf } from "../shared/page-as-of";
import { CommandLinks } from "./command";
import { readResult } from "./reads";

export function TenantDirectory() {
  const { scope } = useWorkspace();
  const location = useLocation();
  const [params, setParams] = useSearchParams();
  const search = params.get("q") ?? "";
  const cursor = params.get("cursor") ?? undefined;
  const archived = params.get("archived") === "true";
  const browsing = params.get("browse") === "true" && !search;
  const filterKey = params.toString();
  const [entry, setEntry] = useState({ key: filterKey, value: search });
  const input = entry.key === filterKey ? entry.value : search;
  const hasSearch = input.trim().length >= 2;
  const current = (hasSearch || browsing) && input.trim() === search;
  const results = useQuery({
    queryKey: scope.key("tenant-directory", search, cursor, archived, browsing),
    enabled: current,
    retry: false,
    queryFn: async ({ signal }) =>
      readResult(
        await api.GET(browsing ? "/api/operator/tenants" : "/api/operator/search", {
          signal,
          params: {
            query: browsing
              ? { limit: 20, cursor, includeArchived: archived }
              : { q: search, group: "tenants", limit: 20, cursor, includeArchived: archived },
          },
        }),
      ),
  });
  const group = current ? results.data?.groups.tenants : undefined;
  function restart() {
    if (cursor) {
      const next = new URLSearchParams(params);
      next.delete("cursor");
      setParams(next, { preventScrollReset: true });
    } else void results.refetch();
  }
  return (
    <section className="tenant-directory" aria-label="Tenant directory">
      <header className="tenant-directory-heading">
        <h2>Tenants</h2>
        <CommandLinks
          keys={["tenant.create"]}
          title="Tenant actions"
          asButtons
          collapsible={false}
        />
      </header>
      <DynamicFilterForm
        className="tenant-directory-filters"
        aria-label="Tenant filters"
        onSubmit={(event) => {
          const data = new FormData(event.currentTarget);
          const next = new URLSearchParams();
          const value = data.get("q");
          const query = typeof value === "string" ? value.trim() : "";
          if (query) next.set("q", query);
          else if (browsing) next.set("browse", "true");
          if (data.get("archived") === "on") next.set("archived", "true");
          setParams(next, { replace: true, preventScrollReset: true });
        }}
      >
        <div className="tenant-directory-search">
          <label htmlFor="tenant-search">Search tenants</label>
          <input
            id="tenant-search"
            type="search"
            name="q"
            value={input}
            onChange={(event) => setEntry({ key: filterKey, value: event.target.value })}
            placeholder="Search by name"
            minLength={2}
            maxLength={240}
            aria-describedby="tenant-search-hint"
          />
          <span id="tenant-search-hint">
            Enter at least 2 characters. Results update as you type.
          </span>
        </div>
        <label className="tenant-directory-archived">
          <input type="checkbox" name="archived" defaultChecked={archived} />
          Include archived tenants
        </label>
        <button
          type="button"
          className="tenant-directory-browse"
          onClick={() => {
            const next = new URLSearchParams({ browse: "true" });
            if (archived) next.set("archived", "true");
            setEntry({ key: next.toString(), value: "" });
            setParams(next, { preventScrollReset: true });
          }}
        >
          Browse tenants
        </button>
      </DynamicFilterForm>
      {!hasSearch && (!browsing || input.trim() !== "") ? (
        <div className="tenant-directory-empty">
          <h3>Find a tenant</h3>
          <p>Search by name or browse tenants to open contact details and preferences.</p>
        </div>
      ) : (
        <section aria-label="Tenant search results" className="tenant-directory-results">
          {(!current || results.isFetching) && <p role="status">Loading tenants…</p>}
          {current && results.error && (
            <div className="tenant-directory-empty" role="alert">
              <h3>{browsing ? "Tenant list is unavailable" : "Tenant search is unavailable"}</h3>
              <p>Try again to load {browsing ? "the tenant list" : "matching tenants"}.</p>
              <button type="button" onClick={restart}>
                {browsing ? "Retry loading tenants" : "Retry search"}
              </button>
            </div>
          )}
          {group?.availability === "unavailable" && (
            <div className="tenant-directory-empty" role="alert">
              <h3>{browsing ? "Tenant list is unavailable" : "Tenant search is unavailable"}</h3>
              <button type="button" onClick={restart}>
                {browsing ? "Retry loading tenants" : "Retry search"}
              </button>
            </div>
          )}
          {group?.availability === "available" && (
            <>
              {results.data && <PageAsOf asOf={results.data.asOf} />}
              {!!group.matchingTotal && (
                <p className="tenant-directory-count" role="status">
                  {group.matchingTotal} {browsing ? "" : "matching "}
                  {group.matchingTotal === 1 ? "tenant" : "tenants"}
                </p>
              )}
              {group.items?.length ? (
                <ul className="tenant-directory-grid">
                  {group.items.map((item) => (
                    <li key={item.sourceId}>
                      <Link
                        className="tenant-directory-card"
                        to={`/tenants?identity=${item.sourceId}`}
                        state={{ returnTo: location.pathname + location.search }}
                        aria-label={item.label}
                      >
                        <div className="tenant-directory-card-heading">
                          <h3>{item.label}</h3>
                          {item.archived && (
                            <span className="tenant-directory-badge">Archived</span>
                          )}
                        </div>
                        <span className="tenant-directory-card-action">
                          View tenant details <span aria-hidden="true">→</span>
                        </span>
                      </Link>
                    </li>
                  ))}
                </ul>
              ) : (
                <div className="tenant-directory-empty">
                  <h3>No tenants found</h3>
                  <p>Try another name{archived ? "." : " or include archived tenants."}</p>
                </div>
              )}
              {(cursor || group.nextCursor) && (
                <nav className="tenant-directory-pagination" aria-label="Tenant pages">
                  {cursor && (
                    <button type="button" onClick={restart}>
                      Back to first page
                    </button>
                  )}
                  {group.nextCursor && (
                    <button
                      type="button"
                      onClick={() => {
                        const next = new URLSearchParams(params);
                        next.set("cursor", group.nextCursor!);
                        setParams(next, { preventScrollReset: true });
                      }}
                    >
                      Next tenants
                    </button>
                  )}
                </nav>
              )}
            </>
          )}
        </section>
      )}
    </section>
  );
}
