import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useLocation, useParams, useSearchParams } from "react-router-dom";
import { api } from "@epm/contracts";
import type { components } from "@epm/contracts/generated";
import { AsyncRegion } from "@epm/ui";
import { useWorkspace } from "../app/workspace-gate";
import { normalizeApiError } from "./mutations";
import { SourceDetail } from "./source-detail";
import { statusLabel } from "../workflows/portfolio-status";

type Schema = components["schemas"];
type Kind = "property" | "owner";
type Section = Schema["OverviewResponse"]["sections"][string];
type SectionKind = Section["kind"];
type Scope = "current" | "former" | "all";
const label = (value: string) => value.replace(/([a-z])([A-Z])/g, "$1 $2").replaceAll("_", " ");
class ReadFailure extends Error {
  constructor(
    readonly status: number,
    error: unknown,
  ) {
    super(normalizeApiError(status, error).message);
  }
}
function choice<T extends string>(value: string | null, choices: readonly T[], fallback: T): T {
  return choices.find((item) => item === value) ?? fallback;
}
function Select({
  name,
  value,
  options,
}: {
  name: string;
  value: string;
  options: readonly string[];
}) {
  return (
    <label>
      {label(name)}
      <select name={name} defaultValue={value}>
        {options.map((option) => (
          <option key={option} value={option}>
            {label(option) || "Any"}
          </option>
        ))}
      </select>
    </label>
  );
}
function ReadError({ error, restart }: { error: Error; restart: () => void }) {
  return (
    <div role="alert">
      <p>
        {error instanceof ReadFailure && error.status === 409
          ? "This view changed or its continuation expired. Restart with the same filters."
          : error.message}
      </p>
      <button onClick={restart}>Refresh results</button>
    </div>
  );
}
function Provenance({ asOf, revision }: { asOf: string; revision: string | null }) {
  return (
    <div>
      <p>
        As of <time dateTime={asOf}>{asOf}</time>
      </p>
      {revision && (
        <details>
          <summary>Read provenance</summary>
          <p className="read-revision">Source revision: {revision}</p>
        </details>
      )}
    </div>
  );
}
function CoveragePreview({ preview }: { preview: Schema["CoveragePreview"] }) {
  return (
    <div>
      {preview.availability === "unavailable" ? (
        <p>Coverage unavailable.</p>
      ) : (
        <>
          <p>{preview.matchingTotal} coverage areas</p>
          <ul>
            {preview.items?.map((item) => (
              <li key={`${item.subjectId}:${item.area}`}>
                {label(item.area)}: {label(item.state ?? "unavailable")}
                {"subjectKind" in item && (
                  <Link to={`/coverage/${item.subjectKind}/${item.subjectId}/${item.area}`}>
                    Review {item.area}
                  </Link>
                )}
              </li>
            ))}
          </ul>
          {preview.hasMore && <p>Showing a bounded coverage preview.</p>}
        </>
      )}
      <Link
        to={`/${preview.viewAll.subjectKind === "property" ? "properties" : "owners"}/${preview.viewAll.subjectId}/overview?relationshipScope=${preview.viewAll.relationshipScope}#coverage`}
      >
        View coverage
      </Link>
    </div>
  );
}
export function Directory({ kind }: { kind: Kind }) {
  const location = useLocation();
  const { scope } = useWorkspace();
  const [params, setParams] = useSearchParams();
  const state = choice(params.get("state"), ["active", "archived", "all"] as const, "active");
  const relationship = choice(
    params.get("relationshipScope"),
    ["current", "former", "all"] as const,
    "current",
  );
  const query = { q: params.get("q") ?? "", limit: 50, cursor: params.get("cursor") ?? undefined };
  const result = useQuery({
    queryKey: scope.key("directory", kind, params.toString()),
    queryFn: async ({ signal }) => {
      const response =
        kind === "property"
          ? await api.GET("/api/operator/properties", {
              signal,
              params: {
                query: {
                  ...query,
                  status: state,
                  ownershipContext:
                    choice(
                      params.get("ownershipContext"),
                      ["", "self_owned", "managed_for_owner", "mixed"] as const,
                      "",
                    ) || undefined,
                  occupancy:
                    choice(
                      params.get("occupancy"),
                      ["", "occupied", "vacant", "unknown"] as const,
                      "",
                    ) || undefined,
                  availability:
                    choice(
                      params.get("availability"),
                      ["", "available_now", "available_on", "not_available", "unknown"] as const,
                      "",
                    ) || undefined,
                  needsAttention:
                    params.get("needsAttention") === "true"
                      ? true
                      : params.get("needsAttention") === "false"
                        ? false
                        : undefined,
                },
              },
            })
          : await api.GET("/api/operator/owners", {
              signal,
              params: {
                query: {
                  ...query,
                  archiveState: state,
                  relationshipScope: relationship,
                  propertyState: choice(
                    params.get("propertyState"),
                    ["active", "archived", "all"] as const,
                    "active",
                  ),
                },
              },
            });
      if (!response.data) throw new ReadFailure(response.response.status, response.error);
      return response.data;
    },
  });
  function cursor(value?: string | null) {
    const next = new URLSearchParams(params);
    next.delete("cursor");
    if (value) next.set("cursor", value);
    setParams(next);
  }
  return (
    <>
      <h2>{kind === "property" ? "Properties" : "Owners"}</h2>
      <form
        key={params.toString()}
        className="read-filters"
        onSubmit={(event) => {
          event.preventDefault();
          const values = new FormData(event.currentTarget);
          const next = new URLSearchParams();
          values.forEach((value, key) => {
            if (typeof value === "string" && value) next.set(key, value);
          });
          setParams(next);
        }}
      >
        <label>
          Search
          <input name="q" defaultValue={query.q} maxLength={240} />
        </label>
        <Select name="state" value={state} options={["active", "archived", "all"]} />
        {kind === "owner" ? (
          <>
            <Select
              name="relationshipScope"
              value={relationship}
              options={["current", "former", "all"]}
            />
            <Select
              name="propertyState"
              value={params.get("propertyState") ?? "active"}
              options={["active", "archived", "all"]}
            />
          </>
        ) : (
          <>
            <Select
              name="ownershipContext"
              value={params.get("ownershipContext") ?? ""}
              options={["", "self_owned", "managed_for_owner", "mixed"]}
            />
            <Select
              name="occupancy"
              value={params.get("occupancy") ?? ""}
              options={["", "occupied", "vacant", "unknown"]}
            />
            <Select
              name="availability"
              value={params.get("availability") ?? ""}
              options={["", "available_now", "available_on", "not_available", "unknown"]}
            />
            <Select
              name="needsAttention"
              value={params.get("needsAttention") ?? ""}
              options={["", "true", "false"]}
            />
          </>
        )}
        <button>Apply filters</button>
      </form>
      {result.error ? (
        <ReadError
          error={result.error}
          restart={() => {
            if (params.has("cursor")) cursor();
            else void result.refetch();
          }}
        />
      ) : result.data ? (
        <>
          <p role="status">
            {result.data.matchingTotal} matching {kind === "property" ? "properties" : "owners"}
            {result.isFetching ? " · Refreshing…" : ""}
          </p>
          <Provenance asOf={result.data.asOf} revision={result.data.sourceRevision} />
          {!result.data.items.length && <p>No matching records on this page.</p>}
          <ul className="context-cards">
            {result.data.items.map((item) =>
              "partyId" in item ? (
                <li key={item.partyId}>
                  <h3>
                    <Link
                      state={{ directory: location.pathname + location.search }}
                      to={`/owners/${item.partyId}/overview?relationshipScope=${relationship}`}
                    >
                      {item.displayName}
                    </Link>
                  </h3>
                  <p>
                    {item.partyKind} · {item.archived ? "Archived" : "Active"} ·{" "}
                    {item.propertyCount} related properties ({relationship})
                  </p>
                  <ul>
                    {item.properties.map((property) => (
                      <li key={property.id}>
                        <Link to={`/properties/${property.id}/overview`}>
                          {property.displayName}
                        </Link>{" "}
                        · {property.addressLine1}, {property.city} · {property.status}
                      </li>
                    ))}
                  </ul>
                  <p>
                    {item.propertyCount > item.properties.length &&
                      "Showing a bounded property preview. "}
                    <Link
                      to={`/owners/${item.partyId}/properties?relationshipScope=${relationship}`}
                    >
                      View related properties
                    </Link>
                  </p>
                  <CoveragePreview preview={item.coverage} />
                </li>
              ) : (
                <li key={item.id}>
                  <h3>
                    <Link
                      state={{ directory: location.pathname + location.search }}
                      to={`/properties/${item.id}/overview`}
                    >
                      {item.displayName}
                    </Link>
                  </h3>
                  <p>
                    {[
                      item.addressLine1,
                      item.addressLine2,
                      item.city,
                      item.region,
                      item.postalCode,
                      item.countryCode,
                    ]
                      .filter(Boolean)
                      .join(", ")}
                  </p>
                  <p>
                    {item.status} · {item.propertyType} · {item.inventoryLayout} ·{" "}
                    {item.ownershipContext}
                  </p>
                  <p>
                    Local date: {item.effectiveLocalDate} ({item.timeZone}) ·{" "}
                    {item.needsAttention ? "Needs attention" : "No status attention"}
                  </p>
                  <p>
                    {item.ownerCount} owners · {item.spaceCount} spaces
                  </p>
                  <ul>
                    {item.owners.map((owner) => (
                      <li key={owner.partyId}>
                        <Link to={`/owners/${owner.partyId}/overview`}>{owner.displayName}</Link>
                      </li>
                    ))}
                  </ul>
                  <ul>
                    {item.spaces.map((space) => (
                      <li key={space.id}>
                        {space.displayName} · {statusLabel(space.occupancy)} ·{" "}
                        {statusLabel(space.availability)}
                        {space.needsAttention && " · Needs attention"}
                      </li>
                    ))}
                  </ul>
                  {item.needsAttention && (
                    <Link to={`/properties/${item.id}/units`}>
                      Review status for {item.displayName}
                    </Link>
                  )}
                  {(item.ownerCount > item.owners.length ||
                    item.spaceCount > item.spaces.length) && (
                    <p>
                      Showing bounded owner and space previews. Open the workspace for all records.
                    </p>
                  )}
                  <CoveragePreview preview={item.coverage} />
                </li>
              ),
            )}
          </ul>
          {result.data.nextCursor && (
            <button onClick={() => cursor(result.data?.nextCursor)}>Next page</button>
          )}
          {params.has("cursor") && <button onClick={() => cursor()}>First page</button>}
        </>
      ) : (
        <p role="status">Loading directory…</p>
      )}
    </>
  );
}

