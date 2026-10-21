import { useId } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@epm/contracts";
import type { components } from "@epm/contracts/generated";
import { useWorkspace } from "../app/workspace-gate";
import { readResult } from "../workflows/reads";
import { collections } from "./home-navigation";

type PropertyChoice = { id: string; displayName: string; archived: boolean };

async function homePropertyChoices(
  horizonDays: 7 | 30 | 90,
  identity: readonly [string, string],
  signal: AbortSignal,
): Promise<PropertyChoice[]> {
  let sourceRevision: string | undefined;
  const lists: PropertyChoice[][] = [];
  for (const collection of collections) {
    const properties: PropertyChoice[] = [];
    const cursors = new Set<string>();
    const keys = new Set<string>();
    let cursor: string | undefined;
    let capture: components["schemas"]["Capture"] | undefined;
    let total: number | undefined;
    do {
      const page = readResult(
        await api.GET("/api/operator/home/items", {
          signal: AbortSignal.any([signal, AbortSignal.timeout(10_000)]),
          params: { query: { collection, horizonDays, limit: 100, cursor } },
        }),
      );
      const section = page.result;
      if (
        page.workspaceId !== identity[0] ||
        page.runtimeEpoch !== identity[1] ||
        page.scope.kind !== "portfolio" ||
        page.scope.propertyId ||
        section.status !== "available" ||
        section.collection !== collection ||
        section.viewAllTarget.horizonDays !== horizonDays ||
        (sourceRevision !== undefined && sourceRevision !== page.sourceRevision) ||
        (capture &&
          (capture.asOf !== section.capture.asOf ||
            capture.sourceRevision !== section.capture.sourceRevision)) ||
        (total !== undefined && total !== section.matchingTotal)
      ) {
        throw new Error("Home property choices changed or are unavailable.");
      }
      sourceRevision = page.sourceRevision;
      capture = section.capture;
      total = section.matchingTotal;
      for (const item of section.items) {
        if (keys.has(item.key)) throw new Error("Home property choices could not be completed.");
        keys.add(item.key);
        if (item.propertyId) {
          if (!item.propertyName) throw new Error("A Home property name is unavailable.");
          properties.push({
            id: item.propertyId,
            displayName: item.propertyName,
            archived: item.propertyArchived,
          });
        }
      }
      cursor = section.nextCursor ?? undefined;
      if (cursor && cursors.has(cursor))
        throw new Error("Home property choices could not be completed.");
      if (cursor) cursors.add(cursor);
    } while (cursor);
    if (keys.size !== total) throw new Error("Home property choices could not be completed.");
    lists.push(properties);
  }
  const properties = new Map<string, PropertyChoice>();
  for (const property of lists.flat()) {
    const previous = properties.get(property.id);
    if (
      previous &&
      (previous.displayName !== property.displayName || previous.archived !== property.archived)
    ) {
      throw new Error("Home property choices changed. Retry shortly.");
    }
    properties.set(property.id, property);
  }
  return [...properties.values()].sort(
    (left, right) =>
      left.displayName.localeCompare(right.displayName) || left.id.localeCompare(right.id),
  );
}

function useSelectedProperty(propertyId?: string) {
  const { scope } = useWorkspace();
  return useQuery({
    queryKey: scope.key("home-selected-property", propertyId),
    enabled: !!propertyId,
    queryFn: async ({ signal }) =>
      readResult(
        await api.GET("/api/properties/{property_id}", {
          signal,
          params: { path: { property_id: propertyId! } },
        }),
      ),
  });
}

export function HomePropertyName({ propertyId }: { propertyId?: string }) {
  const property = useSelectedProperty(propertyId);
  if (!propertyId) return <>All properties</>;
  if (property.error) return <>Selected property (name unavailable)</>;
  return <>{property.data?.displayName ?? "Loading property…"}</>;
}

export function HomePropertyFilter({
  propertyId,
  horizonDays,
  enabled = true,
}: {
  propertyId?: string;
  horizonDays: 7 | 30 | 90;
  enabled?: boolean;
}) {
  const { scope } = useWorkspace();
  const id = useId();
  const selected = useSelectedProperty(propertyId);
  const choices = useQuery({
    queryKey: scope.key("home-property-choices", horizonDays),
    enabled,
    queryFn: ({ signal }) =>
      homePropertyChoices(horizonDays, [scope.workspaceId, scope.runtimeEpoch], signal),
  });
  const items = choices.data ?? [];
  return (
    <div className="home-property-filter">
      <label className="ui-sr-only" htmlFor={`${id}-property`}>
        Property
      </label>
      <select
        id={`${id}-property`}
        name="propertyId"
        value={propertyId ?? ""}
        aria-busy={choices.isFetching}
        onChange={(event) => {
          event.stopPropagation();
          event.currentTarget.form?.requestSubmit();
        }}
      >
        <option value="">All properties</option>
        {propertyId && !items.some((item) => item.id === propertyId) && (
          <option value={propertyId} hidden>
            {selected.data?.displayName ?? "Selected property"}
            {choices.data && !choices.isFetching && !choices.error ? " · No Home items" : ""}
          </option>
        )}
        {items.map((item) => (
          <option key={item.id} value={item.id}>
            {item.displayName}
            {item.archived ? " · Archived" : ""}
          </option>
        ))}
      </select>
      {choices.isFetching && (
        <p role="status" className="ui-sr-only">
          Loading properties…
        </p>
      )}
      {choices.data && !choices.isFetching && !choices.error && items.length === 0 && (
        <p role="status">No properties have Home items for this horizon.</p>
      )}
      {choices.error && <p role="alert">Property choices unavailable. Try again.</p>}
      {selected.error && propertyId && <p role="alert">Selected property name unavailable.</p>}
      {choices.error && (
        <button type="button" onClick={() => void choices.refetch()}>
          Retry properties
        </button>
      )}
    </div>
  );
}
