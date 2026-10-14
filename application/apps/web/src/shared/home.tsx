import { useEffect } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { AsyncRegion } from "@epm/ui";
import { useWorkspace } from "../app/workspace-gate";
import { homeFilters, homeParams, useHomeReads } from "./home-transport";
import { HomeCollection, HomeSummaries, LiveAttention } from "./home-sections";
import { useHomeScroll } from "./home-navigation";

function HomeTransport() {
  const { bootstrap } = useWorkspace();
  const [params, setParams] = useSearchParams();
  const filters = homeFilters(params, bootstrap.serverTimeUtc);
  const normalized = homeParams(filters).toString();
  const reads = useHomeReads(filters);
  useHomeScroll(!!reads.full.value && !!reads.live.value);
  useEffect(() => {
    if (params.toString() !== normalized) setParams(normalized, { replace: true });
  }, [params, normalized, setParams]);
  return (
    <>
      <header>
        <p>
          Scope: {filters.propertyId ?? "All properties"}. Unresolved obligations can include
          archived properties; unlinked Tasks appear only in All properties.
        </p>
        <button disabled={reads.full.updating || reads.live.updating} onClick={reads.refresh}>
          Refresh Home
        </button>
      </header>
      <form
        aria-label="Home filters"
        key={normalized}
        onSubmit={(event) => {
          event.preventDefault();
          const data = new FormData(event.currentTarget);
          const selected = new URLSearchParams();
          for (const name of ["propertyId", "horizonDays", "fromOn", "throughOn"]) {
            const value = data.get(name);
            selected.set(name, typeof value === "string" ? value : "");
          }
          setParams(homeParams(homeFilters(selected, bootstrap.serverTimeUtc)));
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
          Money from
          <input type="date" name="fromOn" defaultValue={filters.fromOn} />
        </label>
        <label>
          Money through
          <input type="date" name="throughOn" defaultValue={filters.throughOn} />
        </label>
        <button type="submit">Apply Home filters</button>
      </form>
      <p>
        Recorded money period: {filters.fromOn} through {filters.throughOn}. The default is the
        complete calendar month selected from server UTC time.
      </p>
      <section aria-label="Home summary">
        {reads.full.kind === "loading" ? (
          <p role="status">Loading Home summary…</p>
        ) : reads.full.kind === "failed" ? (
          <p role="alert">Home summary unavailable: {reads.full.message}</p>
        ) : (
          reads.full.value && <p>Home summary captured at {reads.full.value.asOf}.</p>
        )}
      </section>
      <div className="home-grid">
        <div className="home-work">
          <section aria-label="Live Home attention">
            <LiveAttention
              key={filters.propertyId ?? "portfolio"}
              read={reads.live}
              fallback={reads.full.value?.needsAction}
              filters={filters}
            />
          </section>
          <HomeCollection
            title="Waiting"
            filters={filters}
            collection={reads.full.value?.waiting}
            read={reads.full}
          />
          <HomeCollection
            title="Upcoming"
            filters={filters}
            collection={reads.full.value?.upcoming}
            read={reads.full}
          />
        </div>
        <div>
          <HomeCollection
            title="Calendar and appointments"
            filters={filters}
            collection={reads.full.value?.appointments}
            read={reads.full}
          />
          <HomeCollection
            title="Information review"
            filters={filters}
            collection={reads.full.value?.informationReview}
            read={reads.full}
          />
        </div>
      </div>
      <HomeSummaries value={reads.full.value} read={reads.full} />
    </>
  );
}

export function Home() {
  const { bootstrap } = useWorkspace();
  const ready = bootstrap.capabilities.includes("operator.home");
  return (
    <section aria-label="Home">
      <h2>Home</h2>
      {ready ? (
        <HomeTransport />
      ) : (
        <AsyncRegion
          title="Home attention and calendar"
          state={{
            kind: "unavailable",
            message:
              "The combined Home work queue and calendar are not available yet. Open a source workflow to review its current records.",
          }}
        />
      )}
      <p>Hiding a destination does not hide its obligations.</p>
      <nav aria-label="Task attention">
        <Link to="/tasks">Task deadlines and reminders</Link>{" "}
        <Link to="/tasks?followUps=true">Waiting and follow-ups</Link>
      </nav>
      <p>Review information coverage in the relevant Property or Owner workspace.</p>
    </section>
  );
}
