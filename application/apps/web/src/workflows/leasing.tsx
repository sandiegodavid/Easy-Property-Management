import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { leaseLastCoveredOn } from "../shared/lease-dates";
import { useParams, useSearchParams } from "react-router-dom";
import { ParentBackLink, SourceWorkflowLink as Link } from "../shared/home-navigation";
import { api } from "@epm/contracts";
import { workflows, record } from "@epm/contracts/workflows";
import type { components } from "@epm/contracts/generated";
import { useWorkspace } from "../app/workspace-gate";
import { CommandLinks, CommandLoader } from "./command";
import { useSaveCompletion } from "./saved-command";
import { History, readResult } from "./reads";
import { InspectionList } from "./inspections";
import { ReadableFacts } from "./readable-facts";
import { LeaseDocuments } from "./lease-documents";
import { MoneyFacts } from "./money-presentation";
import { PageAsOf } from "../shared/page-as-of";
import { useWorkflowRecovery } from "./use-workflow-recovery";

type Lease = components["schemas"]["LeaseResponse"];
export function LeasingWorkspace() {
  const { id } = useParams();
  const [params] = useSearchParams();
  const definition = workflows.find((item) => item.formKey === params.get("workflow"));
  if (definition) return <LeaseCommand key={params.toString()} />;
  return id ? <LeaseRecord id={id} /> : <LeaseDirectory />;
}

function LeaseDirectory() {
  const { scope } = useWorkspace();
  const [params, setParams] = useSearchParams();
  const status = params.get("status") as Lease["status"] | null;
  const propertyId = params.get("propertyId") ?? undefined;
  const cursor = params.get("cursor") ?? undefined;
  const leases = useQuery({
    queryKey: scope.key("lease-directory", status, propertyId, cursor),
    retry: false,
    queryFn: async ({ signal }) => {
      const response = await api.GET("/api/leases/directory", {
        signal,
        params: { query: { status: status ?? undefined, propertyId, cursor, limit: 25 } },
      });
      if (response.response.status === 409)
        throw new DirectoryContinuationConflict(
          "This Lease directory continuation changed or expired. Restart with the selected filters.",
        );
      return readResult(response);
    },
  });
  return (
    <section aria-label="Leasing" className="lease-directory">
      <header className="lease-directory-heading">
        <h2>Leasing</h2>
        <CommandLinks keys={["lease.create"]} title="Lease actions" asButtons collapsible={false} />
      </header>
      <div className="lease-directory-filters">
        <div className="lease-directory-status-filter">
          <label htmlFor="lease-status-filter">Lease status</label>
          <select
            id="lease-status-filter"
            value={status ?? ""}
            onChange={(event) => {
              const next = new URLSearchParams(params);
              next.delete("cursor");
              if (event.target.value) next.set("status", event.target.value);
              else next.delete("status");
              setParams(next, { replace: true, preventScrollReset: true });
            }}
          >
            <option value="">All statuses</option>
            {["draft", "executed", "ended", "terminated", "void"].map((value) => (
              <option key={value} value={value}>
                {leaseStatusLabel(value)}
              </option>
            ))}
          </select>
        </div>
        {propertyId && (
          <p>
            Showing leases for one property.{" "}
            <button
              onClick={() => {
                const next = new URLSearchParams(params);
                next.delete("propertyId");
                next.delete("cursor");
                setParams(next, { preventScrollReset: true });
              }}
            >
              Remove property filter
            </button>
          </p>
        )}
      </div>
      {leases.isPending && <p role="status">Loading leases…</p>}
      {leases.error && <p role="alert">{leases.error.message}</p>}
      {leases.error instanceof DirectoryContinuationConflict && (
        <button
          onClick={() => {
            const next = new URLSearchParams(params);
            next.delete("cursor");
            setParams(next, { preventScrollReset: true });
            if (!cursor) void leases.refetch();
          }}
        >
          Restart Lease directory with these filters
        </button>
      )}
      {leases.error && !(leases.error instanceof DirectoryContinuationConflict) && (
        <button type="button" onClick={() => void leases.refetch()}>
          Retry loading leases
        </button>
      )}
      {leases.data && (
        <>
          <PageAsOf asOf={leases.data.asOf} />
          <p className="lease-directory-count">
            {leases.data.matchingTotal} matching{" "}
            {leases.data.matchingTotal === 1 ? "lease" : "leases"}
          </p>
        </>
      )}
      {leases.data?.items.length === 0 && (
        <div className="lease-directory-empty">
          <h3>No leases match these filters</h3>
          <p>
            {status || propertyId
              ? "Choose another status or remove the property filter."
              : "Create a lease draft to get started."}
          </p>
        </div>
      )}
      <ul className="lease-directory-grid">
        {leases.data?.items.map((lease) => (
          <li key={lease.id}>
            <Link className="lease-directory-card" to={`/leases/${lease.id}/details`}>
              <div className="lease-directory-card-heading">
                <h3>{lease.propertyName ?? "Property unavailable"}</h3>
                <span className={`lease-directory-status lease-status-${lease.status}`}>
                  {leaseStatusLabel(lease.status)}
                </span>
              </div>
              <p className="lease-directory-rental">
                {lease.rentalName ?? "Rental details unavailable"} ·{" "}
                {lease.leaseKind === "commercial" ? "Commercial" : "Residential"}
              </p>
              <dl>
                <div>
                  <dt>Starts</dt>
                  <dd>{leaseDate(lease.contractStartsOn)}</dd>
                </div>
                <div>
                  <dt>Last covered day</dt>
                  <dd>
                    {lease.contractEndsOn
                      ? leaseDate(leaseLastCoveredOn(lease.contractEndsOn)!)
                      : "No fixed end date"}
                  </dd>
                </div>
              </dl>
              <span className="lease-directory-action">
                View lease <span aria-hidden="true">→</span>
              </span>
            </Link>
          </li>
        ))}
      </ul>
      <nav className="lease-directory-pagination" aria-label="Lease pages">
        {leases.data?.nextCursor && (
          <button
            onClick={() => {
              const next = new URLSearchParams(params);
              next.set("cursor", leases.data.nextCursor!);
              setParams(next, { preventScrollReset: true });
            }}
          >
            Next lease page
          </button>
        )}
        {cursor && (
          <button
            onClick={() => {
              const next = new URLSearchParams(params);
              next.delete("cursor");
              setParams(next, { preventScrollReset: true });
            }}
          >
            First lease page
          </button>
        )}
      </nav>
      <footer className="lease-directory-footer">
        <Link to="/leasing?templates=true">Manage inspection templates</Link>
      </footer>
    </section>
  );
}

