import { DynamicFilterForm } from "./dynamic-filter-form";
import { useId, useState } from "react";
import type { ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { ParentBackLink, SourceWorkflowLink as Link } from "./home-navigation";
import { api } from "@epm/contracts";
import type { components } from "@epm/contracts/generated";
import { AsyncRegion } from "@epm/ui";
import { useWorkspace } from "../app/workspace-gate";
import { normalizeApiError } from "./mutations";
import { SourceDetail } from "./source-detail";
import { statusLabel } from "../workflows/portfolio-status";
import { PageAsOf } from "./page-as-of";
import { leaseLastCoveredOn } from "./lease-dates";
import { DisclosureHelp } from "./home-disclosure-help";
import { readResult } from "../workflows/reads";
import { propertyUnitsLabel } from "./property-labels";
import { formatHomeTemporal } from "./home-time";
import { ownershipShareLabel } from "./ownership-shares";
import { CommandLinks } from "../workflows/command";

type Schema = components["schemas"];
type Kind = "property" | "owner";
type Section = Schema["OverviewResponse"]["sections"][string];
type SectionKind = Section["kind"];
type Scope = "current" | "former" | "all";
type RentalUnit = { id: string; displayName: string; status: string };
const label = (value: string) =>
  value
    .replace(/([a-z])([A-Z])/g, (_, a, b) => `${a} ${b.toLowerCase()}`)
    .replaceAll("_", " ")
    .replace(/^\w/, (character) => character.toUpperCase());
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
  const id = useId();
  return (
    <div>
      <div className="filter-label">
        <label htmlFor={id}>
          {name === "availability"
            ? "Leasing status"
            : name === "relationshipScope"
              ? "Show relationships"
              : label(name)}
        </label>
        {name === "availability" && (
          <DisclosureHelp
            label="About leasing status"
            text="Leasing status describes whether a property is open to a new tenancy, independent of current occupancy."
          />
        )}
      </div>
      <select key={value} id={id} name={name} defaultValue={value}>
        {options.map((option) => (
          <option key={option} value={option}>
            {(name === "availability" ? statusLabel(option) : label(option)) || "Any"}
          </option>
        ))}
      </select>
    </div>
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
function ReviewCards({
  items,
  unitNames = {},
  disableNotApplicable = false,
}: {
  items: Schema["CoverageResult"][];
  unitNames?: Record<string, string>;
  disableNotApplicable?: boolean;
}) {
  const priority = (item: Schema["CoverageResult"]) =>
    item.state === "missing_required_information" ? 0 : item.state === "needs_review" ? 1 : 2;
  return (
    <ul className="directory-coverage-list" aria-label="Information review areas">
      {[...items]
        .sort((a, b) => priority(a) - priority(b))
        .map((item) => {
          const content = (
            <>
              <span className="directory-coverage-area">Review {label(item.area)}</span>
              {unitNames[item.subjectId] && <span>{unitNames[item.subjectId]}</span>}
              <span className="directory-coverage-state" data-state={item.state ?? "unavailable"}>
                {label(item.state ?? "unavailable").replace(/^./, (character) =>
                  character.toUpperCase(),
                )}
              </span>
            </>
          );
          return (
            <li key={`${item.subjectId}:${item.area}`}>
              {disableNotApplicable && item.state === "not_applicable" ? (
                <div className="directory-coverage-card">{content}</div>
              ) : (
                <Link
                  className="directory-coverage-card"
                  to={`/coverage/${item.subjectKind}/${item.subjectId}/${item.area}`}
                >
                  {content}
                </Link>
              )}
            </li>
          );
        })}
    </ul>
  );
}
function CoveragePreview({ preview }: { preview: Schema["CoveragePreview"] }) {
  return (
    <div className="directory-coverage">
      {preview.viewAll.subjectKind !== "property" && <h4>Information review</h4>}
      {preview.availability === "unavailable" ? (
        <p>Information review unavailable.</p>
      ) : (
        <>
          <ReviewCards
            items={preview.items ?? []}
            disableNotApplicable={preview.viewAll.subjectKind === "property"}
          />
          {preview.hasMore && <p>Showing an information review preview.</p>}
        </>
      )}
      {preview.viewAll.subjectKind !== "property" && (
        <Link
          to={`/owners/${preview.viewAll.subjectId}/overview?relationshipScope=${preview.viewAll.relationshipScope}#coverage`}
        >
          View information review
        </Link>
      )}
    </div>
  );
}
export function Directory({
  kind,
  headingAction,
  beforeFilters,
}: {
  kind: Kind;
  headingAction?: ReactNode;
  beforeFilters?: ReactNode;
}) {
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
  const filterKey = params.toString();
  const [searchDraft, setSearchDraft] = useState({ key: filterKey, value: query.q });
  const search = searchDraft.key === filterKey ? searchDraft.value : query.q;
  function applyFilters(form: HTMLFormElement) {
    const next = new URLSearchParams();
    new FormData(form).forEach((value, key) => {
      if (typeof value === "string" && value) next.set(key, value);
    });
    setParams(next, { replace: true, preventScrollReset: true, state: location.state as unknown });
  }
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
      <div className="directory-heading">
        <h2>{kind === "property" ? "Properties" : "Owners"}</h2>
        {headingAction}
        {kind === "owner" && <Link to="/maintenance?tab=concerns">Owner concerns</Link>}
      </div>
      {beforeFilters}
      <DynamicFilterForm
        key={kind}
        className="read-filters"
        onSubmit={(event) => {
          event.preventDefault();
          applyFilters(event.currentTarget);
        }}
      >
        <label>
          {kind === "property" ? "Property name or address" : "Search"}
          <input
            name="q"
            value={search}
            onChange={(event) => setSearchDraft({ key: filterKey, value: event.target.value })}
            maxLength={240}
          />
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

        {kind === "property" && (
          <button
            type="button"
            onClick={(event) => {
              event.currentTarget.form?.reset();
              setSearchDraft({ key: "", value: "" });
              setParams({}, { replace: true, preventScrollReset: true });
            }}
          >
            Clear filters
          </button>
        )}
      </DynamicFilterForm>
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
          <PageAsOf asOf={result.data.asOf} />
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
                  {item.needsAttention && (
                    <p>
                      <span>Occupancy or leasing status needs review</span>{" "}
                      <Link to={`/properties/${item.id}/units`}>
                        Review status for {item.displayName}
                      </Link>
                    </p>
                  )}
                  <p>
                    {item.ownerCount} {item.ownerCount === 1 ? "owner" : "owners"}
                    {item.ownershipContext === "self_owned" && " · You"} · {item.spaceCount}{" "}
                    {item.spaceCount === 1 ? "rental unit" : "rental units"}
                  </p>
                  <div className="property-card-recognition">
                    <section aria-label="Owners">
                      <h4>Owners</h4>
                      <ul>
                        {item.owners.map((owner) => (
                          <li key={owner.partyId ?? owner.ownerKind}>
                            {owner.ownerKind === "local_operator" ? (
                              "You"
                            ) : (
                              <Link to={`/owners/${owner.partyId}/overview`}>
                                {owner.displayName}
                              </Link>
                            )}
                            <span>
                              {" "}
                              ·{" "}
                              {owner.sharePercent === null
                                ? "Share not recorded"
                                : ownershipShareLabel(owner.sharePercent)}
                            </span>
                          </li>
                        ))}
                        {item.ownerCount > item.owners.length && (
                          <li>
                            <Link to={`/properties/${item.id}/overview#relationships`}>
                              +{item.ownerCount - item.owners.length} more{" "}
                              {item.ownerCount - item.owners.length === 1 ? "owner" : "owners"}
                            </Link>
                          </li>
                        )}
                      </ul>
                    </section>
                    <section aria-label="Rental units">
                      <h4>Rental units</h4>
                      <ul>
                        {item.spaces.map((space) => (
                          <li key={space.id}>
                            {space.displayName} · {statusLabel(space.occupancy)} ·{" "}
                            {statusLabel(space.availability)}
                            {space.availability === "available_on" && space.availableOn && (
                              <> · {space.availableOn}</>
                            )}
                            {space.needsAttention && " · Needs attention"}
                          </li>
                        ))}
                      </ul>
                    </section>
                  </div>
                  {item.spaceCount > item.spaces.length && (
                    <p>
                      Showing {item.spaces.length} of {item.spaceCount} rental units. Open the
                      property for all rental units.
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
  return (
    <p>
      <ParentBackLink to={directory}>
        ← Back to {kind === "property" ? "Properties" : "Owners"}
      </ParentBackLink>
    </p>
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
      {target.entityType === "communication"
        ? "View conversation"
        : `View source ${target.entityType} ${target.entityId}`}
    </Link>
  );
}
function LeaseTenants({ lease }: { lease: Schema["LeaseItem"] }) {
  const tenants = Array.isArray(lease.tenants) ? lease.tenants : null;
  return (
    <>
      {tenants ? (
        <>
          <p>Tenants{lease.tenantCount ? ` (${lease.tenantCount})` : ": None recorded"}</p>
          {!!tenants.length && (
            <ul>
              {tenants.map((tenant, index) => (
                <li key={`${tenant.partyId}:${index}`}>
                  <Link to={`/tenants?identity=${tenant.partyId}`}>{tenant.displayName}</Link>
                  {" · "}
                  {label(tenant.participantRole)} · {tenant.startsOn} through{" "}
                  {leaseLastCoveredOn(tenant.endsOn) ?? "ongoing"}
                </li>
              ))}
            </ul>
          )}
          {lease.tenantCount > tenants.length && (
            <p>
              Showing {tenants.length} of {lease.tenantCount} tenants. View the lease for all
              participants.
            </p>
          )}
        </>
      ) : (
        <p>Tenant details are unavailable here. View the lease to see its participants.</p>
      )}
      <Link to={`/leases/${lease.id}/details`}>View lease</Link>
    </>
  );
}
function PropertyLeases({
  section,
  units,
  canStart,
}: {
  section: Schema["LeaseSection"];
  units: RentalUnit[];
  canStart: boolean;
}) {
  const { scope } = useWorkspace();
  const navigate = useNavigate();
  const location = useLocation();
  const groups = new Map(
    units.map((unit) => [unit.id, { unit, leases: [] as Schema["LeaseItem"][] }]),
  );
  for (const lease of section.items ?? []) {
    if (!groups.has(lease.spaceId)) {
      groups.set(lease.spaceId, {
        unit: { id: lease.spaceId, displayName: "Rental unit", status: "archived" },
        leases: [],
      });
    }
    groups.get(lease.spaceId)!.leases.push(lease);
  }
  return (
    <>
      <p>Manage agreements, tenants and lease history for this property.</p>
      <p>
        {section.matchingTotal} matching {section.matchingTotal === 1 ? "lease" : "leases"}.
        {section.nextCursor &&
          " More agreements may appear under the same rental on the next page."}
      </p>
      <div className="property-lease-groups">
        {[...groups.values()].map(({ unit, leases }) => (
          <section
            className="property-lease-group"
            key={unit.id}
            aria-label={`Leases for ${unit.displayName}`}
          >
            <header className="property-space-title-row">
              <h4>{unit.displayName}</h4>
              {canStart && unit.status === "active" && (
                <button
                  type="button"
                  disabled={!scope.canWrite}
                  onClick={() => {
                    void navigate(`/leasing?workflow=lease.create&spaceId=${unit.id}`, {
                      state: { returnTo: location.pathname + location.search },
                    });
                  }}
                >
                  Start lease draft
                </button>
              )}
            </header>
            {!leases.length && <p>No matching leases on this page.</p>}
            <ul className="context-item-cards">
              {leases.map((lease) => (
                <li key={lease.id}>
                  <strong>
                    {label(lease.status).replace(/^./, (character) => character.toUpperCase())} ·{" "}
                    {label(lease.leaseKind)}
                  </strong>
                  <p>
                    Contract: {lease.contractStartsOn} through{" "}
                    {leaseLastCoveredOn(lease.contractEndsOn) ?? "ongoing"}
                  </p>
                  {lease.actualMoveOutOn && <p>Move-out: {lease.actualMoveOutOn}</p>}
                  <LeaseTenants lease={lease} />
                </li>
              ))}
            </ul>
          </section>
        ))}
      </div>
    </>
  );
}
function SectionContents({
  section,
  currentPropertyOwners = false,
  propertyContext = false,
  unitNames,
  rentalUnits = [],
  canStartLeases = false,
}: {
  section: Section;
  currentPropertyOwners?: boolean;
  propertyContext?: boolean;
  unitNames?: Record<string, string>;
  rentalUnits?: RentalUnit[];
  canStartLeases?: boolean;
}) {
  if (section.kind === "leases" && propertyContext) {
    return <PropertyLeases section={section} units={rentalUnits} canStart={canStartLeases} />;
  }
  if (section.kind === "coverage" && propertyContext) {
    const items = section.items ?? [];
    const needsReview = items.filter(
      (item) => item.state === "needs_review" || item.state === "missing_required_information",
    ).length;
    return (
      <>
        <p>
          {needsReview} {needsReview === 1 ? "item needs" : "items need"} review
          {(section.matchingTotal ?? 0) > items.length ? " on this page" : ""}
        </p>
        <ReviewCards items={items} unitNames={unitNames} disableNotApplicable />
        {!items.length && <p>No information review areas on this page.</p>}
      </>
    );
  }
  if (section.kind === "money")
    return (
      section.summary && (
        <div className="property-money-summary">
          <p className="property-money-period">
            {section.summary.filters.from_on} through {section.summary.filters.through_on}
            <span>{section.summary.currency_code} · Property-local business dates</span>
          </p>
          <dl className="property-money-metrics">
            {section.summary.metrics.map((metric) => (
              <div key={metric.metric}>
                <dt>{label(metric.metric)}</dt>
                <dd>
                  {metric.amount} {section.summary?.currency_code}
                </dd>
              </div>
            ))}
          </dl>
          <p className="property-money-note">
            Whole-property activity, not owner entitlement. Recorded ownership shares do not
            allocate payments or distributions. Scheduled checks and pending owner reports are not
            received income. Figures reflect current corrected records. Deposit obligations are
            current balances across all recorded dates, separate from period activity.
          </p>
          <Link
            to={`/money?${new URLSearchParams({ [section.viewAll.subjectKind === "property" ? "propertyId" : "ownerId"]: section.viewAll.subjectId, fromOn: section.viewAll.fromOn ?? "", throughOn: section.viewAll.throughOn ?? "" })}`}
          >
            View money sources
          </Link>
        </div>
      )
    );
  return (
    <>
      <p>
        {currentPropertyOwners && section.kind === "relationships" ? (
          <>
            {section.matchingTotal} {section.matchingTotal === 1 ? "owner" : "owners"}
            {section.matchingTotal === 1 &&
              section.items?.some((item) => item.ownerKind === "local_operator") &&
              " · You"}
          </>
        ) : (
          `${section.matchingTotal} matching records`
        )}
      </p>
      {!section.items?.length && <p>No matching records on this page.</p>}
      <ul className="context-item-cards">
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
              <>
                <strong>
                  {propertyContext ? (
                    item.ownerKind === "local_operator" ? (
                      "You"
                    ) : item.partyId ? (
                      <Link to={`/owners/${item.partyId}/overview`}>
                        {item.ownerName ?? "Owner"}
                      </Link>
                    ) : (
                      (item.ownerName ?? "Owner")
                    )
                  ) : (
                    <Link to={`/properties/${item.propertyId}/overview`}>{item.propertyName}</Link>
                  )}
                </strong>
                <p>Ownership share: {ownershipShareLabel(item.sharePercent)}</p>
                <p>
                  {label(item.relationshipState)} · {item.startsOn} to {item.endsOn ?? "ongoing"}
                </p>
              </>
            )}
            {"occupancyStartsOn" in item && (
              <>
                <p>
                  {item.leaseKind} · Occupancy from {item.occupancyStartsOn} · Move-out{" "}
                  {item.actualMoveOutOn ?? "not recorded"}
                </p>
                <LeaseTenants lease={item} />
              </>
            )}
            {"occurredAtUtc" in item && (
              <p>
                {item.channel} · {item.direction} ·{" "}
                <time dateTime={item.occurredAtUtc}>
                  {formatHomeTemporal({ at: item.occurredAtUtc, timeZone: item.occurredTimezone })}
                </time>
              </p>
            )}
            {"dueAtUtc" in item && (
              <p>
                {item.priority} · {item.taskDeadlineState} · {item.dueAtUtc ?? "No deadline"}
                {item.waitingForLabel && ` · Waiting for ${item.waitingForLabel}`}
                {item.followUpAtUtc && ` · Follow-up ${item.followUpAtUtc}`}
              </p>
            )}
            {"target" in item && !("leaseKind" in item) && !("ownerKind" in item) && (
              <SourceLink target={item.target} />
            )}
            {"area" in item && (
              <p>
                {item.area} · {item.availability} · {item.state ?? "State unavailable"} ·{" "}
                {item.causes.join(", ")}
                <Link to={`/coverage/${item.subjectKind}/${item.subjectId}/${item.area}`}>
                  Review {item.area} information
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
  unitNames,
  unitsLabel = "Units",
  canManageProperty = false,
  rentalUnits,
}: {
  initial: Section;
  kind: Kind;
  id: string;
  query: ContextQuery;
  unitNames?: Record<string, string>;
  unitsLabel?: string;
  canManageProperty?: boolean;
  rentalUnits?: RentalUnit[];
}) {
  const { scope } = useWorkspace();
  const [page, setPage] = useState<{ cursor?: string } | null>(null);
  const heading =
    initial.kind === "coverage"
      ? "Information review"
      : initial.kind === "spaces"
        ? unitsLabel
        : kind === "property" && initial.kind === "relationships"
          ? "Owners"
          : initial.kind === "concerns"
            ? "Owner concerns"
            : label(initial.kind).replace(/^./, (character) => character.toUpperCase());
  const result = useQuery({
    queryKey: scope.key("overview-section", kind, id, query, initial.kind, page),
    enabled: page !== null,
    queryFn: ({ signal }) =>
      readOverview(kind, id, { ...query, section: initial.kind, cursor: page?.cursor }, signal),
  });
  const section = page === null ? initial : result.data?.sections[initial.kind];
  const showHeading = !(kind === "property" && initial.kind === "coverage");
  return (
    <section
      id={initial.kind}
      aria-label={`${initial.kind === "coverage" || initial.kind === "spaces" || (kind === "property" && initial.kind === "relationships") ? heading : initial.kind} section`}
      className="context-section"
    >
      {result.error ? (
        <>
          {showHeading && <h3>{heading}</h3>}
          {initial.kind === "money" && <MoneyPeriodFilter query={query} />}
          <ReadError
            error={result.error}
            restart={() => {
              if (page === null || page.cursor) setPage({});
              else void result.refetch();
            }}
          />
        </>
      ) : !section ? (
        <p role="status">Loading {heading.toLowerCase()}…</p>
      ) : (
        <>
          <AsyncRegion
            title={heading}
            showHeading={showHeading}
            headingAction={
              kind === "property" && section.kind === "relationships" ? (
                <div className="owners-heading-actions">
                  <RelationshipCheckboxes value={query.relationshipScope} />
                  {canManageProperty && (
                    <CommandLinks
                      keys={["portfolio.ownerships.replace"]}
                      target={id}
                      labels={{ "portfolio.ownerships.replace": "Change ownership" }}
                      title="Ownership actions"
                      asButtons
                      collapsible={false}
                    />
                  )}
                </div>
              ) : kind === "property" && section.kind === "leases" ? (
                <LeaseScopeFilter value={query.relationshipScope} />
              ) : kind === "owner" && section.kind === "concerns" ? (
                <div className="owners-heading-actions">
                  <Link
                    className="concern-create-link"
                    to={`/maintenance?workflow=owner_concern.create&ownerId=${id}`}
                  >
                    Record concern
                  </Link>
                  <Link to={`/maintenance?tab=concerns&ownerId=${id}`}>View all concerns</Link>
                </div>
              ) : undefined
            }
            showCaptureTime={false}
            state={
              section.availability === "unavailable"
                ? {
                    kind: "unavailable",
                    message:
                      section.reasonCode === "money_period_required"
                        ? "Choose an explicit period to read money activity."
                        : "This source is unavailable. Other sections remain independent.",
                    recovery: (
                      <>
                        {section.kind === "money" && <MoneyPeriodFilter query={query} />}
                        {section.reasonCode !== "money_period_required" && (
                          <button
                            onClick={() => {
                              if (page === null || page.cursor) setPage({});
                              else void result.refetch();
                            }}
                          >
                            Retry section
                          </button>
                        )}
                      </>
                    ),
                  }
                : {
                    kind: result.isFetching ? "refreshing" : "success",
                    message: "Refreshing section…",
                    asOf: section.asOf,
                  }
            }
          >
            {section.kind === "money" && <MoneyPeriodFilter query={query} />}
            <SectionContents
              section={section}
              currentPropertyOwners={kind === "property" && query.relationshipScope === "current"}
              propertyContext={kind === "property"}
              unitNames={unitNames}
              rentalUnits={rentalUnits}
              canStartLeases={canManageProperty}
            />
          </AsyncRegion>
          {section.kind !== "coverage" && <p>Source: {section.sourceKind}</p>}
          {"nextCursor" in section && section.nextCursor && (
            <button onClick={() => setPage({ cursor: section.nextCursor ?? undefined })}>
              Next {heading.toLowerCase()}
            </button>
          )}
          {page?.cursor && (
            <button onClick={() => setPage({})}>First {heading.toLowerCase()}</button>
          )}
        </>
      )}
    </section>
  );
}
function LeaseScopeFilter({ value }: { value: Scope }) {
  const [params, setParams] = useSearchParams();
  const state: unknown = useLocation().state;
  return (
    <label className="relationship-filter lease-scope-filter">
      <input
        type="checkbox"
        checked={value !== "current"}
        onChange={(event) => {
          const next = new URLSearchParams(params);
          next.set("leaseScope", event.target.checked ? "all" : "current");
          next.delete("cursor");
          setParams(next, { state, preventScrollReset: true });
        }}
      />{" "}
      Include past, future and draft leases
    </label>
  );
}
function RelationshipCheckboxes({ value }: { value: Scope }) {
  const [params, setParams] = useSearchParams();
  const navigationState: unknown = useLocation().state;
  return (
    <div className="relationship-filter" role="group" aria-label="Include owners">
      {(["current", "former"] as const).map((option) => (
        <label key={option}>
          <input
            type="checkbox"
            checked={value === "all" || value === option}
            disabled={value === option}
            onChange={() => {
              const next = new URLSearchParams(params);
              next.set(
                "relationshipScope",
                value === "all" ? (option === "current" ? "former" : "current") : "all",
              );
              next.delete("cursor");
              setParams(next, { state: navigationState });
            }}
          />
          {option === "current" ? "Current" : "Former"}
        </label>
      ))}
    </div>
  );
}
function MoneyPeriodFilter({ query }: { query: ContextQuery }) {
  const [params, setParams] = useSearchParams();
  const navigationState: unknown = useLocation().state;
  const [error, setError] = useState("");
  return (
    <DynamicFilterForm
      className="read-filters money-period-filter"
      aria-label="Money period"
      onSubmit={(event) => {
        event.preventDefault();
        const values = new FormData(event.currentTarget);
        const from = values.get("fromOn");
        const through = values.get("throughOn");
        if (typeof from !== "string" || typeof through !== "string" || from > through) {
          setError("Money from must be on or before Money through.");
          return;
        }
        setError("");
        const next = new URLSearchParams(params);
        next.set("fromOn", from);
        next.set("throughOn", through);
        next.delete("cursor");
        setParams(next, { state: navigationState, preventScrollReset: true, replace: true });
      }}
    >
      <label>
        Money from
        <input type="date" name="fromOn" defaultValue={query.fromOn} required />
      </label>
      <label>
        Money through
        <input type="date" name="throughOn" defaultValue={query.throughOn} required />
      </label>

      {error && <p role="alert">{error}</p>}
    </DynamicFilterForm>
  );
}
export function ContextOverview({ kind, tab = "overview" }: { kind: Kind; tab?: string }) {
  const { id = "" } = useParams();
  const { scope } = useWorkspace();
  const property = useQuery({
    queryKey: scope.key("portfolio-record", id),
    enabled: kind === "property",
    queryFn: async ({ signal }) =>
      readResult(
        await api.GET("/api/properties/{property_id}", {
          signal,
          params: { path: { property_id: id } },
        }),
      ),
  });
  const unitNames = Object.fromEntries(
    (property.data?.spaces ?? []).map((unit) => [unit.id, unit.displayName]),
  );
  const [params, setParams] = useSearchParams();
  const relationshipScope = choice(
    params.get(kind === "property" && tab === "leases" ? "leaseScope" : "relationshipScope"),
    ["current", "former", "all"] as const,
    kind === "property" && tab === "leases" ? "all" : "current",
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
  const result = useQuery<Schema["OverviewResponse"]>({
    queryKey: scope.key("overview", kind, id, query, section),
    placeholderData: (previous: Schema["OverviewResponse"] | undefined) =>
      previous?.subject.id === id && previous.subject.kind === kind ? previous : undefined,
    queryFn: ({ signal }) => readOverview(kind, id, { ...query, section }, signal),
  });
  return (
    <>
      {kind === "owner" && <h2>{tab}</h2>}
      <SourceDetail />
      {kind === "owner" && (
        <DynamicFilterForm
          className="read-filters"
          onSubmit={(event) => {
            event.preventDefault();
            const values = new FormData(event.currentTarget);
            const next = new URLSearchParams(params);
            values.forEach((value, key) => {
              if (typeof value === "string" && value) next.set(key, value);
            });
            next.delete("cursor");
            setParams(next, { replace: true, preventScrollReset: true });
          }}
        >
          <Select
            name="relationshipScope"
            value={relationshipScope}
            options={["current", "former", "all"]}
          />
        </DynamicFilterForm>
      )}
      {result.error ? (
        <ReadError
          error={result.error}
          restart={() => {
            void result.refetch();
          }}
        />
      ) : result.data ? (
        <>
          {result.data.subject.kind !== "property" && (
            <p>
              {result.data.subject.partyKind} ·{" "}
              {result.data.subject.archived ? "Archived" : "Active"}
            </p>
          )}
          {result.isFetching && (
            <span className="context-refresh-status" role="status">
              Refreshing…
            </span>
          )}
          <PageAsOf asOf={result.data.asOf} />
          {kind === "property" && tab === "overview" && (
            <div
              className="property-overview-status"
              role="region"
              aria-label="Property status summary"
            >
              {property.data ? (
                <>
                  {property.data.inventoryLayout !== "office_suites" && property.data.spaces[0] ? (
                    <p>
                      Occupancy:{" "}
                      {statusLabel(property.data.spaces[0].currentOccupancy.occupancyStatus)}
                      {" · "}Leasing status:{" "}
                      {statusLabel(property.data.spaces[0].availability.effectiveStatus)}
                      {property.data.spaces[0].availability.effectiveStatus === "available_on" &&
                        ` · ${property.data.spaces[0].availability.availableOn}`}
                    </p>
                  ) : (
                    <p>
                      {property.data.statusSummary.activeSpaceCount} active suites ·{" "}
                      {property.data.statusSummary.occupiedCount} occupied ·{" "}
                      {property.data.statusSummary.vacantCount} vacant ·{" "}
                      {property.data.statusSummary.unknownOccupancyCount} need occupancy
                      classification · {property.data.statusSummary.availableNowCount} open for
                      leasing now · {property.data.statusSummary.availableLaterCount} open for
                      leasing later
                    </p>
                  )}
                  {property.data.statusSummary.needsAttentionCount > 0 && (
                    <p className="ui-muted">Occupancy or leasing status needs review.</p>
                  )}
                </>
              ) : (
                <p role="status">
                  {property.error ? "Property status unavailable." : "Loading property status…"}
                </p>
              )}
            </div>
          )}
          {Object.values(result.data.sections)
            .filter(
              (item) =>
                !(
                  kind === "property" &&
                  tab === "overview" &&
                  ["spaces", "leases", "money", "maintenance", "communications"].includes(item.kind)
                ),
            )
            .sort((a, b) =>
              kind === "property"
                ? Number(b.kind === "coverage") - Number(a.kind === "coverage")
                : 0,
            )
            .map((item) => (
              <OverviewSection
                key={`${kind}:${id}:${JSON.stringify(query)}:${item.kind}:${result.data?.sourceRevision}`}
                initial={item}
                kind={kind}
                id={id}
                query={query}
                unitNames={unitNames}
                rentalUnits={property.data?.spaces}
                canManageProperty={kind === "property" && property.data?.status === "active"}
                unitsLabel={
                  property.data ? propertyUnitsLabel(property.data.inventoryLayout) : "Units"
                }
              />
            ))}
        </>
      ) : (
        <p role="status">Loading workspace…</p>
      )}
    </>
  );
}
