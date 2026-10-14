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
  const filters = homeFilters(params, bootstrap.serverTimeUtc);
  const requested = Number(params.get("limit") ?? 50);
  const limit = Number.isInteger(requested) && requested >= 1 && requested <= 100 ? requested : 50;
  const cursor = params.get("cursor") ?? undefined;
  const normalized = homeParams(filters);
  normalized.set("limit", String(limit));
  if (cursor) normalized.set("cursor", cursor);
  const query = normalized.toString();
  const read = useHomeItems(collection, filters, limit, cursor);
  useHomeScroll(!!read.value);
  useEffect(() => {
    if (params.toString() !== query) setParams(query, { replace: true, state: navigationState });
  }, [params, query, setParams, navigationState]);
  function restart() {
    const next = new URLSearchParams(query);
    next.delete("cursor");
    if (cursor) setParams(next, { state: navigationState });
    else read.retry();
  }
  const next = new URLSearchParams(query);
  if (read.value?.result.status === "available" && read.value.result.nextCursor)
    next.set("cursor", read.value.result.nextCursor);
  return (
    <section aria-label="Home collection page">
      <h2>{collectionTitles[collection]}</h2>
      <HomeBackLink fallback={`/home?${homeParams(filters)}`}>Return Home</HomeBackLink>
      <p>
        Scope: {filters.propertyId ?? "All properties"} · Horizon: {filters.horizonDays} days. Each
        page uses the capture shown below.
      </p>
      <form
        key={query}
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
          setParams(changed, { state: navigationState });
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
        <button>Apply collection filters</button>
      </form>
      <button disabled={read.updating} onClick={restart}>
        Restart collection with current filters
      </button>
      {read.status === 409 ? (
        <div role="alert">
          This collection changed or its continuation expired. Restart with the same filters before
          continuing.
        </div>
      ) : (
        <HomeCollection
          title={collectionTitles[collection]}
          collection={read.value?.result}
          read={read}
        />
      )}
      {read.kind === "available" &&
        read.value?.result.status === "available" &&
        read.value.result.nextCursor && (
          <Link state={navigationState} to={`?${next}`}>
            Next collection page
          </Link>
        )}
      <p>
        Restart replaces this page with a fresh capture. Pages from different captures are never
        appended together.
      </p>
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