class DirectoryContinuationConflict extends Error {}

function leaseStatusLabel(value: string) {
  return (
    (
      {
        draft: "Draft",
        executed: "Signed",
        ended: "Ended",
        terminated: "Terminated",
        void: "Voided",
      } as Record<string, string>
    )[value] ?? value
  );
}

function leaseDate(value: string) {
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeZone: "UTC" }).format(
    new Date(`${value}T00:00:00Z`),
  );
}

function LeaseRecord({ id }: { id: string }) {
  const { scope } = useWorkspace();
  const lease = useQuery({
    queryKey: scope.key("lease-record", id),
    queryFn: async ({ signal }) =>
      readResult(
        await api.GET("/api/leases/{lease_id}", { signal, params: { path: { lease_id: id } } }),
      ),
  });
  if (lease.isPending || lease.error)
    return (
      <>
        <ParentBackLink to="/leasing">← Back to Leasing</ParentBackLink>
        {lease.error ? (
          <p role="alert">{lease.error.message}</p>
        ) : (
          <p role="status">Loading lease…</p>
        )}
      </>
    );
  const item = lease.data;
  const lastDay = leaseLastCoveredOn(item.contractEndsOn);
  return (
    <section aria-label="Lease workspace" className="lease-detail">
      <p>
        <ParentBackLink to="/leasing">← Back to Leasing</ParentBackLink>
      </p>
      <header className="lease-detail-heading">
        <h2>{item.leaseKind === "commercial" ? "Commercial" : "Residential"} lease</h2>
        <span className={`lease-directory-status lease-status-${item.status}`}>
          {leaseStatusLabel(item.status)}
        </span>
      </header>
      <LeaseSpaceContext spaceId={item.spaceId} />
      <div className="lease-detail-actions">
        <CommandLinks
          target={id}
          keys={
            item.status === "draft"
              ? ["lease.patch", "lease.term.replace", "lease.participant.add", "lease.execute"]
              : item.status === "executed"
                ? [
                    "lease.end",
                    ...(item.occupancyState === "scheduled" ? ["lease.void"] : []),
                    "lease.renewal.add",
                    "lease.termination.create",
                  ]
                : []
          }
          title="Lease actions"
          labels={{
            "lease.execute": "Record signed lease",
            "lease.patch": "Edit lease",
            "lease.term.replace": "Change rent terms",
            "lease.participant.add": "Add participant",
            "lease.end": "Record lease end",
          }}
          collapsible={false}
        />
      </div>
      {item.status === "draft" && (
        <p className="lease-detail-note">
          Review the tenants, dates and rent terms before recording the signed lease. This also
          updates the rental's occupancy timeline.
        </p>
      )}
      {item.status === "executed" && (
        <p className="lease-detail-note">
          Rent due entries are created separately from signing the lease.{" "}
          <Link
            to={`/money?workflow=finance.rent_expectation.synchronize&target=${id}&leaseId=${id}`}
          >
            Review and create rent schedule
          </Link>
        </p>
      )}
      <div className="lease-detail-grid">
        <section aria-label="Lease milestones" className="lease-detail-panel">
          <h3>Dates and occupancy</h3>
          <dl className="lease-detail-facts">
            {[
              ["Lease starts", leaseDate(item.contractStartsOn)],
              ["Lease ends (last covered day)", lastDay ? leaseDate(lastDay) : "No fixed end date"],
              ["Occupancy starts", leaseDate(item.occupancyStartsOn)],
              ...(item.executedOn ? [["Signed on", leaseDate(item.executedOn)]] : []),
              ...(item.actualMoveOutOn ? [["Moved out", leaseDate(item.actualMoveOutOn)]] : []),
              ...(item.endReason ? [["End reason", item.endReason.replaceAll("_", " ")]] : []),
            ].map(([name, value]) => (
              <div key={name}>
                <dt>{name}</dt>
                <dd>{value}</dd>
              </div>
            ))}
          </dl>
          <p className="lease-detail-note">
            The end date is the last covered day. Record physical move-out separately; contract
            expiry does not make the rental vacant.
          </p>
        </section>
        <section aria-label="Rent terms" className="lease-detail-panel">
          <div className="lease-detail-section-heading">
            <h3>Rent terms</h3>
            <Link to={`/money?leaseId=${id}`}>View rent and deposits →</Link>
          </div>
          {!item.terms.length && <p>No rent terms recorded.</p>}
          {item.terms.map((term, index) => (
            <article className="child-record-card lease-rent-term" key={term.id}>
              <h4>
                Rent terms from {leaseDate(term.effectiveOn)}
                {item.terms.length > 1 ? ` · Period ${index + 1}` : ""}
              </h4>
              <MoneyFacts
                value={{
                  ...term,
                  effectiveOn: leaseDate(term.effectiveOn),
                  paymentDueDay:
                    term.paymentFrequency === "monthly" && term.paymentDueDay !== null
                      ? `Day ${term.paymentDueDay} of each month`
                      : term.paymentDueDay,
                  lastCoveredOn: term.endsOn
                    ? leaseDate(leaseLastCoveredOn(term.endsOn)!)
                    : "Ongoing",
                }}
                labels={{
                  effectiveOn: "Applies from",
                  lastCoveredOn: "Through",
                  baseRentMinor: "Rent",
                  paymentFrequency: "Frequency",
                  paymentDueDay: "Due day",
                  agreedSecurityDepositMinor: "Agreed security deposit",
                }}
                fields={[
                  "effectiveOn",
                  "lastCoveredOn",
                  "baseRentMinor",
                  "paymentFrequency",
                  "paymentDueDay",
                  "agreedSecurityDepositMinor",
                ]}
              />
            </article>
          ))}
        </section>
      </div>
      <LeaseParticipants lease={item} />
      {item.notes && (
        <section className="lease-detail-section" aria-label="Lease notes">
          <h3>Notes</h3>
          <p className="lease-detail-text">{item.notes}</p>
        </section>
      )}
      <details className="lease-detail-section" open={item.renewalOptions.length > 0}>
        <summary>
          Renewal options{item.renewalOptions.length ? ` (${item.renewalOptions.length})` : ""}
        </summary>
        {!item.renewalOptions.length && <p>No renewal options recorded.</p>}
        {item.renewalOptions.map((option) => (
          <article className="child-record-card" key={option.id}>
            <h4>Renewal from {leaseDate(option.proposedStartsOn)}</h4>
            <ReadableFacts
              value={{
                ...option,
                proposedStartsOn: leaseDate(option.proposedStartsOn),
                proposedLastCoveredOn: option.proposedEndsOn
                  ? leaseDate(leaseLastCoveredOn(option.proposedEndsOn)!)
                  : "No fixed end date",
              }}
              fields={[
                "status",
                "proposedStartsOn",
                "proposedLastCoveredOn",
                "noticeDueOn",
                "responseDueOn",
                "notes",
              ]}
            />
            {item.status === "executed" && option.status === "open" && (
              <CommandLinks
                target={id}
                child={option.id}
                keys={["lease.renewal.update", "lease.renewal.decide"]}
                title={`Renewal ${option.proposedStartsOn}`}
                asButtons
                collapsible={false}
              />
            )}
          </article>
        ))}
      </details>
      <TerminationCases lease={item} />
      <InspectionList lease={item} />
      {item.status === "ended" || item.status === "terminated" ? (
        <section aria-label="Move-out next steps">
          <h3>Move-out recorded</h3>
          <p>
            Finish the post-move-out inspection, compare condition, then prepare settlement.
            Inspection findings do not create deductions; settlement approval and refund recording
            are separate decisions.
          </p>
          <Link to={`/money?leaseId=${id}`}>Review deposit settlement</Link>
        </section>
      ) : null}
      <LeaseDocuments leaseId={id} entityId={id} entityType="lease" files={item.files} />
      <History kind="lease" id={id} presentation="timeline" />
    </section>
  );
}

