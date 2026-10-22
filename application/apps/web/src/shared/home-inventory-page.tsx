import { useLocation, useSearchParams } from "react-router-dom";
import { useWorkspace } from "../app/workspace-gate";
import { HomeBackLink, HomeSourceLink, SourceWorkflowLink, useHomeScroll } from "./home-navigation";
import { useHomeInventory } from "./home-transport";
import { formatHomeTime } from "./home-time";

function InventoryPage({ occupancy }: { occupancy: "vacant" | "unknown" }) {
  const [params, setParams] = useSearchParams(),
    location = useLocation();
  const navigationState: unknown = location.state;
  const propertyId = params.get("propertyId") ?? undefined,
    cursor = params.get("cursor") ?? undefined;
  const requested = Number(params.get("limit") ?? 50);
  const limit = Number.isInteger(requested) && requested >= 1 && requested <= 100 ? requested : 50;
  const read = useHomeInventory(occupancy, propertyId, limit, cursor);
  useHomeScroll(!!read.value);
  function restart() {
    const next = new URLSearchParams(params);
    next.delete("cursor");
    if (cursor) setParams(next, { state: navigationState });
    else read.retry();
  }
  const next = new URLSearchParams(params);
  if (read.value?.nextCursor) next.set("cursor", read.value.nextCursor);
  return (
    <section aria-label="Home rental-unit inventory">
      <HomeBackLink fallback="/home">Return Home</HomeBackLink>
      <h2>{occupancy === "vacant" ? "Vacant rental units" : "Unknown occupancy"}</h2>
      <p>
        Active properties and rental units only. Counts describe recorded occupancy, not leasing
        status or verified physical condition. Unknown occupancy never counts as vacant.
      </p>
      <button disabled={read.updating} onClick={restart}>
        Restart inventory with current filters
      </button>
      {read.kind === "loading" && (
        <p role="status">{read.elapsed >= 2 ? "Still loading inventory…" : "Loading inventory…"}</p>
      )}
      {read.kind === "failed" ? (
        <p role="alert">
          {read.status === 409
            ? "Inventory changed or its continuation expired. Restart with the same filters."
            : `Inventory unavailable: ${read.message}. No count can be inferred.`}
        </p>
      ) : (
        read.value && (
          <>
            <p>
              {read.value.matchingTotal} matching {occupancy} rental units · As of{" "}
              <time dateTime={read.value.asOf}>{formatHomeTime(read.value.asOf)}</time>
            </p>
            {read.value.items.length === 0 && <p>No matching rental units at this capture.</p>}
            <ul className="result-card-list">
              {read.value.items.map((item) => (
                <li className="child-record-card inventory-result-card" key={item.spaceId}>
                  <header className="child-record-heading">
                    <h3>{item.propertyName}</h3>
                    <span className="record-pill">
                      {item.occupancy === "unknown" ? "Needs occupancy classification" : "Vacant"}
                    </span>
                  </header>
                  <p className="inventory-unit-name">{item.spaceName}</p>
                  <dl className="context-row-facts">
                    <div>
                      <dt>Property-local date</dt>
                      <dd>{item.effectiveLocalDate}</dd>
                    </div>
                    <div>
                      <dt>Time zone</dt>
                      <dd>{item.timeZone}</dd>
                    </div>
                  </dl>
                  <HomeSourceLink to={`/properties/${item.propertyId}/units`}>
                    Review occupancy and leasing status
                  </HomeSourceLink>
                </li>
              ))}
            </ul>
            {read.value.nextCursor && (
              <SourceWorkflowLink state={navigationState} to={`?${next}`}>
                Next inventory page
              </SourceWorkflowLink>
            )}
          </>
        )
      )}
    </section>
  );
}

export function HomeInventoryPage() {
  const { bootstrap } = useWorkspace();
  const [params] = useSearchParams();
  if (!bootstrap.capabilities.includes("operator.home"))
    return <p role="alert">Home inventory is unavailable. No records have been loaded.</p>;
  const occupancy = params.get("occupancy");
  return occupancy === "vacant" || occupancy === "unknown" ? (
    <InventoryPage key={occupancy} occupancy={occupancy} />
  ) : (
    <p role="alert">Choose vacant or unknown occupancy.</p>
  );
}
