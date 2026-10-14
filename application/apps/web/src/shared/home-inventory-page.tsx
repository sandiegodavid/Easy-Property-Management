import { useLocation, useSearchParams } from "react-router-dom";
import { useWorkspace } from "../app/workspace-gate";
import { HomeBackLink, HomeSourceLink, SourceWorkflowLink, useHomeScroll } from "./home-navigation";
import { useHomeInventory } from "./home-transport";

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
    <section aria-label="Home inventory spaces">
      <h2>{occupancy === "vacant" ? "Vacant spaces" : "Unknown occupancy"}</h2>
      <HomeBackLink fallback="/home">Return Home</HomeBackLink>
      <p>
        Active Properties and Spaces only. Counts describe recorded occupancy, not availability or
        verified physical condition. Unknown occupancy never counts as vacant.
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
              {read.value.matchingTotal} matching {occupancy} spaces · As of {read.value.asOf}
            </p>
            {read.value.items.length === 0 && <p>No matching spaces at this capture.</p>}
            <ul>
              {read.value.items.map((item) => (
                <li key={item.spaceId}>
                  {item.propertyName} / {item.spaceName} · {item.occupancy} · Local date{" "}
                  {item.effectiveLocalDate} · {item.timeZone}{" "}
                  <HomeSourceLink to={`/properties/${item.propertyId}/units`}>
                    Review current Property and Space status
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