function LeaseParticipants({ lease }: { lease: Lease }) {
  const { scope } = useWorkspace();
  const ids = [...new Set(lease.participants.map((item) => item.tenantPartyId))].sort();
  const names = useQuery({
    queryKey: scope.key("lease-participant-names", ids.join(",")),
    enabled: ids.length > 0,
    retry: false,
    queryFn: async ({ signal }) => {
      const rows: components["schemas"]["PartyNameResponse"][] = [];
      for (let offset = 0; offset < ids.length; offset += 100) {
        rows.push(
          ...readResult(
            await api.GET("/api/parties/names", {
              signal,
              params: { query: { ids: ids.slice(offset, offset + 100) } },
            }),
          ),
        );
      }
      return new Map(rows.map((item) => [item.id, item.displayName]));
    },
  });
  return (
    <section className="lease-detail-section" aria-label="Lease participants">
      <h3>Tenants and other participants</h3>
      {names.error && (
        <p role="alert">Participant names are unavailable. You can still open tenant details.</p>
      )}
      {!lease.participants.length && <p>No participants added yet.</p>}
      <ul className="lease-participants">
        {lease.participants.map((item) => (
          <li key={item.id}>
            <div className="lease-detail-section-heading">
              <div>
                <Link to={`/tenants?identity=${item.tenantPartyId}`}>
                  {names.data?.get(item.tenantPartyId) ??
                    (names.isPending ? "Loading name…" : "View tenant details")}
                </Link>
                <p>{item.participantRole.replaceAll("_", " ")}</p>
              </div>
              {lease.status === "draft" && (
                <CommandLinks
                  target={lease.id}
                  child={item.id}
                  keys={["lease.participant.update", "lease.participant.remove"]}
                  labels={{
                    "lease.participant.update": "Edit participant",
                    "lease.participant.remove": "Remove participant",
                  }}
                  title={`Participant actions for ${names.data?.get(item.tenantPartyId) ?? "tenant"}`}
                  collapsible={false}
                />
              )}
            </div>
            <p className="lease-detail-note">
              From {leaseDate(item.startsOn)}
              {item.endsOn
                ? ` through ${leaseDate(leaseLastCoveredOn(item.endsOn)!)}`
                : " · Ongoing"}
            </p>
            {item.notes && <p className="lease-detail-text">{item.notes}</p>}
          </li>
        ))}
      </ul>
    </section>
  );
}

