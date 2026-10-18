import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api } from "@epm/contracts";
import { record, scalar } from "@epm/contracts/workflows";
import { useWorkspace } from "../app/workspace-gate";
import { Facts, readResult } from "./reads";

export function ConcernOwnerSearch({
  disabled,
  onSelect,
}: {
  disabled: boolean;
  onSelect: (id: string, name: string) => void;
}) {
  const { scope } = useWorkspace();
  const [input, setInput] = useState("");
  const [search, setSearch] = useState("");
  useEffect(() => {
    const timer = setTimeout(() => setSearch(input.trim()), 250);
    return () => clearTimeout(timer);
  }, [input]);
  const owners = useQuery({
    queryKey: scope.key("concern-owner-search", search),
    enabled: search.length >= 2,
    queryFn: async ({ signal }) =>
      readResult(
        await api.GET("/api/parties/selection", {
          signal,
          params: { query: { search, includeArchived: true, limit: 25 } },
        }),
      ),
  });
  return (
    <details className="maintenance-create-section">
      <summary>Find a former or different owner</summary>
      <p>
        Search for an existing person or organization. Ownership at the raised time is checked when
        you save.
      </p>
      <label>
        Find owner by name
        <input
          value={input}
          maxLength={200}
          disabled={disabled}
          onChange={(event) => setInput(event.target.value)}
        />
      </label>
      {owners.isFetching && <p role="status">Finding owners…</p>}
      {owners.error && <p role="alert">Owner search is unavailable. Try again.</p>}
      {search === input.trim() && owners.data && (
        <>
          <p>Showing up to 25 matching identities. Refine the name to narrow the results.</p>
          <ul>
            {owners.data.items.map((owner) => (
              <li key={owner.id}>
                <button
                  type="button"
                  disabled={disabled}
                  onClick={() => onSelect(owner.id, owner.displayName)}
                >
                  Use {owner.displayName}
                  {owner.archivedAt ? " (archived)" : ""}
                </button>
              </li>
            ))}
          </ul>
          {!owners.data.items.length && <p>No matching identities.</p>}
        </>
      )}
    </details>
  );
}

export function concernProblem(values: Record<string, unknown>) {
  if (["lease", "tenant", "vacancy"].includes(scalar(values.concernType)) && !values.spaceId)
    return "Select the home, unit or suite for this concern type.";
  if (["lease", "tenant"].includes(scalar(values.concernType)) && !values.leaseId)
    return "Lease and tenant concerns require a lease for the selected rental.";
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
    <section aria-label="Owner concern review" className="maintenance-create-section">
      <h3>Check the selected context</h3>
      <p>
        Choose an owner of the property at the time the concern was raised. For a backdated concern
        involving a former owner or tenant, confirm the historical selection and give a reason under
        additional context.
      </p>
      {property.data && (
        <p>
          {property.data.displayName} · {property.data.timeZone}
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
        <Facts value={lease.data} fields={["status", "occupancyStartsOn", "actualMoveOutOn"]} />
      )}
      {[property.error, owner.error, lease.error].filter(Boolean).map((error, index) => (
        <p role="alert" key={index}>
          Source context unavailable: {error?.message}
        </p>
      ))}
      <p>
        General rental concerns can cover the whole property. For a vacancy, choose a rental; for a
        lease or tenant concern, also choose its lease and, where relevant, its tenant.
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
