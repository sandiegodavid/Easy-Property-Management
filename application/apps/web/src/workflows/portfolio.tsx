import { useQuery } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "@epm/contracts";
import { workflows, scalar } from "@epm/contracts/workflows";
import type { components } from "@epm/contracts/generated";
import { useWorkspace } from "../app/workspace-gate";
import { CommandLinks, CommandLoader } from "./command";
import { Facts, History, readResult, IdentityLookup } from "./reads";
import { useState } from "react";
import type { Choice } from "./fields";

type Space = components["schemas"]["SpaceStatusResponse"];
export function PortfolioEntry() {
  return (
    <section aria-label="Property setup">
      <CommandLinks keys={["portfolio.property.create"]} title="Set up property" />
      <p>
        Create a minimal property, then record occupancy, availability, contacts and ownership.
        Coverage prompts identify later lease and rent steps.
      </p>
      <Link to="/parties">Shared identities and tenants</Link>
    </section>
  );
}
export function PortfolioRecord({ id }: { id: string }) {
  const { scope } = useWorkspace();
  const result = useQuery({
    queryKey: scope.key("portfolio-record", id),
    queryFn: async ({ signal }) =>
      readResult(
        await api.GET("/api/properties/{property_id}", {
          signal,
          params: { path: { property_id: id } },
        }),
      ),
  });
  if (result.isPending) return <p role="status">Loading property setup…</p>;
  if (result.error) return <p role="alert">{result.error.message}</p>;
  const item = result.data;
  return (
    <section aria-label="Property setup" className="context-section">
      <h3>{item.displayName}: setup and history</h3>
      <Facts
        value={item}
        fields={[
          "propertyType",
          "inventoryLayout",
          "status",
          "propertyRevision",
          "addressLine1",
          "addressLine2",
          "city",
          "region",
          "postalCode",
          "countryCode",
          "timeZone",
          "notes",
          "asOf",
          "effectiveLocalDate",
        ]}
      />
      <CommandLinks
        target={id}
        keys={
          item.status === "archived"
            ? ["portfolio.property.restore"]
            : [
                "portfolio.property.patch",
                "portfolio.ownerships.replace",
                ...(item.inventoryLayout === "office_suites" ? ["portfolio.space.create"] : []),
                "portfolio.property.archive",
              ]
        }
        title="Property actions"
      />
      <h4>Ownership intervals</h4>
      {item.ownerships.map((owner) => (
        <article key={owner.id}>
          <p>
            {owner.ownerKind === "local_operator" ? "Local operator" : owner.party?.displayName} ·{" "}
            {owner.startsOn} through {owner.endsOn ?? "ongoing"}
          </p>
          {owner.partyId && (
            <Link to={`/parties?identity=${owner.partyId}`}>View owner identity</Link>
          )}
        </article>
      ))}
      <h4>Spaces</h4>
      {item.spaces.map((space) => (
        <SpaceRecord key={space.id} space={space} propertyId={id} />
      ))}
      <History kind="property" id={id} />
    </section>
  );
}
function SpaceRecord({ space, propertyId }: { space: Space; propertyId: string }) {
  return (
    <article className="context-section">
      <h4>{space.displayName}</h4>
      <Facts
        value={space}
        fields={["spaceKind", "status", "revision", "suiteOrFloor", "notes", "effectiveLocalDate"]}
      />
      <p>
        Current occupancy: {space.currentOccupancy.occupancyStatus} · Source:{" "}
        {space.currentOccupancy.sourceKind}
      </p>
      <Facts
        value={space.availability}
        fields={["effectiveAvailabilityStatus", "availabilityStatus", "availableOn", "sourceKind"]}
      />
      {space.attentionReasons.map((reason, index) => (
        <p key={index}>{reason.code}</p>
      ))}
      <CommandLinks
        target={propertyId}
        child={space.id}
        keys={
          space.status === "archived"
            ? ["portfolio.space.restore"]
            : ["portfolio.space.patch", "portfolio.space.archive"]
        }
        title={`Inventory actions for ${space.displayName}`}
      />
      {space.status === "active" && (
        <Link to={`/leasing?workflow=lease.create&spaceId=${space.id}`}>
          Start lease draft for {space.displayName}
        </Link>
      )}
      {space.status === "active" && (
        <CommandLinks
          target={space.id}
          keys={[
            "portfolio.occupancy.change",
            "portfolio.availability.change",
            "portfolio.space.classify",
          ]}
          title={`Status actions for ${space.displayName}`}
        />
      )}
      {space.currentOccupancy.sourceKind === "manual" && (
        <CommandLinks
          target={space.id}
          child={space.currentOccupancy.id}
          keys={["portfolio.occupancy.correct"]}
          title={`Correct current occupancy for ${space.displayName}`}
        />
      )}
      <details>
        <summary>Scheduled occupancy and corrections</summary>
        {space.scheduledOccupancyTimeline.map((period) => (
          <article key={period.id}>
            <Facts
              value={period}
              fields={["occupancyStatus", "startsOn", "endsOn", "sourceKind", "note"]}
            />
            {period.sourceKind === "manual" && (
              <CommandLinks
                target={space.id}
                child={period.id}
                keys={[
                  "portfolio.occupancy.cancel",
                  "portfolio.occupancy.replace",
                  "portfolio.occupancy.reschedule",
                  "portfolio.occupancy.correct",
                ]}
                title={`Scheduled transition ${period.startsOn}`}
              />
            )}
          </article>
        ))}
      </details>
      <History kind="space" id={space.id} />
    </article>
  );
}