function LeaseSpaceContext({ spaceId }: { spaceId: string }) {
  const { scope } = useWorkspace();
  const space = useQuery({
    queryKey: scope.key("lease-space-context", spaceId),
    retry: false,
    queryFn: async ({ signal }) =>
      readResult(
        await api.GET("/api/spaces/{space_id}/status", {
          signal,
          params: { path: { space_id: spaceId } },
        }),
      ),
  });
  const propertyId = space.data?.propertyId;
  const property = useQuery({
    queryKey: scope.key("portfolio-record", propertyId),
    enabled: !!propertyId,
    retry: false,
    queryFn: async ({ signal }) =>
      readResult(
        await api.GET("/api/properties/{property_id}", {
          signal,
          params: { path: { property_id: propertyId! } },
        }),
      ),
  });
  return (
    <section aria-label="Lease property" className="lease-detail-context">
      {space.isPending && <p role="status">Loading property…</p>}
      {space.error && (
        <p role="alert">Property information is unavailable. Lease records remain available.</p>
      )}
      {space.data && (
        <>
          <p>
            <Link to={`/properties/${space.data.propertyId}/overview`}>
              {property.data?.displayName ?? "View property"}
            </Link>{" "}
            · {space.data.displayName}
          </p>
          <Link to={`/properties/${space.data.propertyId}/units`}>
            View occupancy and leasing status
          </Link>
        </>
      )}
    </section>
  );
}

