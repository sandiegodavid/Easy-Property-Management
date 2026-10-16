import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { leaseLastCoveredOn } from "../shared/lease-dates";
import { CoverageLinks } from "../shared/coverage";
import { useParams, useSearchParams } from "react-router-dom";
import { SourceWorkflowLink as Link } from "../shared/home-navigation";
import { api } from "@epm/contracts";
import { workflows, record, scalar } from "@epm/contracts/workflows";
import type { components } from "@epm/contracts/generated";
import { useWorkspace } from "../app/workspace-gate";
import { CommandLinks, CommandLoader } from "./command";
import { Facts, History, readResult } from "./reads";
import { InspectionList } from "./inspections";
import { LeaseDocuments } from "./lease-documents";
import { MoneyFacts } from "./money-presentation";
import { statusLabel } from "./portfolio-status";
import { PageAsOf } from "../shared/page-as-of";

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
    <section aria-label="Leasing">
      <h2>Leasing</h2>
      <CommandLinks keys={["lease.create"]} title="Set up lease" />
      <p>
        Record a draft, review and execute it, then review rent setup and related inspections as
        separate steps.
      </p>
      <label>
        Lease status
        <select
          value={status ?? ""}
          onChange={(event) => {
            const next = new URLSearchParams(params);
            next.delete("cursor");
            if (event.target.value) next.set("status", event.target.value);
            else next.delete("status");
            setParams(next);
          }}
        >
          <option value="">All statuses</option>
          {["draft", "executed", "ended", "terminated", "void"].map((value) => (
            <option key={value}>{value}</option>
          ))}
        </select>
      </label>
      {propertyId && (
        <p>
          Property filter: {propertyId}{" "}
          <button
            onClick={() => {
              const next = new URLSearchParams(params);
              next.delete("propertyId");
              next.delete("cursor");
              setParams(next);
            }}
          >
            Remove property filter
          </button>
        </p>
      )}
      {leases.isPending && <p role="status">Loading leases…</p>}
      {leases.error && <p role="alert">{leases.error.message}</p>}
      {leases.error instanceof DirectoryContinuationConflict && (
        <button
          onClick={() => {
            const next = new URLSearchParams(params);
            next.delete("cursor");
            setParams(next);
            if (!cursor) void leases.refetch();
          }}
        >
          Restart Lease directory with these filters
        </button>
      )}
      {leases.data && (
        <>
          <PageAsOf asOf={leases.data.asOf} />
          <p>{leases.data.matchingTotal} matching leases</p>
        </>
      )}
      {leases.data?.items.length === 0 && <p>No leases match these filters.</p>}
      {leases.data?.items.map((lease) => (
        <article key={lease.id}>
          <Link to={`/leases/${lease.id}/details`}>
            {lease.leaseKind} lease · {lease.contractStartsOn} · {lease.status}
          </Link>
          <p>Space {lease.spaceId}</p>
        </article>
      ))}
      {leases.data?.nextCursor && (
        <button
          onClick={() => {
            const next = new URLSearchParams(params);
            next.set("cursor", leases.data.nextCursor!);
            setParams(next);
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
            setParams(next);
          }}
        >
          First lease page
        </button>
      )}
      <Link to="/leasing?templates=true">Inspection templates</Link>
    </section>
  );
}

class DirectoryContinuationConflict extends Error {}