type ContextQuery = {
  relationshipScope: Scope;
  fromOn?: string;
  throughOn?: string;
  sectionLimit: number;
};
export function ContextNavigator({ kind }: { kind: Kind }) {
  const location = useLocation();
  const { scope } = useWorkspace();
  const [search, setSearch] = useState<string | null>(null);
  const base = kind === "property" ? "/properties" : "/owners";
  const state: unknown = location.state;
  const directory =
    state &&
    typeof state === "object" &&
    "directory" in state &&
    typeof state.directory === "string" &&
    (state.directory === base || state.directory.startsWith(`${base}?`))
      ? state.directory
      : base;
  const result = useQuery({
    queryKey: scope.key("context-switcher", kind, search),
    enabled: search !== null,
    queryFn: async ({ signal }) => {
      const response =
        kind === "property"
          ? await api.GET("/api/operator/properties", {
              signal,
              params: { query: { q: search ?? "", limit: 50, status: "all" } },
            })
          : await api.GET("/api/operator/owners", {
              signal,
              params: {
                query: {
                  q: search ?? "",
                  limit: 50,
                  archiveState: "all",
                  propertyState: "all",
                  relationshipScope: "all",
                },
              },
            });
      if (!response.data) throw new ReadFailure(response.response.status, response.error);
      return response.data;
    },
  });
  return (
    <>
      <Link to={directory}>All {kind === "property" ? "properties" : "owners"}</Link>
      <details>
        <summary>Switch {kind}</summary>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            const value = new FormData(event.currentTarget).get("switchSearch");
            setSearch(typeof value === "string" ? value : "");
          }}
        >
          <label>
            Find {kind}
            <input name="switchSearch" maxLength={240} />
          </label>
          <button>Find records</button>
        </form>
        {result.isFetching && <p role="status">Finding records…</p>}
        {result.error && <p role="alert">{result.error.message}</p>}
        {result.data && (
          <>
            <p>
              {result.data.matchingTotal} matches; showing up to 50. Refine the search for more.
            </p>
            <ul>
              {result.data.items.map((item) => {
                const id = "partyId" in item ? item.partyId : item.id;
                return (
                  <li key={id}>
                    <Link state={{ directory }} to={`${base}/${id}/overview?relationshipScope=all`}>
                      {item.displayName}
                    </Link>
                  </li>
                );
              })}
            </ul>
          </>
        )}
      </details>
    </>
  );
}
async function readOverview(
  kind: Kind,
  id: string,
  query: ContextQuery & { section?: SectionKind; cursor?: string },
  signal: AbortSignal,
) {
  const response = await api.GET(
    kind === "property"
      ? "/api/operator/properties/{subject_id}/overview"
      : "/api/operator/owners/{subject_id}/overview",
    { signal, params: { path: { subject_id: id }, query } },
  );
  if (!response.data) throw new ReadFailure(response.response.status, response.error);
  return response.data;
}
function SourceLink({ target }: { target: Schema["EntityTarget"] }) {
  const location = useLocation();
  const state: unknown = location.state;
  const [params] = useSearchParams();
  const next = new URLSearchParams(params);
  next.set("sourceType", target.entityType);
  next.set("sourceId", target.entityId);
  const to =
    target.entityType === "property"
      ? `/properties/${target.entityId}/overview`
      : `?${next.toString()}#source-detail`;
  return (
    <Link to={to} state={state}>
      View source {target.entityType} {target.entityId}
    </Link>
  );
}
function SectionContents({ section }: { section: Section }) {
  if (section.kind === "money")
    return (
      section.summary && (
        <>
          <p>
            Whole-property activity, not owner entitlement. Ownership does not establish financial
            shares. Scheduled checks and pending owner reports are not received income.
          </p>
          <p>
            {section.summary.filters.from_on} through {section.summary.filters.through_on} ·{" "}
            {section.summary.currency_code} · Property-local business dates
          </p>
          <p>
            Figures reflect current corrected records. Deposit obligations are current balances
            across all recorded dates, separate from period activity.
          </p>
          <dl>
            {section.summary.metrics.map((metric) => (
              <div key={metric.metric}>
                <dt>{label(metric.metric)}</dt>
                <dd>
                  {metric.amount} {section.summary?.currency_code}
                </dd>
              </div>
            ))}
          </dl>
          <Link
            to={`/money?${new URLSearchParams({ [section.viewAll.subjectKind === "property" ? "propertyId" : "ownerId"]: section.viewAll.subjectId, fromOn: section.viewAll.fromOn ?? "", throughOn: section.viewAll.throughOn ?? "" })}`}
          >
            View money sources
          </Link>
        </>
      )
    );
  return (
    <>
      <p>{section.matchingTotal} matching records</p>
      {!section.items?.length && <p>No matching records on this page.</p>}
      <ul>
        {section.items?.map((item, index) => (
          <li key={"id" in item ? item.id : index}>
            {"displayName" in item && <strong>{item.displayName}</strong>}
            {"title" in item && <strong>{item.title}</strong>}
            {"summary" in item && <strong>{item.summary}</strong>}
            {"subject" in item && <strong>{item.subject}</strong>}
            {"status" in item && <p>Status: {item.status}</p>}
            {"occupancy" in item && (
              <p>
                {item.occupancy} · {item.availability}
                {item.needsAttention && " · Needs attention"}
              </p>
            )}
            {"ownerKind" in item && (
              <p>
                {item.ownerName ?? "Local operator"} · {item.propertyName} ·{" "}
                {item.relationshipState} · {item.startsOn} to {item.endsOn ?? "ongoing"}
              </p>
            )}
            {"occupancyStartsOn" in item && (
              <p>
                {item.leaseKind} · Occupancy from {item.occupancyStartsOn} · Move-out{" "}
                {item.actualMoveOutOn ?? "not recorded"}
              </p>
            )}
            {"occurredAtUtc" in item && (
              <p>
                {item.channel} · {item.direction} · {item.occurredAtUtc} ({item.occurredTimezone})
              </p>
            )}
            {"dueAtUtc" in item && (
              <p>
                {item.priority} · {item.taskDeadlineState} · {item.dueAtUtc ?? "No deadline"}
                {item.waitingForLabel && ` · Waiting for ${item.waitingForLabel}`}
                {item.followUpAtUtc && ` · Follow-up ${item.followUpAtUtc}`}
              </p>
            )}
            {"target" in item && <SourceLink target={item.target} />}
            {"area" in item && (
              <p>
                {item.area} · {item.availability} · {item.state ?? "State unavailable"} ·{" "}
                {item.causes.join(", ")}
                <Link to={`/coverage/${item.subjectKind}/${item.subjectId}/${item.area}`}>
                  Review {item.area} coverage
                </Link>
              </p>
            )}
          </li>
        ))}
      </ul>
    </>
  );
}
function OverviewSection({
  initial,
  kind,
  id,
  query,
}: {
  initial: Section;
  kind: Kind;
  id: string;
  query: ContextQuery;
}) {
  const { scope } = useWorkspace();
  const [page, setPage] = useState<{ cursor?: string } | null>(null);
  const result = useQuery({
    queryKey: scope.key("overview-section", kind, id, query, initial.kind, page),
    enabled: page !== null,
    queryFn: ({ signal }) =>
      readOverview(kind, id, { ...query, section: initial.kind, cursor: page?.cursor }, signal),
  });
  const section = page === null ? initial : result.data?.sections[initial.kind];
  return (
    <section id={initial.kind} aria-label={`${initial.kind} section`} className="context-section">
      {result.error ? (
        <>
          <h3>{initial.kind}</h3>
          <ReadError
            error={result.error}
            restart={() => {
              if (page === null || page.cursor) setPage({});
              else void result.refetch();
            }}
          />
        </>
      ) : !section ? (
        <p role="status">Loading {initial.kind}…</p>
      ) : (
        <>
          <AsyncRegion
            title={section.kind}
            state={
              section.availability === "unavailable"
                ? {
                    kind: "unavailable",
                    message:
                      section.reasonCode === "money_period_required"
                        ? "Choose an explicit period to read money activity."
                        : "This source is unavailable. Other sections remain independent.",
                    recovery: (
                      <button
                        onClick={() => {
                          if (page === null || page.cursor) setPage({});
                          else void result.refetch();
                        }}
                      >
                        Retry section
                      </button>
                    ),
                  }
                : {
                    kind: result.isFetching ? "refreshing" : "success",
                    message: "Refreshing section…",
                    asOf: section.asOf,
                  }
            }
          >
            <SectionContents section={section} />
          </AsyncRegion>
          <p>Source: {section.sourceKind}</p>
          <Provenance asOf={section.asOf} revision={section.sourceRevision} />
          {"nextCursor" in section && section.nextCursor && (
            <button onClick={() => setPage({ cursor: section.nextCursor ?? undefined })}>
              Next {section.kind}
            </button>
          )}
          {page?.cursor && <button onClick={() => setPage({})}>First {section.kind}</button>}
        </>
      )}
    </section>
  );
}
export function ContextOverview({ kind, tab = "overview" }: { kind: Kind; tab?: string }) {
  const { id = "" } = useParams();
  const { scope } = useWorkspace();
  const [params, setParams] = useSearchParams();
  const relationshipScope = choice(
    params.get("relationshipScope"),
    ["current", "former", "all"] as const,
    "current",
  );
  const query: ContextQuery = {
    relationshipScope,
    fromOn: params.get("fromOn") || undefined,
    throughOn: params.get("throughOn") || undefined,
    sectionLimit: 10,
  };
  const tabSections: Record<string, SectionKind> = {
    units: "spaces",
    details: "relationships",
    conversations: "communications",
    leases: "leases",
    money: "money",
    maintenance: "maintenance",
    properties: "properties",
  };
  const section = tabSections[tab];
  const result = useQuery({
    queryKey: scope.key("overview", kind, id, query, section),
    queryFn: ({ signal }) => readOverview(kind, id, { ...query, section }, signal),
  });
  return (
    <>
      <h2>{tab}</h2>
      <SourceDetail />
      <form
        key={params.toString()}
        className="read-filters"
        onSubmit={(event) => {
          event.preventDefault();
          const values = new FormData(event.currentTarget);
          const next = new URLSearchParams();
          values.forEach((value, key) => {
            if (typeof value === "string" && value) next.set(key, value);
          });
          setParams(next);
        }}
      >
        <Select
          name="relationshipScope"
          value={relationshipScope}
          options={["current", "former", "all"]}
        />
        <label>
          Money from
          <input type="date" name="fromOn" defaultValue={query.fromOn} />
        </label>
        <label>
          Money through
          <input type="date" name="throughOn" defaultValue={query.throughOn} />
        </label>
        <button>Apply context</button>
      </form>
      {result.error ? (
        <ReadError
          error={result.error}
          restart={() => {
            void result.refetch();
          }}
        />
      ) : result.data ? (
        <>
          <h3>{result.data.subject.displayName}</h3>
          {result.data.subject.kind === "property" ? (
            <p>
              {result.data.subject.addressLine1}, {result.data.subject.city},{" "}
              {result.data.subject.countryCode} · {result.data.subject.timeZone} ·{" "}
              {result.data.subject.status}
            </p>
          ) : (
            <p>
              {result.data.subject.partyKind} ·{" "}
              {result.data.subject.archived ? "Archived" : "Active"}
            </p>
          )}
          <p>
            Relationships: {result.data.relationshipScope}
            {result.isFetching && " · Refreshing…"}
          </p>
          <Provenance asOf={result.data.asOf} revision={result.data.sourceRevision} />
          {Object.values(result.data.sections).map((item) => (
            <OverviewSection
              key={`${kind}:${id}:${JSON.stringify(query)}:${item.kind}:${result.data?.sourceRevision}`}
              initial={item}
              kind={kind}
              id={id}
              query={query}
            />
          ))}
        </>
      ) : (
        <p role="status">Loading workspace…</p>
      )}
    </>
  );
}