function TerminationCases({ lease }: { lease: Lease }) {
  const { scope } = useWorkspace();
  const cases = useQuery({
    queryKey: scope.key("lease-termination", lease.id),
    queryFn: async ({ signal }) =>
      readResult(
        await api.GET("/api/leases/{lease_id}/termination-cases", {
          signal,
          params: { path: { lease_id: lease.id } },
        }),
      ),
  });
  return (
    <section aria-label="Termination requests" className="lease-detail-section">
      <details open={cases.isPending || !!cases.error || !!cases.data?.length}>
        <summary>
          Early termination requests{cases.data?.length ? ` (${cases.data.length})` : ""}
        </summary>
        {cases.isPending && <p role="status">Loading termination requests…</p>}
        {cases.error && <p role="alert">{cases.error.message}</p>}
        {cases.data?.length === 0 && <p>No early termination requests recorded.</p>}
        {cases.data?.map((item) => (
          <article className="child-record-card termination-case" key={item.id}>
            <header className="child-record-heading">
              <h4>Requested end: {leaseDate(item.requestedTerminationOn)}</h4>
              <span className="record-pill">
                {item.status.replaceAll("_", " ").replace(/^\w/, (letter) => letter.toUpperCase())}
              </span>
            </header>
            <ReadableFacts
              value={item}
              fields={[
                "reason",
                "noticeReceivedOn",
                "requestedTerminationOn",
                "expectedMoveOutOn",
                "agreedTerminationOn",
                "acceptedOn",
                "completedOn",
                "tenantExplanation",
                "contractClauseReference",
                "operatorNotes",
              ]}
            />
            {lease.status === "executed" && (
              <CommandLinks
                target={lease.id}
                child={item.id}
                keys={
                  item.status === "accepted"
                    ? ["lease.termination.complete", "lease.terminate"]
                    : ["requested", "under_review", "proposed"].includes(item.status)
                      ? [
                          "lease.termination.proposal.add",
                          "lease.termination.proposal.accept",
                          "lease.termination.transition",
                        ]
                      : []
                }
                title={`Termination actions ${item.requestedTerminationOn}`}
                asButtons
                collapsible={false}
              />
            )}
            {item.proposals.map((p) => (
              <section className="termination-proposal" key={p.id}>
                <header className="child-record-heading">
                  <h5>Proposal {p.proposalVersion}</h5>
                  <span className="record-pill">
                    {p.status.replaceAll("_", " ").replace(/^\w/, (letter) => letter.toUpperCase())}
                  </span>
                </header>
                <MoneyFacts
                  value={p}
                  labels={{
                    terminationFeeMinor: "Termination fee",
                    proposedTerminationOn: "Proposed lease end",
                    rentResponsibilityEndsOn: "Rent responsibility through",
                  }}
                  fields={[
                    "proposedTerminationOn",
                    "expectedMoveOutOn",
                    "rentResponsibilityEndsOn",
                    "terminationFeeMinor",
                    "currencyCode",
                    "feeWaived",
                    "replacementTenantCondition",
                    "accessArrangement",
                    "otherTerms",
                    "responseDueOn",
                    "decidedOn",
                  ]}
                />
              </section>
            ))}
            <LeaseDocuments
              leaseId={lease.id}
              entityId={item.id}
              entityType="lease_termination_case"
              files={item.files}
            />
          </article>
        ))}
      </details>
    </section>
  );
}

