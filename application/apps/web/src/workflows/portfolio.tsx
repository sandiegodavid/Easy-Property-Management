import { useQuery } from "@tanstack/react-query";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { api } from "@epm/contracts";
import { workflows, scalar } from "@epm/contracts/workflows";
import type { components } from "@epm/contracts/generated";
import { useWorkspace } from "../app/workspace-gate";
import { CommandLinks, CommandLoader, workflowUrl } from "./command";
import { Facts, History, readResult, IdentityLookup } from "./reads";
import { useState } from "react";
import type { Choice } from "./fields";
import { PortfolioStatusSummary, statusLabel } from "./portfolio-status";
import { PageAsOf } from "../shared/page-as-of";
import { propertyUnitsLabel, rentableUnitLabel } from "../shared/property-labels";

type Space = components["schemas"]["SpaceStatusResponse"];
export function PortfolioEntry() {
  return (
    <section aria-label="Property setup">
      <PortfolioStatusSummary />
    </section>
  );
}
export function PropertyCreateButton() {
  const { scope } = useWorkspace();
  const navigate = useNavigate();
  const location = useLocation();
  return (
    <button
      type="button"
      disabled={!scope.canWrite}
      onClick={() => {
        void navigate(workflowUrl("portfolio.property.create"), {
          state: { returnTo: location.pathname + location.search },
        });
      }}
    >
      Create property
    </button>
  );
}
export function PortfolioRecord({ id, view = "setup" }: { id: string; view?: "setup" | "spaces" }) {
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
  if (view === "spaces") {
    const summary = item.statusSummary;
    const unitLabel = propertyUnitsLabel(item.inventoryLayout);
    return (
      <section aria-label={`Property ${unitLabel.toLowerCase()}`} className="property-spaces">
        <PageAsOf asOf={item.asOf} priority={1} />
        <div className="property-spaces-intro">
          <p>
            {unitLabel === "Suites"
              ? "Manage occupancy and leasing status for each suite."
              : `Manage occupancy and leasing status for this ${unitLabel.toLowerCase()}.`}
          </p>
          {item.status === "active" && item.inventoryLayout === "office_suites" && (
            <CommandLinks
              target={id}
              keys={["portfolio.space.create"]}
              title="Add suite"
              labels={{ "portfolio.space.create": "Add suite" }}
            />
          )}
        </div>
        <dl className="property-space-summary">
          {[
            [
              unitLabel === "Suites" ? "Active suites" : `Active ${unitLabel.toLowerCase()}`,
              summary.activeSpaceCount,
            ],
            ["Occupied", summary.occupiedCount],
            ["Vacant", summary.vacantCount],
            ["Needs classification", summary.unknownOccupancyCount],
            ["Open for leasing now", summary.availableNowCount],
            ["Open for leasing later", summary.availableLaterCount],
          ].map(([name, count]) => (
            <div key={name}>
              <dt>{name}</dt>
              <dd>{count}</dd>
            </div>
          ))}
        </dl>
        <div className="property-space-grid">
          {item.spaces.map((space) => (
            <SpaceRecord
              key={space.id}
              space={space}
              propertyId={id}
              allowSuiteLifecycle={item.inventoryLayout === "office_suites"}
            />
          ))}
        </div>
        {!item.spaces.length && <p>No {unitLabel.toLowerCase()} recorded.</p>}
      </section>
    );
  }
  return (
    <section aria-label="Property setup" className="context-section property-details">
      <PageAsOf asOf={item.asOf} priority={1} />
      <section className="property-details-panel" aria-label="Property information">
        <header className="property-setup-heading">
          <h3>Property setup</h3>
          {item.status !== "archived" && (
            <CommandLinks
              target={id}
              keys={["portfolio.property.patch"]}
              title="Edit property"
              collapsible={false}
              asButtons
            />
          )}
        </header>
        <Facts value={item} fields={["propertyType", "inventoryLayout", "propertyRevision"]} />
        {item.notes && <p className="property-details-notes">{item.notes}</p>}
        {item.status !== "archived" && (
          <CommandLinks
            target={id}
            keys={[
              "portfolio.ownerships.replace",
              ...(item.inventoryLayout === "office_suites" ? ["portfolio.space.create"] : []),
            ]}
            title="Property actions"
            labels={{ "portfolio.space.create": "Add suite" }}
            collapsible={false}
            asButtons
          />
        )}
      </section>
      <div className="property-setup-lifecycle">
        <CommandLinks
          target={id}
          keys={[
            item.status === "archived"
              ? "portfolio.property.restore"
              : "portfolio.property.archive",
          ]}
          title="Property lifecycle"
          collapsible={false}
          asButtons
        />
      </div>
      <div className="property-details-panel">
        <History kind="property" id={id} presentation="timeline" />
      </div>
    </section>
  );
}
function SpaceRecord({
  space,
  propertyId,
  allowSuiteLifecycle,
}: {
  space: Space;
  propertyId: string;
  allowSuiteLifecycle: boolean;
}) {
  const { scope } = useWorkspace();
  const navigate = useNavigate();
  const location = useLocation();
  const unit = rentableUnitLabel(space.spaceKind);
  const attentionLabels = {
    availability_unknown: "Leasing status hasn’t been classified.",
    occupancy_unknown: "Occupancy hasn’t been classified.",
    source_conflict: "Status records conflict and need review.",
    missing_status_record: "A required status record is missing.",
  };
  return (
    <article className="property-space-card" aria-label={space.displayName}>
      <header className="property-space-header">
        <div>
          <div className="property-space-title-row">
            <h4>{space.displayName}</h4>
            {space.status === "active" && (
              <>
                <button
                  type="button"
                  disabled={!scope.canWrite}
                  onClick={() => {
                    void navigate(workflowUrl("portfolio.space.patch", propertyId, space.id), {
                      state: { returnTo: location.pathname + location.search },
                    });
                  }}
                >
                  Edit {unit}
                </button>
                <button
                  type="button"
                  disabled={!scope.canWrite}
                  onClick={() => {
                    void navigate(`/leasing?workflow=lease.create&spaceId=${space.id}`, {
                      state: { returnTo: location.pathname + location.search },
                    });
                  }}
                >
                  Start lease draft
                </button>
              </>
            )}
          </div>
          {(statusLabel(space.spaceKind).toLowerCase() !== space.displayName.toLowerCase() ||
            space.suiteOrFloor) && (
            <p>
              {statusLabel(space.spaceKind)}
              {space.suiteOrFloor && ` · ${space.suiteOrFloor}`}
            </p>
          )}
        </div>
        <span className="property-space-lifecycle">{statusLabel(space.status)}</span>
      </header>
      <dl className="property-space-status">
        <div>
          <dt>Occupancy</dt>
          <dd>
            {statusLabel(space.currentOccupancy.occupancyStatus)}
            {space.currentOccupancy.sourceKind === "lease" && space.currentOccupancy.sourceId && (
              <Link
                className="property-space-lease"
                to={`/leases/${space.currentOccupancy.sourceId}`}
              >
                View lease
              </Link>
            )}
            {space.currentOccupancy.sourceKind === "lease" && (
              <span className="property-space-note">Managed by lease</span>
            )}
            {space.status === "active" && space.currentOccupancy.sourceKind === "manual" && (
              <CommandLinks
                collapsible={false}
                asButtons
                target={space.id}
                child={space.currentOccupancy.id}
                keys={["portfolio.occupancy.change", "portfolio.occupancy.correct"]}
                title="Occupancy actions"
                labels={{ "portfolio.occupancy.correct": "Correct recorded occupancy" }}
              />
            )}
          </dd>
        </div>
        <div>
          <dt className="property-space-status-label">
            Leasing status
            {space.status === "active" && space.availability.sourceKind === "manual" && (
              <button
                type="button"
                disabled={!scope.canWrite}
                className="property-space-primary"
                onClick={() => {
                  void navigate(workflowUrl("portfolio.availability.change", space.id), {
                    state: { returnTo: location.pathname + location.search },
                  });
                }}
              >
                Change leasing status
              </button>
            )}
          </dt>
          <dd>
            {statusLabel(space.availability.effectiveStatus)}
            {space.availability.effectiveStatus === "available_on" &&
              space.availability.availableOn && (
                <time className="property-space-date" dateTime={space.availability.availableOn}>
                  {space.availability.availableOn}
                </time>
              )}
            {space.availability.note && (
              <span className="property-space-note">{space.availability.note}</span>
            )}
            {space.availability.recordedStatus !== space.availability.effectiveStatus && (
              <span className="property-space-note">
                Recorded leasing intention: {statusLabel(space.availability.recordedStatus)}
              </span>
            )}
          </dd>
        </div>
      </dl>
      {space.notes && <p className="property-space-note">{space.notes}</p>}
      {space.attentionReasons.length > 0 && (
        <div className="property-space-attention">
          <strong>Needs review</strong>
          <ul>
            {space.attentionReasons.map((reason, index) => (
              <li key={index}>{attentionLabels[reason.code]}</li>
            ))}
          </ul>
          {space.status === "active" && (
            <button
              type="button"
              disabled={!scope.canWrite}
              className="property-space-primary"
              onClick={() => {
                void navigate(workflowUrl("portfolio.space.classify", space.id), {
                  state: { returnTo: location.pathname + location.search },
                });
              }}
            >
              Review status for {space.displayName}
            </button>
          )}
        </div>
      )}
      {allowSuiteLifecycle && space.spaceKind === "office_suite" && (
        <div className="property-space-actions">
          <CommandLinks
            collapsible={false}
            asButtons
            target={propertyId}
            child={space.id}
            keys={
              space.status === "archived"
                ? ["portfolio.space.restore"]
                : ["portfolio.space.archive"]
            }
            title={space.status === "archived" ? `Restore ${unit}` : `Archive ${unit}`}
            labels={{
              "portfolio.space.patch": `Edit ${unit}`,
              "portfolio.space.archive": `Archive ${unit}`,
              "portfolio.space.restore": `Restore ${unit}`,
            }}
          />
        </div>
      )}
      {space.scheduledOccupancyTimeline.length > 0 && (
        <section className="property-space-scheduled" aria-label="Scheduled occupancy">
          <h5>Scheduled occupancy</h5>
          {space.scheduledOccupancyTimeline.map((period) => (
            <article key={period.id}>
              <p>
                <strong>{statusLabel(period.occupancyStatus)}</strong> from{" "}
                <time dateTime={period.startsOn}>{period.startsOn}</time>
                {period.endsOn && (
                  <>
                    {" "}
                    until <time dateTime={period.endsOn}>{period.endsOn}</time>
                  </>
                )}
              </p>
              {period.note && <p className="property-space-note">{period.note}</p>}
              {period.sourceKind === "lease" && (
                <p className="property-space-note">Managed by lease</p>
              )}
              {space.status === "active" && period.sourceKind === "manual" && (
                <CommandLinks
                  collapsible={false}
                  asButtons
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
        </section>
      )}
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
        const property = [
          "portfolio.space.classify",
          "portfolio.availability.change",
          "portfolio.occupancy.change",
        ].includes(definition.formKey)
          ? readResult(
              await api.GET("/api/properties/{property_id}", {
                signal,
                params: { path: { property_id: space.propertyId } },
              }),
            )
          : null;
        return { revision: space.revision, initial: {}, space, property };
      }
      const property = readResult(
        await api.GET("/api/properties/{property_id}", {
          signal,
          params: { path: { property_id: target! } },
        }),
      );
      if (child && !property.spaces.some((item) => item.id === child))
        throw new Error("This rental does not belong to the selected property.");
      const rental = property.spaces.find((item) => item.id === child);
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
            : definition?.formKey === "portfolio.space.patch" && rental
              ? {
                  displayName: rental.displayName,
                  suiteOrFloor: rental.suiteOrFloor,
                  notes: rental.notes,
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
  const classifying = definition.formKey === "portfolio.space.classify";
  const changingLeasing = definition.formKey === "portfolio.availability.change";
  const changingOccupancy = definition.formKey === "portfolio.occupancy.change";
  const statusCommand = classifying || changingLeasing || changingOccupancy;
  const editingRental = definition.formKey === "portfolio.space.patch";
  const archivingRental = definition.formKey === "portfolio.space.archive";
  const selectedUnit =
    source.data?.space ?? source.data?.property?.spaces.find((item) => item.id === child);
  const unit = selectedUnit ? rentableUnitLabel(selectedUnit.spaceKind) : "suite";
  const unitCommandTitles: Record<string, string> = {
    "portfolio.space.create": "Add suite",
    "portfolio.space.patch": `Edit ${unit}`,
    "portfolio.space.archive": `Archive ${unit}`,
    "portfolio.space.restore": `Restore ${unit}`,
    "portfolio.space.classify": `Classify ${unit}`,
  };
  const formDefinition =
    changingLeasing || changingOccupancy
      ? {
          ...definition,
          title: changingLeasing ? "Change leasing status" : definition.title,
          schema: {
            ...definition.schema,
            properties: {
              ...(changingLeasing
                ? {
                    availabilityStatus: definition.schema.properties!.availabilityStatus,
                    availableOn: definition.schema.properties!.availableOn,
                  }
                : {
                    occupancyStatus: definition.schema.properties!.occupancyStatus,
                    effectiveOn: definition.schema.properties!.effectiveOn,
                  }),
              note: definition.schema.properties!.note,
              ...definition.schema.properties,
            },
          },
        }
      : unitCommandTitles[definition.formKey]
        ? { ...definition, title: unitCommandTitles[definition.formKey] }
        : definition;
  return (
    <div
      className={
        statusCommand || editingRental || archivingRental
          ? `space-status-command${archivingRental ? " space-archive-command space-status-single-form" : editingRental ? " space-edit-command space-status-single-form" : changingLeasing ? " space-leasing-command space-status-single-form" : changingOccupancy ? " space-occupancy-command space-status-single-form" : ""}`
          : undefined
      }
    >
      {(editingRental || archivingRental) && source.data?.property && selectedUnit && (
        <>
          <Link to={`/properties/${source.data.property.id}/units`}>
            ← Back to {source.data.property.displayName}
          </Link>
          <section
            className="space-classification-context"
            aria-label="Selected property and rental"
          >
            <p className="space-classification-property">{source.data.property.displayName}</p>
            <h2>{selectedUnit.displayName}</h2>
            <dl>
              <div>
                <dt>Current lifecycle</dt>
                <dd>{statusLabel(selectedUnit.status)}</dd>
              </div>
              <div>
                <dt>Current occupancy</dt>
                <dd>{statusLabel(selectedUnit.currentOccupancy.occupancyStatus)}</dd>
              </div>
              <div>
                <dt>Current leasing status</dt>
                <dd>{statusLabel(selectedUnit.availability.effectiveStatus)}</dd>
              </div>
            </dl>
            {archivingRental ? (
              <div className="space-archive-notice">
                <h3>Retire this {unit}, not the property</h3>
                <p>
                  The property and its other suites remain active. Existing records and history are
                  retained; archiving does not delete them.
                </p>
                <p>
                  For temporary vacancy or a pause in leasing, change occupancy or leasing status
                  instead. An occupied suite, a suite with scheduled occupancy changes, or the
                  property’s last active suite cannot be archived.
                </p>
              </div>
            ) : (
              <p>
                Update the name, suite or floor, and notes. Occupancy, leasing status and lease
                records stay unchanged.
              </p>
            )}
          </section>
        </>
      )}
      {statusCommand && source.data?.space && (
        <>
          <Link to={`/properties/${source.data.space.propertyId}/units`}>
            ← Back to {source.data.property?.displayName ?? "property"}
          </Link>
          <section
            className="space-classification-context"
            aria-label="Selected property and rental"
          >
            <p className="space-classification-property">{source.data.property?.displayName}</p>
            <h2>{source.data.space.displayName}</h2>
            <dl>
              <div>
                <dt>Current occupancy</dt>
                <dd>{statusLabel(source.data.space.currentOccupancy.occupancyStatus)}</dd>
              </div>
              <div>
                <dt>Current leasing status</dt>
                <dd>{statusLabel(source.data.space.availability.effectiveStatus)}</dd>
                {source.data.space.availability.effectiveStatus === "available_on" &&
                  source.data.space.availability.availableOn && (
                    <dd>
                      <time dateTime={source.data.space.availability.availableOn}>
                        {source.data.space.availability.availableOn}
                      </time>
                    </dd>
                  )}
              </div>
            </dl>
            <p>
              {classifying
                ? "Set only the information that needs classification. Leave an already classified status unchanged."
                : changingOccupancy
                  ? `Occupancy records whether this ${unit} is occupied or vacant. Changing it does not change leasing status or an existing lease. Lease-managed occupancy must be changed through Leasing.`
                  : `Leasing status describes whether this ${unit} is open to a new tenancy. Changing it does not change occupancy or an existing lease.`}
            </p>
          </section>
        </>
      )}
      {definition.formKey === "portfolio.property.create" && (
        <>
          <Link to="/properties">← Back to Properties</Link>
          <p>
            Create a minimal property, then record occupancy, leasing status, contacts and
            ownership. Coverage prompts identify later lease and rent steps.
          </p>
        </>
      )}
      {!statusCommand && !editingRental && !archivingRental && (
        <p>
          Effective dates use the property time zone. Inventory uses the Property revision; manual
          status uses its own status revision. Lease-owned occupancy must be changed through
          Leasing.
        </p>
      )}
      {source.data?.space && (
        <>
          <PageAsOf asOf={source.data.space.asOf} />
          {!statusCommand && (
            <Facts
              value={source.data.space}
              fields={["displayName", "effectiveLocalDate", "revision"]}
            />
          )}
          {statusCommand && (
            <p className="space-classification-date">
              {classifying ? "Classification takes effect today" : "Property-local date"}:{" "}
              {source.data.space.effectiveLocalDate} · {source.data.property?.timeZone}.
            </p>
          )}
        </>
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
        definition={formDefinition}
        sourceId={target}
        childId={child}
        revision={source.data?.revision ?? 0}
        initial={initial}
        choices={{ partyId: [...owners, ...identities] }}
        returnTo={
          source.data?.space
            ? `/properties/${source.data.space.propertyId}/units`
            : (editingRental || archivingRental) && source.data?.property
              ? `/properties/${source.data.property.id}/units`
              : undefined
        }
      />
    </div>
  );
}
