import { DynamicFilterForm } from "./dynamic-filter-form";
import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { AsyncRegion } from "@epm/ui";
import { useWorkspace } from "../app/workspace-gate";
import { homeFilters, homeParams, useHomeReads } from "./home-transport";
import { HomeCollection, HomeSummaries, LiveAttention } from "./home-sections";
import { DisclosureHelp } from "./home-disclosure-help";
import { useHomeScroll } from "./home-navigation";
import type { components } from "@epm/contracts/generated";

function DayHeading({
  attention,
  unavailable = false,
  updating = false,
}: {
  attention?:
    components["schemas"]["AvailableCollection"] | components["schemas"]["UnavailableCollection"];
  unavailable?: boolean;
  updating?: boolean;
}) {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), 60_000);
    return () => window.clearInterval(timer);
  }, []);
  let summary = unavailable ? "Action summary unavailable." : "Checking what needs action…";
  if (attention?.status === "available") {
    const total = attention.matchingTotal;
    const properties = new Set(
      attention.items.flatMap((item) => (item.propertyId ? [item.propertyId] : [])),
    ).size;
    const completePreview = total === attention.items.length;
    summary =
      total === 0
        ? "No items need action in recorded information."
        : `${total} ${total === 1 ? "item needs" : "items need"} action${completePreview && properties > 0 ? ` across ${properties} ${properties === 1 ? "property" : "properties"}` : ""}.`;
    if (updating || attention.capture.freshness === "stale")
      summary += " Showing the previous capture.";
  } else if (attention?.status === "unavailable") summary = "Action summary unavailable.";
  return (
    <div className="home-heading">
      <p className="home-eyebrow">
        <time dateTime={now.toISOString()}>
          {new Intl.DateTimeFormat("en-US", {
            weekday: "long",
            month: "long",
            day: "numeric",
          }).format(now)}
        </time>
      </p>
      <h2>Your day, in view</h2>
      <p className="ui-muted">{summary}</p>
    </div>
  );
}