function LeaseCommand() {
  const { onSaved } = useSaveCompletion();
  const [params] = useSearchParams();
  const definition = workflows.find((item) => item.formKey === params.get("workflow"))!;
  const target = params.get("target") ?? undefined;
  const { scope } = useWorkspace();
  const [session] = useState(() => crypto.randomUUID());
  const { resume, recovery, child } = useWorkflowRecovery(definition);
  const source = useQuery({
    queryKey: scope.key("lease-command-source", session, target),
    enabled: !!target,
    staleTime: Infinity,
    refetchOnWindowFocus: false,
    queryFn: async ({ signal }) => {
      const lease = readResult(
        await api.GET("/api/leases/{lease_id}", {
          signal,
          params: { path: { lease_id: target! } },
        }),
      );
      const space =
        "expectedRevision" in (definition.schema.properties ?? {})
          ? readResult(
              await api.GET("/api/spaces/{space_id}/status", {
                signal,
                params: { path: { space_id: lease.spaceId } },
              }),
            )
          : null;
      const cases =
        definition.childKey === "caseId"
          ? readResult(
              await api.GET("/api/leases/{lease_id}/termination-cases", {
                signal,
                params: { path: { lease_id: target! } },
              }),
            )
          : [];
      return { lease, space, cases };
    },
  });
  if (!definition.formKey.startsWith("lease."))
    return <p role="alert">Unsupported Leasing workflow.</p>;
  if (definition.sourceKind && !target) return <p role="alert">Select the owning Lease first.</p>;
  if ((target && source.isPending) || (resume && recovery.isPending))
    return <p role="status">Loading displayed lease…</p>;
  if (source.error || recovery.error)
    return <p role="alert">{source.error?.message ?? recovery.error?.message}</p>;
  const lease = source.data?.lease;
  const selected =
    definition.childKey === "participantId"
      ? lease?.participants.find((p) => p.id === child)
      : definition.childKey === "optionId"
        ? lease?.renewalOptions.find((o) => o.id === child)
        : source.data?.cases.find((c) => c.id === child);
  const savedAttempt = recovery.data;
  const canRecoverMissingChild = !!(
    savedAttempt &&
    savedAttempt.formKey === definition.formKey &&
    savedAttempt.sourceId === target &&
    definition.childKey &&
    savedAttempt.payload[definition.childKey] === child &&
    ((savedAttempt.status === "outcome_unknown" && savedAttempt.attemptKey) || savedAttempt.receipt)
  );
  if (definition.childKey && !selected && !canRecoverMissingChild)
    return <p role="alert">This child record does not belong to the selected Lease.</p>;
  const initial: Record<string, unknown> = {
    ...(source.data?.space ? { expectedRevision: source.data.space.revision } : {}),
  };
  const facts = definition.formKey === "lease.term.replace" ? lease?.terms[0] : (selected ?? lease);
  if (/patch|update|replace/.test(definition.formKey))
    for (const key of Object.keys(definition.schema.properties ?? {}))
      if (key in record(facts) && !key.startsWith("expected") && record(facts)[key] !== null)
        initial[key] = record(facts)[key];
  if (definition.formKey === "lease.create")
    Object.assign(initial, {
      spaceId: params.get("spaceId") ?? undefined,
      leaseKind: "residential",
      initialTerm: {
        currencyCode: "USD",
        paymentFrequency: "monthly",
        agreedSecurityDepositMinor: 0,
      },
      participants: [{}],
    });
  return (
    <>
      <CommandLoader
        onSaved={onSaved}
        definition={definition}
        sourceId={target}
        childId={child}
        revision={lease?.leaseRevision ?? 0}
        initial={initial}
        checkSource={
          source.data?.space
            ? async (values) => {
                const current = readResult(
                  await api.GET("/api/spaces/{space_id}/status", {
                    params: { path: { space_id: source.data.lease.spaceId } },
                  }),
                );
                if (current.revision !== values.expectedRevision)
                  throw new Error(
                    "Space timeline changed. Review the current source before submitting; your input is retained.",
                  );
              }
            : undefined
        }
        choices={{
          proposalId:
            source.data?.cases
              .find((c) => c.id === child)
              ?.proposals.filter((p) => p.status === "open")
              .map((p) => ({
                id: p.id,
                label: `${p.proposedTerminationOn} · ${p.otherTerms ?? "proposal"}`,
              })) ?? [],
        }}
        returnTo={target ? `/leases/${target}/details` : "/leasing"}
      />
    </>
  );
}
