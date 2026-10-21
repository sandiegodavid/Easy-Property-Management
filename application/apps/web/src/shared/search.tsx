import { useEffect, useId, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "@epm/contracts";
import type { components } from "@epm/contracts/generated";
import { useWorkspace } from "../app/workspace-gate";
import { readResult } from "../workflows/reads";
import { SourceDetail } from "./source-detail";
import { PageAsOf } from "./page-as-of";

type Group = components["schemas"]["SearchGroup"];
type Target = components["schemas"]["SearchTarget"];
const searchGroupLabels: Record<Group["kind"], string> = {
  properties: "Properties",
  spaces: "Rental units",
  owners: "Owners",
  tenants: "Tenants",
  leases: "Leases",
  communications: "Conversations",
  maintenance: "Maintenance issues",
  tasks: "Tasks",
};
function searchTarget(target: Target) {
  const id = encodeURIComponent(target.entityId);
  switch (target.entityType) {
    case "property":
      return `/properties/${id}/overview`;
    case "owner":
      return `/owners/${id}/overview`;
    case "tenant":
      return `/tenants?identity=${id}`;
    case "lease":
      return `/leases/${id}`;
    case "task":
      return `/tasks?record=task&id=${id}`;
    case "maintenance_issue":
      return `/maintenance?record=issue&id=${id}`;
    case "communication":
      return `/conversations?record=communication&id=${id}`;
    case "space":
      return `?sourceType=space&sourceId=${id}#source-detail`;
  }
}
function SearchGroup({ initial, q, archived }: { initial: Group; q: string; archived: boolean }) {
  const { scope } = useWorkspace();
  const [params, setParams] = useSearchParams();
  const [refreshed, setRefreshed] = useState(false);
  const cursor = params.get(`${initial.kind}Cursor`) ?? undefined;
  function setCursor(value?: string) {
    const next = new URLSearchParams(params);
    next.delete(`${initial.kind}Cursor`);
    if (value) next.set(`${initial.kind}Cursor`, value);
    setParams(next);
  }
  const result = useQuery({
    queryKey: scope.key("search-group", q, archived, initial.kind, cursor),
    enabled: cursor !== undefined || refreshed,
    queryFn: async ({ signal }) =>
      readResult(
        await api.GET("/api/operator/search", {
          signal,
          params: {
            query: { q, includeArchived: archived, group: initial.kind, cursor, limit: 10 },
          },
        }),
      ),
  });
  const group = cursor === undefined && !refreshed ? initial : result.data?.groups[initial.kind];
  return (
    <section aria-label={`${searchGroupLabels[initial.kind]} search results`}>
      <h3>{searchGroupLabels[initial.kind]}</h3>
      {result.error ? (
        <>
          <p role="alert">{result.error.message} Restart this group with the same filters.</p>
          <button
            onClick={() => {
              setRefreshed(true);
              setCursor(undefined);
            }}
          >
            Restart group
          </button>
        </>
      ) : !group ? (
        <p role="status">Loading results…</p>
      ) : group.availability === "unavailable" ? (
        <>
          <p role="alert">This search source is unavailable.</p>
          <button
            onClick={() => {
              if (refreshed) void result.refetch();
              else setRefreshed(true);
            }}
          >
            Retry {searchGroupLabels[group.kind].toLowerCase()} search
          </button>
        </>
      ) : (
        <>
          <PageAsOf asOf={group.asOf} priority={1} />
          <p>{group.matchingTotal} matches</p>
          {!group.items?.length && <p>No matching records on this page.</p>}
          <ul>
            {group.items?.map((hit) => (
              <li key={hit.sourceId}>
                <Link
                  to={
                    hit.sourceType === "space"
                      ? `?${new URLSearchParams([...params, ["sourceType", "space"], ["sourceId", hit.sourceId]])}#source-detail`
                      : searchTarget(hit.target)
                  }
                >
                  {hit.label}
                </Link>
                <p>
                  {hit.context}
                  {hit.archived && " · Archived"}
                </p>
              </li>
            ))}
          </ul>
          {group.nextCursor && (
            <button onClick={() => setCursor(group.nextCursor ?? undefined)}>
              Next {searchGroupLabels[group.kind].toLowerCase()} results
            </button>
          )}
          {cursor && (
            <button onClick={() => setCursor(undefined)}>
              First {searchGroupLabels[group.kind].toLowerCase()} results
            </button>
          )}
        </>
      )}
    </section>
  );
}
export function MetadataSearch() {
  const searchId = useId();
  const { scope } = useWorkspace();
  const [params, setParams] = useSearchParams();
  const q = params.get("q") ?? "";
  const archived = params.get("includeArchived") === "true";
  const [entry, setEntry] = useState({ query: q, value: q });
  if (entry.query !== q) setEntry({ query: q, value: q });
  const input = entry.query === q ? entry.value : q;
  useEffect(() => {
    if (input === q) return;
    const timer = setTimeout(
      () =>
        setParams(
          { q: input, includeArchived: String(archived) },
          { replace: true, preventScrollReset: true },
        ),
      250,
    );
    return () => clearTimeout(timer);
  }, [input, q, archived, setParams]);
  const result = useQuery({
    queryKey: scope.key("metadata-search", q, archived),
    enabled: q.trim().length >= 2,
    queryFn: async ({ signal }) =>
      readResult(
        await api.GET("/api/operator/search", {
          signal,
          params: { query: { q, includeArchived: archived, limit: 10 } },
        }),
      ),
  });
  return (
    <>
      <h2>Search</h2>
      <label htmlFor={searchId}>
        Search records
        <input
          id={searchId}
          value={input}
          maxLength={240}
          onChange={(event) => setEntry({ query: q, value: event.target.value })}
        />
      </label>
      <label>
        <input
          type="checkbox"
          checked={archived}
          onChange={(event) =>
            setParams(
              { q: input, includeArchived: String(event.target.checked) },
              { replace: true, preventScrollReset: true },
            )
          }
        />
        Include archived records
      </label>
      <p>Searches names and record details. Message text and file contents are not searched.</p>
      <SourceDetail />
      {q.trim().length < 2 ? (
        <p>Enter at least two characters.</p>
      ) : result.error ? (
        <>
          <p role="alert">{result.error.message}</p>
          <button onClick={() => void result.refetch()}>Retry search</button>
        </>
      ) : result.data ? (
        Object.values(result.data.groups).map((group) => (
          <SearchGroup
            key={`${q}:${archived}:${group.kind}`}
            initial={group}
            q={q}
            archived={archived}
          />
        ))
      ) : (
        <p role="status">Searching…</p>
      )}
    </>
  );
}
