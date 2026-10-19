import { DynamicFilterForm } from "./dynamic-filter-form";
import { useEffect } from "react";
import { Link, useLocation, useParams, useSearchParams } from "react-router-dom";
import { useWorkspace } from "../app/workspace-gate";
import { HomeCollection } from "./home-sections";
import { collections, collectionTitles, HomeBackLink, useHomeScroll } from "./home-navigation";
import { homeFilters, homeParams, useHomeItems } from "./home-transport";

function CollectionPage({ collection }: { collection: (typeof collections)[number] }) {
  const { bootstrap } = useWorkspace();
  const [params, setParams] = useSearchParams(),
    location = useLocation();
  const navigationState: unknown = location.state;
  const state =
    navigationState && typeof navigationState === "object"
      ? (navigationState as Record<string, unknown>)
      : {};
  const previous = Array.isArray(state.homeCollectionPrevious)
    ? state.homeCollectionPrevious.filter(
        (value): value is string | null => value === null || typeof value === "string",
      )
    : [];
  const filters = homeFilters(params, bootstrap.serverTimeUtc);
  const requested = Number(params.get("limit") ?? 50);
  const limit = Number.isInteger(requested) && requested >= 1 && requested <= 100 ? requested : 50;
  const cursor =
    params.get("cursor") ??
    (typeof state.homeCollectionCursor === "string" ? state.homeCollectionCursor : undefined);
  const normalized = homeParams(filters);
  normalized.set("limit", String(limit));
  if (params.has("cursor")) normalized.set("cursor", params.get("cursor")!);
  const query = normalized.toString();
  const read = useHomeItems(collection, filters, limit, cursor);
  useHomeScroll(!!read.value && !read.updating);
  useEffect(() => {
    if (params.toString() !== query) setParams(query, { replace: true, state: navigationState });
  }, [params, query, setParams, navigationState]);
  function restart() {
    const next = new URLSearchParams(query);
    next.delete("cursor");
    if (cursor)
      setParams(next, {
        state: { ...state, homeCollectionCursor: undefined, homeCollectionPrevious: [] },
      });
    else read.retry();
  }
  const next = new URLSearchParams(query);
  next.delete("cursor");
  return (
    <section aria-label="Home collection page">
      <HomeBackLink className="parent-back-link" fallback={`/home?${homeParams(filters)}`}>
        ← Back to Home
      </HomeBackLink>
      <h2>{collectionTitles[collection]}</h2>
      <p>
        Scope: {filters.propertyId ?? "All properties"} · Horizon: {filters.horizonDays} days. Each
        page uses the capture shown below.
      </p>
      <DynamicFilterForm
        aria-label="Collection filters"
        onSubmit={(event) => {
          event.preventDefault();
          const data = new FormData(event.currentTarget);
          const changed = new URLSearchParams(query);
          for (const key of ["propertyId", "horizonDays", "limit"]) {
            const value = data.get(key);
            changed.set(key, typeof value === "string" ? value : "");
          }
          changed.delete("cursor");
          setParams(changed, {
            state: { ...state, homeCollectionCursor: undefined, homeCollectionPrevious: [] },
            replace: true,
            preventScrollReset: true,
          });
        }}
      >
        <label>
          Property ID (blank for all properties)
          <input name="propertyId" defaultValue={filters.propertyId ?? ""} />
        </label>
        <label>
          Upcoming horizon
          <select name="horizonDays" defaultValue={filters.horizonDays}>
            <option value="7">7 days</option>
            <option value="30">30 days</option>
            <option value="90">90 days</option>
          </select>
        </label>
        <label>
          Page size
          <input type="number" name="limit" defaultValue={limit} min={1} max={100} required />
        </label>
      </DynamicFilterForm>
      <button disabled={read.updating} onClick={restart}>
        Refresh collection
      </button>
      {read.status === 409 ? (
        <div role="alert">
          This collection changed or its continuation expired. Refresh collection to continue with
          the same filters.
        </div>
      ) : (
        <HomeCollection
          showHeading={false}
          title={collectionTitles[collection]}
          collection={read.value?.result}
          read={read}
        />
      )}
      <nav aria-label="Collection pages" className="home-collection-pagination">
        {previous.length > 0 && (
          <Link
            to={`?${next}`}
            state={{
              ...state,
              homeCollectionCursor: previous.at(-1),
              homeCollectionPrevious: previous.slice(0, -1),
            }}
          >
            ← Previous
          </Link>
        )}
        <span>Page {previous.length + 1}</span>
        {read.kind === "available" &&
          read.value?.result.status === "available" &&
          read.value.result.nextCursor && (
            <Link
              state={{
                ...state,
                homeCollectionCursor: read.value.result.nextCursor,
                homeCollectionPrevious: [...previous, cursor ?? null],
              }}
              to={`?${next}`}
            >
              Next →
            </Link>
          )}
      </nav>
    </section>
  );
}

export function HomeCollectionPage() {
  const { bootstrap } = useWorkspace();
  const { collection } = useParams();
  if (!bootstrap.capabilities.includes("operator.home"))
    return <p role="alert">Home collections are unavailable. No records have been loaded.</p>;
  const selected = collections.find((kind) => kind === collection);
  return selected ? (
    <CollectionPage key={selected} collection={selected} />
  ) : (
    <p role="alert">Unknown Home collection.</p>
  );
}
