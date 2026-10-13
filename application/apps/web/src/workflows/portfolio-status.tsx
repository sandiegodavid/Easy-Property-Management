import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "@epm/contracts";
import { useWorkspace } from "../app/workspace-gate";
import { readResult } from "./reads";

export function statusLabel(value: string) {
  return (
    (
      {
        unknown: "Needs classification",
        available_on: "Available later",
        available_now: "Available now",
        not_available: "Not available",
        occupied: "Occupied",
        vacant: "Vacant",
        manual: "Recorded manually",
        lease: "Lease-owned",
        listing: "Listing-owned",
      } as Record<string, string>
    )[value] ?? value.replaceAll("_", " ")
  );
}

export function PortfolioStatusSummary() {
  const { scope } = useWorkspace();
  const result = useQuery({
    queryKey: scope.key("portfolio-status-summary"),
    retry: false,
    queryFn: async ({ signal }) =>
      readResult(await api.GET("/api/portfolio/status-summary", { signal })),
  });
  return (
    <section aria-label="Portfolio occupancy and availability">
      <h3>Occupancy and availability</h3>
      {result.isPending && <p role="status">Loading inventory status…</p>}
      {result.error && <p role="alert">Inventory status unavailable: {result.error.message}</p>}
      {result.data && (
        <>
          <p>
            {result.data.activePropertyCount} active properties · {result.data.activeSpaceCount}{" "}
            active spaces · As of {result.data.asOf}
          </p>
          <p>
            Counts describe spaces; filtered property results include any matching active space.
          </p>
          <ul>
            {[
              { label: "Occupied", count: result.data.occupiedCount, query: "occupancy=occupied" },
              { label: "Vacant", count: result.data.vacantCount, query: "occupancy=vacant" },
              {
                label: "Needs occupancy classification",
                count: result.data.unknownOccupancyCount,
                query: "occupancy=unknown",
              },
              {
                label: "Available now",
                count: result.data.availableNowCount,
                query: "availability=available_now",
              },
              {
                label: "Available later",
                count: result.data.availableLaterCount,
                query: "availability=available_on",
              },
              {
                label: "Review status",
                count: result.data.needsAttentionSpaceCount,
                query: "needsAttention=true",
              },
            ].map((item) => (
              <li key={item.query}>
                <Link to={`/properties?${item.query}`}>
                  {item.label}: {item.count}
                </Link>
              </li>
            ))}
          </ul>
          {result.data.nearestAvailableOn && (
            <p>Nearest availability date: {result.data.nearestAvailableOn}</p>
          )}
        </>
      )}
    </section>
  );
}