function HomeTransport() {
  const { bootstrap } = useWorkspace();
  const [params, setParams] = useSearchParams();
  const filters = homeFilters(params, bootstrap.serverTimeUtc);
  const normalized = homeParams(filters).toString();
  const reads = useHomeReads(filters);
  const [showFilters, setShowFilters] = useState(false);
  const tabs = ["Needs action", "Waiting", "Upcoming"] as const;
  const [tab, setTab] = useState<(typeof tabs)[number]>("Needs action");
  useHomeScroll(!!reads.full.value && !!reads.live.value);
  useEffect(() => {
    if (params.toString() !== normalized) setParams(normalized, { replace: true });
  }, [params, normalized, setParams]);
  return (
    <>
      <div className="home-heading-bar">
        <DayHeading
          attention={reads.live.value?.needsAction ?? reads.full.value?.needsAction}
          unavailable={reads.live.kind === "failed" && !reads.live.value && !reads.full.value}
          updating={reads.live.updating || reads.live.stale || reads.live.kind === "failed"}
        />
        <div className="home-heading-actions">
          <div className="home-filter-control">
            <button
              type="button"
              aria-expanded={showFilters}
              aria-controls="home-filters"
              aria-describedby="home-filter-hint"
              onClick={() => setShowFilters(!showFilters)}
            >
              Filters
            </button>
            <small id="home-filter-hint" className="ui-muted">
              Property, upcoming horizon, and money period
            </small>
          </div>
          <button disabled={reads.full.updating || reads.live.updating} onClick={reads.refresh}>
            Refresh
          </button>
        </div>
        <section aria-label="Home summary" className="ui-muted">
          {reads.full.kind === "loading" ? (
            <p role="status">Loading Home summary…</p>
          ) : reads.full.kind === "failed" ? (
            <p role="alert">Home summary unavailable: {reads.full.message}</p>
          ) : null}
          <p className="home-scope">
            Scope: {filters.propertyId ?? "All properties"}. Unresolved obligations can include
            archived properties; unlinked Tasks appear only in All properties.
          </p>
        </section>
      </div>
      <div id="home-filters" hidden={!showFilters}>
        <DynamicFilterForm
          aria-label="Home filters"
          onSubmit={(event) => {
            event.preventDefault();
            const data = new FormData(event.currentTarget);
            const selected = new URLSearchParams();
            for (const name of ["propertyId", "horizonDays", "fromOn", "throughOn"]) {
              const value = data.get(name);
              selected.set(name, typeof value === "string" ? value : "");
            }
            setParams(homeParams(homeFilters(selected, bootstrap.serverTimeUtc)), {
              replace: true,
              preventScrollReset: true,
            });
          }}
        >
          <p id="home-money-filter-hint" className="ui-muted home-filter-explanation">
            Money dates apply only to Recorded money. They do not hide overdue or unresolved work.
          </p>
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
            <input
              type="date"
              name="fromOn"
              defaultValue={filters.fromOn}
              aria-describedby="home-money-filter-hint"
            />
          </label>
          <label>
            Money through
            <input
              type="date"
              name="throughOn"
              defaultValue={filters.throughOn}
              aria-describedby="home-money-filter-hint"
            />
          </label>
        </DynamicFilterForm>
      </div>
      <div className="home-grid">
        <div className="home-work">
          <div className="home-queue-header">
            <div role="tablist" aria-label="Work queue" className="page-tabs home-tabs">
              {tabs.map((title, index) => (
                <button
                  key={title}
                  type="button"
                  role="tab"
                  id={`home-tab-${index}`}
                  aria-selected={tab === title}
                  aria-controls={`home-panel-${index}`}
                  tabIndex={tab === title ? 0 : -1}
                  onClick={() => setTab(title)}
                  onKeyDown={(event) => {
                    const next =
                      event.key === "ArrowRight"
                        ? (index + 1) % tabs.length
                        : event.key === "ArrowLeft"
                          ? (index + tabs.length - 1) % tabs.length
                          : event.key === "Home"
                            ? 0
                            : event.key === "End"
                              ? tabs.length - 1
                              : null;
                    if (next !== null) {
                      event.preventDefault();
                      setTab(tabs[next]);
                      document.getElementById(`home-tab-${next}`)?.focus();
                    }
                  }}
                >
                  {title}
                </button>
              ))}
            </div>
            <DisclosureHelp />
          </div>
          <div
            role="tabpanel"
            id="home-panel-0"
            aria-labelledby="home-tab-0"
            hidden={tab !== "Needs action"}
          >
            <section aria-label="Live Home attention" className="home-live">
              <LiveAttention
                showDisclosureHint={false}
                allItems={tab === "Needs action"}
                key={filters.propertyId ?? "portfolio"}
                read={reads.live}
                fallback={reads.full.value?.needsAction}
                filters={filters}
              />
            </section>
          </div>
          <div
            role="tabpanel"
            id="home-panel-1"
            aria-labelledby="home-tab-1"
            hidden={tab !== "Waiting"}
          >
            <HomeCollection
              showDisclosureHint={false}
              allItems={tab === "Waiting"}
              title="Waiting"
              showHeading={false}
              filters={filters}
              collection={reads.full.value?.waiting}
              read={reads.full}
            />
          </div>
          <div
            role="tabpanel"
            id="home-panel-2"
            aria-labelledby="home-tab-2"
            hidden={tab !== "Upcoming"}
          >
            <HomeCollection
              showDisclosureHint={false}
              allItems={tab === "Upcoming"}
              title="Upcoming"
              showHeading={false}
              filters={filters}
              collection={reads.full.value?.upcoming}
              read={reads.full}
            />
          </div>
        </div>
        <div className="home-side">
          <HomeCollection
            showDisclosureHelp
            showDisclosureHint={false}
            allItems
            title="Calendar and appointments"
            filters={filters}
            collection={reads.full.value?.appointments}
            read={reads.full}
          />
          <HomeCollection
            showDisclosureHelp
            showDisclosureHint={false}
            allItems
            title="Information review"
            filters={filters}
            collection={reads.full.value?.informationReview}
            read={reads.full}
          />
        </div>
        <HomeSummaries value={reads.full.value} read={reads.full} filters={filters} />
      </div>
    </>
  );
}

export function Home() {
  const { bootstrap } = useWorkspace();
  const ready = bootstrap.capabilities.includes("operator.home");
  return (
    <section aria-label="Home">
      {ready ? (
        <HomeTransport />
      ) : (
        <>
          <DayHeading unavailable />
          <AsyncRegion
            title="Home attention and calendar"
            state={{
              kind: "unavailable",
              message:
                "The combined Home work queue and calendar are not available yet. Open a source workflow to review its current records.",
            }}
          />
          <nav aria-label="Task attention">
            <Link to="/tasks">Task deadlines and reminders</Link>{" "}
            <Link to="/tasks?followUps=true">Waiting and follow-ups</Link>
          </nav>
        </>
      )}
    </section>
  );
}
