import { useQuery } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "@epm/contracts";
import { useWorkspace } from "../app/workspace-gate";
import { readResult } from "./reads";
import { PageAsOf } from "../shared/page-as-of";
import { leasingStatusLabels } from "../shared/leasing-status";

export function statusLabel(value: string) {
  return (
    (
      {
        unknown: "Needs classification",
        ...leasingStatusLabels,
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
  const [params] = useSearchParams();
  const result = useQuery({
    queryKey: scope.key("portfolio-status-summary"),
    retry: false,
    queryFn: async ({ signal }) =>
      readResult(await api.GET("/api/portfolio/status-summary", { signal })),
  });
  return (
    <section aria-label="Portfolio occupancy and leasing status">
      {result.isPending && <p role="status">Loading inventory status…</p>}
      {result.error && <p role="alert">Inventory status unavailable: {result.error.message}</p>}
      {result.data && (
        <>
          <PageAsOf asOf={result.data.asOf} priority={1} />
          <p>
            {result.data.activePropertyCount} active properties · {result.data.activeSpaceCount}{" "}
            active rental units.
          </p>
          <nav className="property-status-tabs" aria-label="Property status filters">
            {[
              { label: "Occupied", count: result.data.occupiedCount, query: "occupancy=occupied" },
              { label: "Vacant", count: result.data.vacantCount, query: "occupancy=vacant" },
              {
                label: "Needs occupancy classification",
                count: result.data.unknownOccupancyCount,
                query: "occupancy=unknown",
              },
              {
                label: "Open for leasing now",
                count: result.data.availableNowCount,
                query: "availability=available_now",
              },
              {
                label: "Open for leasing later",
                count: result.data.availableLaterCount,
                query: "availability=available_on",
              },
              {
                label: "Review status",
                count: result.data.needsAttentionSpaceCount,
                query: "needsAttention=true",
              },
            ].map((item) => {
              const [key, value] = item.query.split("=");
              const selected = params.get(key) === value;
              const next = new URLSearchParams(params);
              for (const name of ["occupancy", "availability", "needsAttention", "cursor"])
                next.delete(name);
              next.set("state", "active");
              if (!selected) next.set(key, value);
              return (
                <Link
                  key={item.query}
                  to={`/properties?${next.toString()}`}
                  aria-current={selected ? "page" : undefined}
                >
                  {item.label}: <span>{item.count}</span>
                </Link>
              );
            })}
          </nav>
          {result.data.nearestAvailableOn && (
            <p>Next leasing opening date: {result.data.nearestAvailableOn}</p>
          )}
        </>
      )}
    </section>
  );
}