export function PortfolioCommand() {
  const [params] = useSearchParams();
  const definition = workflows.find((item) => item.formKey === params.get("workflow"));
  const target = params.get("target") ?? undefined;
  const { scope } = useWorkspace();
  const resume = params.get("resume");
  const recovery = useQuery({
    queryKey: scope.key("workflow-recovery", resume),
    enabled: !!resume,
    queryFn: async ({ signal }) =>
      readResult(
        await api.GET("/api/operator/recovery/{record_id}", {
          signal,
          params: { path: { record_id: resume! } },
        }),
      ),
  });
  const child =
    params.get("child") ??
    (definition?.childKey && recovery.data
      ? scalar(recovery.data.payload[definition.childKey])
      : undefined);
  const [identities, setIdentities] = useState<Choice[]>([]);
  const [session] = useState(() => crypto.randomUUID());
  const source = useQuery({
    queryKey: scope.key("portfolio-command-source", session, definition?.sourceKind, target),
    staleTime: Infinity,
    refetchOnWindowFocus: false,
    enabled: !!target && !!definition?.sourceKind && (!resume || !!recovery.data),
    queryFn: async ({ signal }) => {
      if (definition?.sourceKind === "space") {
        const space = readResult(
          await api.GET("/api/spaces/{space_id}/status", {
            signal,
            params: { path: { space_id: target! } },
          }),
        );
        return { revision: space.revision, initial: {}, space, property: null };
      }
      const property = readResult(
        await api.GET("/api/properties/{property_id}", {
          signal,
          params: { path: { property_id: target! } },
        }),
      );
      if (child && !property.spaces.some((item) => item.id === child))
        throw new Error("This space does not belong to the selected property.");
      return {
        revision: property.propertyRevision,
        initial:
          definition?.formKey === "portfolio.property.patch"
            ? {
                displayName: property.displayName,
                addressLine1: property.addressLine1,
                city: property.city,
                countryCode: property.countryCode,
              }
            : {},
        property,
        space: null,
      };
    },
  });
  if (!definition || !definition.formKey.startsWith("portfolio."))
    return <p role="alert">Unknown Portfolio workflow.</p>;
  if (resume && recovery.isPending) return <p role="status">Loading unfinished form…</p>;
  if (recovery.error) return <p role="alert">{recovery.error.message}</p>;
  if (definition.sourceKind && !target) return <p role="alert">Select the owning record first.</p>;
  if (target && source.isPending) return <p role="status">Loading displayed revision…</p>;
  if (source.error) return <p role="alert">{source.error.message}</p>;
  const initial: Record<string, unknown> =
    definition.formKey === "portfolio.property.create"
      ? { propertyType: "single_family_home", ownerships: [{ ownerKind: "local_operator" }] }
      : { ...source.data?.initial };
  if (definition.formKey === "portfolio.occupancy.correct") {
    const space = source.data?.space;
    const period =
      space && space.currentOccupancy.id === child
        ? space.currentOccupancy
        : space?.scheduledOccupancyTimeline.find((item) => item.id === child);
    if (!period)
      return <p role="alert">This occupancy period is no longer in the displayed timeline.</p>;
    initial.occupancy = { occupancyStatus: period.occupancyStatus, effectiveOn: period.startsOn };
  }
  const owners =
    source.data?.property?.ownerships.flatMap((item) =>
      item.partyId && item.party ? [{ id: item.partyId, label: item.party.displayName }] : [],
    ) ?? [];
  return (
    <>
      <p>
        Effective dates use the property time zone. Inventory uses the Property revision; manual
        status uses the independent Space revision. Lease-owned occupancy must be changed through
        Leasing.
      </p>
      {source.data?.space && (
        <Facts
          value={source.data.space}
          fields={["displayName", "effectiveLocalDate", "revision", "asOf"]}
        />
      )}
      {["portfolio.property.create", "portfolio.ownerships.replace"].includes(
        definition.formKey,
      ) && (
        <IdentityLookup
          onSelect={(id, name) =>
            setIdentities((current) => [
              ...current.filter((item) => item.id !== id),
              { id, label: name },
            ])
          }
        />
      )}
      <CommandLoader
        definition={definition}
        sourceId={target}
        childId={child}
        revision={source.data?.revision ?? 0}
        initial={initial}
        choices={{ partyId: [...owners, ...identities] }}
        returnTo={
          source.data?.space ? `/properties/${source.data.space.propertyId}/units` : undefined
        }
      />
    </>
  );
}