export function LeaseRecord({ id }: { id: string }) {
  const { scope } = useWorkspace();
  const lease = useQuery({
    queryKey: scope.key("lease-record", id),
    queryFn: async ({ signal }) =>
      readResult(
        await api.GET("/api/leases/{lease_id}", { signal, params: { path: { lease_id: id } } }),
      ),
  });
  if (lease.isPending) return <p role="status">Loading lease…</p>;
  if (lease.error) return <p role="alert">{lease.error.message}</p>;
  const item = lease.data;
  const displayed = { ...item, leaseLastCoveredOn: leaseLastCoveredOn(item.contractEndsOn) };
  return (
    <section aria-label="Lease workspace">
      <h2>{item.leaseKind} lease</h2>
      <Facts
        value={displayed}
        fields={[
          "status",
          "leaseRevision",
          "contractStartsOn",
          "leaseLastCoveredOn",
          "occupancyStartsOn",
          "actualMoveOutOn",
          "occupancyState",
          "notes",
        ]}
      />
      <Link to="/leasing">Return to Leasing</Link>
      <section aria-label="Lease milestones">
        <h3>Contract and physical occupancy</h3>
        <Facts
          value={displayed}
          fields={[
            "contractStartsOn",
            "leaseLastCoveredOn",
            "executedOn",
            "occupancyStartsOn",
            "actualMoveOutOn",
            "endReason",
          ]}
        />
        <p>
          Lease end shows the last day covered by the contract. Contract expiry or an accepted
          termination proposal does not confirm physical move-out or make the Space available.
        </p>
        <LeaseSpaceContext spaceId={item.spaceId} />
      </section>
      <CoverageLinks spaceId={item.spaceId} />
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
      />
      {item.status === "draft" && (
        <p>
          Review participants, contract dates and rent terms before confirming execution. Execution
          changes the Space occupancy timeline as well as this Lease.
        </p>
      )}
      {item.status === "executed" && (
        <section aria-label="Related rent setup">
          <h3>Lease recorded</h3>
          <p>
            Rent schedule needs review. Execution does not synchronize rent or create a deposit
            account.
          </p>
          <Link to={`/money?leaseId=${id}`}>Review rent setup</Link>
        </section>
      )}
      <h3>Participants</h3>
      {item.participants.map((participant) => (
        <article key={participant.id}>
          <Facts
            value={{ ...participant, lastCoveredOn: leaseLastCoveredOn(participant.endsOn) }}
            fields={["tenantPartyId", "participantRole", "startsOn", "lastCoveredOn", "notes"]}
          />
          <Link to={`/parties?identity=${participant.tenantPartyId}`}>Tenant identity</Link>
          {item.status === "draft" && (
            <CommandLinks
              target={id}
              child={participant.id}
              keys={["lease.participant.update", "lease.participant.remove"]}
              title={`Participant actions ${participant.tenantPartyId}`}
            />
          )}
        </article>
      ))}
      <h3>Rent terms</h3>
      {item.terms.map((term) => (
        <MoneyFacts
          key={term.id}
          value={{ ...term, lastCoveredOn: leaseLastCoveredOn(term.endsOn) }}
          fields={[
            "effectiveOn",
            "lastCoveredOn",
            "baseRentMinor",
            "currencyCode",
            "paymentFrequency",
            "paymentDueDay",
            "agreedSecurityDepositMinor",
          ]}
        />
      ))}
      <h3>Renewal options</h3>
      {item.renewalOptions.map((option) => (
        <article key={option.id}>
          <Facts
            value={option}
            fields={[
              "status",
              "proposedStartsOn",
              "proposedEndsOn",
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
            />
          )}
        </article>
      ))}
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
      <History kind="lease" id={id} />
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
  return (
    <section aria-label="Lease Space context">
      {space.isPending && <p role="status">Loading Space status…</p>}
      {space.error && (
        <p role="alert">
          Space status unavailable: {space.error.message}. Lease records remain available.
        </p>
      )}
      {space.data && (
        <>
          <p>
            {space.data.displayName} · Current occupancy:{" "}
            {statusLabel(space.data.currentOccupancy.occupancyStatus)} · Leasing status:{" "}
            {statusLabel(space.data.availability.effectiveStatus)}
          </p>
          <p>Property-local date: {space.data.effectiveLocalDate}</p>
          <Link to={`/properties/${space.data.propertyId}/units`}>
            Review Space occupancy and leasing status
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
    <section aria-label="Termination requests">
      <h3>Termination requests</h3>
      {cases.isPending && <p role="status">Loading termination requests…</p>}
      {cases.error && <p role="alert">{cases.error.message}</p>}
      {cases.data?.map((item) => (
        <article key={item.id}>
          <Facts
            value={item}
            fields={[
              "status",
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
            />
          )}
          {item.proposals.map((p) => (
            <MoneyFacts
              key={p.id}
              value={p}
              fields={[
                "id",
                "status",
                "proposalVersion",
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
          ))}
          <LeaseDocuments
            leaseId={lease.id}
            entityId={item.id}
            entityType="lease_termination_case"
            files={item.files}
          />
        </article>
      ))}
    </section>
  );
}

function LeaseCommand() {
  const [params] = useSearchParams();
  const definition = workflows.find((item) => item.formKey === params.get("workflow"))!;
  const target = params.get("target") ?? undefined;
  const { scope } = useWorkspace();
  const [session] = useState(() => crypto.randomUUID());
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
    (definition.childKey && recovery.data
      ? scalar(recovery.data.payload[definition.childKey])
      : undefined);
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
      <p>
        Lease revision: {lease?.leaseRevision ?? 0}
        {source.data?.space && ` · Space timeline revision: ${source.data.space.revision}`}. These
        are independent checks; review both before submitting a timeline change.
      </p>
      <CommandLoader
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
