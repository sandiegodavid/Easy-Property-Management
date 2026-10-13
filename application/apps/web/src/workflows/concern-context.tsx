import { useQuery } from "@tanstack/react-query";
import { api } from "@epm/contracts";
import { record, scalar } from "@epm/contracts/workflows";
import { useWorkspace } from "../app/workspace-gate";
import { Facts, readResult } from "./reads";

export function concernProblem(values: Record<string, unknown>) {
  if (["lease", "tenant", "vacancy"].includes(scalar(values.concernType)) && !values.spaceId)
    return "Select a Space from the owning Property for this concern type.";
  if (["lease", "tenant"].includes(scalar(values.concernType)) && !values.leaseId)
    return "Lease and Tenant concerns require a Lease from the selected Space.";
  if (values.concernType === "tenant" && !values.tenantPartyId)
    return "Select a participant's existing Tenant identity for a Tenant concern.";
  if (
    values.historicalSelectionConfirmed === true &&
    !scalar(values.historicalSelectionReason, "").trim()
  )
    return "Historical selection requires a backdated raised time and a reason.";
  if (values.duplicateConfirmed === true && !scalar(values.duplicateReason, "").trim())
    return "Give a reason for an independent concern; candidates are never merged automatically.";
  const follow = record(values.followUp);
  if (!!follow.dueAtUtc !== !!follow.dueTimezone)
    return "Follow-up deadline and IANA time zone must be supplied together.";
  return undefined;
}

export function ConcernContext({
  values,
  source,
}: {
  values: Record<string, unknown>;
  source: Record<string, unknown>;
}) {
  const { scope } = useWorkspace();
  const propertyId = scalar(values.propertyId ?? source.propertyId, "");
  const ownerId = scalar(values.ownerPartyId ?? source.ownerPartyId, "");
  const leaseId = scalar(values.leaseId ?? source.leaseId, "");
  const property = useQuery({
    queryKey: scope.key("concern-property-context", propertyId),
    enabled: !!propertyId,
    queryFn: async ({ signal }) =>
      readResult(
        await api.GET("/api/properties/{property_id}", {
          signal,
          params: { path: { property_id: propertyId } },
        }),
      ),
  });
  const owner = useQuery({
    queryKey: scope.key("concern-owner-context", ownerId),
    enabled: !!ownerId,
    queryFn: async ({ signal }) =>
      readResult(
        await api.GET("/api/parties/{party_id}", {
          signal,
          params: { path: { party_id: ownerId } },
        }),
      ),
  });
  const lease = useQuery({
    queryKey: scope.key("concern-lease-context", leaseId),
    enabled: !!leaseId,
    queryFn: async ({ signal }) =>
      readResult(
        await api.GET("/api/leases/{lease_id}", {
          signal,
          params: { path: { lease_id: leaseId } },
        }),
      ),
  });
  return (
    <section aria-label="Owner concern review">
      <p>
        A concern records a client Owner's claim, not occupancy, paid income or a verified repair.
        Completing a Task does not resolve the concern; resolving it does not change its Lease,
        Tenant or Property.
      </p>
      <p>
        Eligibility is checked at the raised instant in the Property's IANA zone. Current source
        state is context, not a rewrite of retained snapshots. Ended relationships and archived
        identities require explicit historical confirmation/reason for genuinely backdated
        selection. Local operator ownership never creates an Owner Party.
      </p>
      {property.data && (
        <p>
          {property.data.displayName} · {property.data.timeZone} · Current ownership:{" "}
          {property.data.ownershipContext}. Historical relationships may not appear in this current
          view.
        </p>
      )}
      {owner.data && (
        <p>
          Selected Owner: {owner.data.displayName} ·{" "}
          {owner.data.archivedAt
            ? "Archived — historical selection required"
            : "Active identity; server checks date-effective ownership"}
        </p>
      )}
      {lease.data && (
        <Facts
          value={lease.data}
          fields={["id", "spaceId", "status", "occupancyStartsOn", "actualMoveOutOn"]}
        />
      )}
      {[property.error, owner.error, lease.error].filter(Boolean).map((error, index) => (
        <p role="alert" key={index}>
          Source context unavailable: {error?.message}
        </p>
      ))}
      <p>
        General rental may be Property-wide. Vacancy requires a matching Space; Lease and Tenant
        concerns require its Lease, and Tenant concerns also require that Lease's participant. The
        server rechecks every reference together.
      </p>
      {!!values.replacesConcernId && (
        <p>
          This creates a replacement of one dismissed concern. Its predecessor and audit history
          remain retained; correct the target fields explicitly.
        </p>
      )}
      {concernProblem(values) && <p role="alert">{concernProblem(values)}</p>}
    </section>
  );
}
