import { createContext, useContext } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@epm/contracts";
import { record, scalar } from "@epm/contracts/workflows";
import { useWorkspace } from "../app/workspace-gate";
import { readResult } from "../workflows/reads";
import { browserTimeZone } from "./zoned-date-time";

export const FormTimeZone = createContext<string | undefined>(undefined);

export function useDefaultTimeZone() {
  return useContext(FormTimeZone) || browserTimeZone();
}

// People have no single owning property. Preserve all property identities so a
// conversation spanning properties cannot accidentally choose one of them.
async function propertiesFor(kind: string, id: string, signal: AbortSignal): Promise<string[]> {
  switch (kind) {
    case "property":
      return [id];
    case "space":
      return [
        readResult(
          await api.GET("/api/spaces/{space_id}/status", {
            signal,
            params: { path: { space_id: id } },
          }),
        ).propertyId,
      ];
    case "lease": {
      const lease = readResult(
        await api.GET("/api/leases/{lease_id}", {
          signal,
          params: { path: { lease_id: id } },
        }),
      );
      return propertiesFor("space", lease.spaceId, signal);
    }
    case "maintenance_issue":
      return [
        readResult(
          await api.GET("/api/maintenance-issues/{issue_id}", {
            signal,
            params: { path: { issue_id: id } },
          }),
        ).propertyId,
      ];
    case "owner_concern":
      return [
        readResult(
          await api.GET("/api/owner-concerns/{concern_id}", {
            signal,
            params: { path: { concern_id: id } },
          }),
        ).propertyId,
      ];
    case "communication": {
      const conversation = readResult(
        await api.GET("/api/communications/{communication_id}", {
          signal,
          params: { path: { communication_id: id } },
        }),
      );
      // Communication links cannot recursively establish a property context.
      return (
        await Promise.all(
          conversation.links
            .filter((link) =>
              ["property", "space", "lease", "maintenance_issue", "owner_concern"].includes(
                link.entityType,
              ),
            )
            .map((link) => propertiesFor(link.entityType, link.entityId, signal)),
        )
      ).flat();
    }
    default:
      return [];
  }
}

export function useFormTimeZone(
  values: Record<string, unknown>,
  source: Record<string, unknown>,
  enabled: boolean,
  suppliedZone?: string,
) {
  const { scope } = useWorkspace();
  const context = { ...source, ...values };
  const propertyId = scalar(context.propertyId);
  const relatedId = scalar(context.relatedEntityId);
  const relatedKind = scalar(context.relatedEntityType);
  const links = Array.isArray(context.links) ? context.links.map(record) : [];
  const references = propertyId
    ? [{ entityType: "property", entityId: propertyId }]
    : relatedId
      ? [{ entityType: relatedKind, entityId: relatedId }]
      : links;
  const query = useQuery({
    queryKey: scope.key("form-property-time-zone", references),
    enabled: enabled && !suppliedZone && references.length > 0,
    queryFn: async ({ signal }) => {
      const ids = new Set(
        (
          await Promise.all(
            references.map((link) =>
              propertiesFor(scalar(link.entityType), scalar(link.entityId), signal),
            ),
          )
        )
          .flat()
          .filter(Boolean),
      );
      if (ids.size !== 1) return null;
      return readResult(
        await api.GET("/api/properties/{property_id}", {
          signal,
          params: { path: { property_id: [...ids][0] } },
        }),
      ).timeZone;
    },
  });
  return {
    timeZone: suppliedZone || query.data || browserTimeZone(),
    pending: query.isEnabled && query.isPending,
    error: query.isEnabled ? query.error : null,
  };
}
