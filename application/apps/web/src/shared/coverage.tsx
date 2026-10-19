import { useState } from "react";
import { PageAsOf } from "./page-as-of";
import { useQuery } from "@tanstack/react-query";
import { Navigate, useParams, useSearchParams } from "react-router-dom";
import { ParentBackLink, SourceWorkflowLink as Link } from "./home-navigation";
import { api } from "@epm/contracts";
import type { components } from "@epm/contracts/generated";
import { useWorkspace } from "../app/workspace-gate";
import { readResult } from "../workflows/reads";
import { useRecoverableForm, RecoveryNavigation } from "./use-recoverable-form";
import { mutation } from "./mutations";
import type { Recovery } from "./recovery";
import { formatHomeTime } from "./home-time";
import { propertyUnitsLabel, rentableUnitLabel } from "./property-labels";

type Coverage = components["schemas"]["CoverageResult"];
type Area = Coverage["area"];
type Kind = Coverage["subjectKind"];
type ReviewValues = {
  subjectKind: Kind;
  subjectId: string;
  area: Area;
  expectedEvidenceRevision: string;
  basis: "acknowledged" | "not_applicable";
  reason: string;
  nextReviewOn: string;
};
const projectReview = (values: ReviewValues) => ({
  ...values,
  nextReviewOn: values.nextReviewOn || null,
});
const explain: Record<Area, string> = {
  occupancy:
    "Review occupancy and leasing status. If either is unclassified or incorrect, follow the link below to update the property’s records.",
  lease:
    "Occupied rentals need an applicable lease and term. Review the lease source to resolve missing context.",
  rent: "Rent tracking needs a confirmed schedule for an executed lease. Relevant term changes require review or synchronization.",
  deposit: "Applicable deposit tracking must exist and agree with the lease terms.",
  maintenance:
    "Review recorded issues explicitly. An empty issue list does not establish the absence of problems.",
};
const words = (value: string) => value.replaceAll("_", " ");
const occupancyReasons: Partial<Record<Coverage["causes"][number], string>> = {
  availability_unknown: "Leasing status hasn’t been classified.",
  occupancy_unknown_or_conflicting: "Occupancy is unclassified or has conflicting records.",
};

function OccupancyResolution({
  current,
  space,
  unitName,
  unitsLabel,
}: {
  current: Coverage;
  space: components["schemas"]["SpaceStatusResponse"];
  unitName: string;
  unitsLabel: string;
}) {
  const missingLeasing = current.causes.includes("availability_unknown");
  const unknownOccupancy =
    space.currentOccupancy.occupancyStatus === "unknown" &&
    space.currentOccupancy.sourceKind === "manual";
  const conflict = space.attentionReasons.some((reason) => reason.code === "source_conflict");
  const classify =
    !conflict &&
    (unknownOccupancy ||
      (missingLeasing && !current.causes.includes("occupancy_unknown_or_conflicting")));
  let label = "Review occupancy and leasing status";
  if (classify)
    label = unknownOccupancy
      ? missingLeasing
        ? "Set occupancy and leasing status"
        : "Set occupancy"
      : "Set leasing status";
  return (
    <>
      <p>
        {classify
          ? `${unknownOccupancy ? `Record whether this ${unitName} is occupied or vacant.` : `Choose whether this ${unitName} is not open for leasing, open now, or open from a future date.`} Save the classification form, then return here and refresh.`
          : `Review the current records in the property’s ${unitsLabel} tab. Lease-owned occupancy must be changed through its lease; conflicting records need review before changes.`}
      </p>
      <Link
        className="information-review-primary"
        to={
          classify
            ? `/properties?workflow=portfolio.space.classify&target=${space.id}`
            : `/properties/${space.propertyId}/units`
        }
      >
        {label}
      </Link>
    </>
  );
}

function CoverageResolution({
  current,
  unitName,
  unitsLabel,
}: {
  current: Coverage;
  unitName: string;
  unitsLabel: string;
}) {
  const { scope } = useWorkspace();
  const target = current.resolutionRoute;
  const space = useQuery({
    queryKey: scope.key("coverage-resolution-space", target?.entityId),
    enabled:
      current.applicability !== "not_applicable" &&
      target?.entityType === "space" &&
      (target.section === "occupancy" || !current.leaseId),
    retry: false,
    queryFn: async ({ signal }) =>
      readResult(
        await api.GET("/api/spaces/{space_id}/status", {
          signal,
          params: { path: { space_id: target!.entityId } },
        }),
      ),
  });
  if (current.applicability === "not_applicable")
    return <p>No setup is needed for the current records.</p>;
  if (!target) return <p>Source resolution context is unavailable.</p>;
  if (target.section === "occupancy")
    return (
      <>
        {space.error && (
          <p role="alert">Current property context unavailable: {space.error.message}</p>
        )}
        {space.isPending && <p role="status">Loading current property context…</p>}
        {space.data && (
          <OccupancyResolution
            current={current}
            space={space.data}
            unitName={unitName}
            unitsLabel={unitsLabel}
          />
        )}
      </>
    );
  if (target.section === "maintenance")
    return <Link to={`/maintenance?propertyId=${target.entityId}`}>Review maintenance issues</Link>;
  if (
    target.section === "lease" ||
    current.causes.includes("lease_context_missing") ||
    current.causes.includes("lease_context_ambiguous_or_missing_term")
  ) {
    if (current.leaseId)
      return <Link to={`/leases/${current.leaseId}/details`}>Review lease and terms</Link>;
    if (space.error)
      return <p role="alert">Current property context unavailable: {space.error.message}</p>;
    if (!space.data) return <p role="status">Loading current property context…</p>;
    return <Link to={`/properties/${space.data.propertyId}/leases`}>Review property leases</Link>;
  }
  if (!current.leaseId)
    return (
      <p>
        Lease context is unavailable. Review the property’s leases before setting up money records.
      </p>
    );
  const needsRentSetup =
    current.causes.includes("rent_expectations_missing") ||
    current.causes.includes("rent_synchronization_required");
  const needsDepositSetup = current.causes.includes("deposit_account_missing");
  const url =
    target.section === "rent" && needsRentSetup
      ? `/money?workflow=finance.rent_expectation.synchronize&target=${current.leaseId}`
      : target.section === "deposit" && needsDepositSetup
        ? `/money?workflow=finance.deposit_account.create&leaseId=${current.leaseId}`
        : `/money?tab=${target.section === "deposit" ? "deposits" : "rent"}&leaseId=${current.leaseId}`;
  return (
    <>
      <Link className="information-review-primary" to={url}>
        {target.section === "rent"
          ? needsRentSetup
            ? current.causes.includes("rent_expectations_missing")
              ? "Set up rent schedule"
              : "Update rent schedule"
            : "Review rent records"
          : needsDepositSetup
            ? "Set up deposit tracking"
            : "Review deposit records"}
      </Link>
      <Link to={`/leases/${current.leaseId}/details`}>Review lease and terms</Link>
    </>
  );
}
function ReviewEditor({
  current,
  recovered,
  refresh,
}: {
  current: Coverage;
  recovered?: Recovery;
  refresh: () => void;
}) {
  const { scope } = useWorkspace();
  const [id] = useState(() => recovered?.id ?? crypto.randomUUID());
  const [error, setError] = useState<string>();
  const [receipt, setReceipt] = useState<Coverage>();
  const payload = recovered?.payload;
  const { form, controller, state, blocker } = useRecoverableForm<ReviewValues>({
    id,
    identity: {
      formKey: "coverage.review",
      schemaVersion: 1,
      sourceKind: null,
      sourceId: null,
      baseSourceRevision: null,
    },
    initial: {
      subjectKind: current.subjectKind,
      subjectId: current.subjectId,
      area: current.area,
      expectedEvidenceRevision:
        typeof payload?.expectedEvidenceRevision === "string"
          ? payload.expectedEvidenceRevision
          : current.evidenceRevision!,
      basis: payload?.basis === "not_applicable" ? "not_applicable" : "acknowledged",
      reason: typeof payload?.reason === "string" ? payload.reason : "",
      nextReviewOn: typeof payload?.nextReviewOn === "string" ? payload.nextReviewOn : "",
    },
    recovered,
    project: projectReview,
  });
  const displayed = form.watch("expectedEvidenceRevision");
  const changed = displayed !== current.evidenceRevision;
  const original = useQuery({
    queryKey: scope.key("coverage-original", state.record?.attemptKey),
    enabled: state.command === "committed" && !!state.record?.attemptKey,
    queryFn: async ({ signal }) =>
      readResult(
        await api.GET("/api/operator/coverage/operations/{key}", {
          signal,
          params: { path: { key: state.record!.attemptKey! } },
        }),
      ),
  });
  async function dispatch(record: Recovery) {
    const values = record.payload;
    const result = await mutation(() =>
      api.POST("/api/operator/coverage/{kind}/{subject_id}/{area}/reviews", {
        params: {
          path: { kind: current.subjectKind, subject_id: current.subjectId, area: current.area },
        },
        body: {
          expectedEvidenceRevision: String(values.expectedEvidenceRevision),
          basis: values.basis === "not_applicable" ? "not_applicable" : "acknowledged",
          reason: String(values.reason),
          nextReviewOn: typeof values.nextReviewOn === "string" ? values.nextReviewOn : null,
          idempotencyKey: record.attemptKey!,
        },
      }),
    );
    setReceipt(result);
    refresh();
  }
  async function action(operation: () => Promise<void>) {
    setError(undefined);
    try {
      await operation();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Review failed.");
    }
  }
  const locked =
    state.command === "submitting" ||
    state.command === "outcome_unknown" ||
    state.command === "committed";
  return (
    <section className="information-review-editor" aria-label="Information review form">
      <h3>Review {current.area}</h3>
      <p className="information-review-intro">
        Record your review of the information shown above. This does not change the underlying
        records.
      </p>
      <details className="information-review-revision">
        <summary>Source reference</summary>
        <p>Evidence revision: {displayed}</p>
      </details>
      {changed && (
        <p role="alert">
          Source information changed. Your review edits are retained. Review the latest facts before
          accepting their evidence revision.
        </p>
      )}
      {changed && !locked && current.evidenceRevision && (
        <button
          onClick={() =>
            form.setValue("expectedEvidenceRevision", current.evidenceRevision!, {
              shouldDirty: true,
            })
          }
        >
          Use displayed evidence revision
        </button>
      )}
      <form
        onSubmit={(event) => {
          void form.handleSubmit(() => void action(() => controller.submit(dispatch)))(event);
        }}
      >
        <fieldset disabled={locked || !scope.canWrite}>
          <label>
            Review basis
            <select {...form.register("basis")}>
              <option value="acknowledged">Acknowledged</option>
              {current.applicability === "not_applicable" && (
                <option value="not_applicable">Not applicable</option>
              )}
            </select>
          </label>
          <label>
            Review reason
            <textarea
              required
              maxLength={1000}
              {...form.register("reason", { required: true, validate: (value) => !!value.trim() })}
            />
          </label>
          <label>
            Next review date
            <input
              type="date"
              min={current.effectiveLocalDate ?? undefined}
              {...form.register("nextReviewOn")}
            />
          </label>
          <button disabled={changed || current.availability !== "available"}>Record review</button>
        </fieldset>
      </form>
      <p role="status">
        Form {state.draft} · Review {state.command}
      </p>
      {(error || state.error) && <p role="alert">{error ?? state.error}</p>}
      <button
        disabled={locked || !scope.canWrite}
        onClick={() => void action(() => controller.flush())}
      >
        Save review form
      </button>
      {state.command === "outcome_unknown" && (
        <>
          <p>The outcome is unknown. Reconcile or replay the original attempt.</p>
          <button onClick={() => void action(() => controller.reconcile())}>
            Reconcile review
          </button>
          <button onClick={() => void action(() => controller.replay(dispatch))}>
            Replay original review
          </button>
        </>
      )}
      {receipt && (
        <p>
          Original review {receipt.operationId}: {words(receipt.state ?? "unavailable")} ·{" "}
          {receipt.asOf}
        </p>
      )}
      {original.data && !receipt && (
        <p>
          Original review {original.data.operationId}: {words(original.data.state ?? "unavailable")}{" "}
          · {original.data.asOf}
        </p>
      )}
      {original.error && (
        <p role="alert">Original review receipt unavailable: {original.error.message}</p>
      )}
      <RecoveryNavigation controller={controller} blocker={blocker} />
    </section>
  );
}
function CoveragePanel({
  kind,
  id,
  area,
  propertyName,
  unitsLabel = "Home, Office, or Suites",
  unitName = "rental",
}: {
  kind: Kind;
  id: string;
  area: Area;
  propertyName?: string;
  unitsLabel?: string;
  unitName?: string;
}) {
  const { scope } = useWorkspace();
  const [params, setParams] = useSearchParams();
  const [editing, setEditing] = useState(false);
  const resume = params.get("reviewResume") ?? undefined;
  const result = useQuery({
    queryKey: scope.key("coverage", kind, id, area),
    refetchInterval: 60_000,
    queryFn: async ({ signal }) =>
      readResult(
        await api.GET("/api/operator/coverage/{kind}/{subject_id}/{area}", {
          signal,
          params: { path: { kind, subject_id: id, area } },
        }),
      ),
  });
  const recovery = useQuery({
    queryKey: scope.key("coverage-resume", resume),
    enabled: !!resume,
    queryFn: async ({ signal }) => {
      const value = readResult(
        await api.GET("/api/operator/recovery/{record_id}", {
          signal,
          params: { path: { record_id: resume! } },
        }),
      );
      if (
        value.formKey !== "coverage.review" ||
        !["active", "outcome_unknown", "reconciled"].includes(value.status) ||
        value.payload.subjectKind !== kind ||
        value.payload.subjectId !== id ||
        value.payload.area !== area
      )
        throw new Error("This review form belongs to a different subject or area.");
      return value;
    },
  });
  const current = result.data;
  return (
    <section className="information-review-panel" aria-label={`${words(area)} information review`}>
      <header className="information-review-heading">
        <div>
          <h3>
            {words(area).replace(/^./, (character) => character.toUpperCase())} information review
          </h3>
          <p>{explain[area]}</p>
        </div>
        <button onClick={() => void result.refetch()}>Refresh {words(area)} information</button>
      </header>
      {propertyName && <p className="information-review-property">{propertyName}</p>}
      {result.error ? (
        <p role="alert">{result.error.message}</p>
      ) : !current ? (
        <p role="status">Loading information review…</p>
      ) : current.availability === "unavailable" ? (
        <p role="alert">Information review source unavailable; no state can be inferred.</p>
      ) : (
        <div className="information-review-grid">
          <section className="information-review-card" aria-label="Current information">
            <h4>Current information</h4>
            <div className="information-review-badges">
              <span
                className="information-review-badge"
                data-state={current.state ?? "unavailable"}
              >
                {words(current.state ?? "unavailable")}
              </span>
            </div>
            {current.causes.length > 0 && (
              <ul className="information-review-reasons">
                {current.causes.map((cause) => (
                  <li key={cause}>
                    {area === "occupancy"
                      ? (occupancyReasons[cause] ?? words(cause))
                      : words(cause)}
                  </li>
                ))}
              </ul>
            )}
            {current.trigger && (
              <p className="information-review-prompt" role="status">
                Review prompt: {words(current.trigger)}
              </p>
            )}
            <div className="information-review-sources">
              <h4>
                {current.applicability === "not_applicable" ? "No setup needed" : "Next step"}
              </h4>
              <CoverageResolution current={current} unitName={unitName} unitsLabel={unitsLabel} />
            </div>
          </section>
          <PageAsOf asOf={current.asOf} />
          <section className="information-review-card" aria-label="Review details">
            <h4>{area === "occupancy" ? "Review history" : "Review details"}</h4>
            <dl className="information-review-facts">
              <div>
                <dt>Property-local date</dt>
                <dd>{current.effectiveLocalDate ?? "Unavailable"}</dd>
              </div>
              <div>
                <dt>Last manual review</dt>
                <dd>
                  {current.lastManualReviewAt ? (
                    <time dateTime={current.lastManualReviewAt}>
                      {formatHomeTime(current.lastManualReviewAt)}
                    </time>
                  ) : (
                    "Not recorded"
                  )}
                </dd>
              </div>
            </dl>
            <p className="information-review-intro">
              {area === "occupancy"
                ? "Optional: record that you checked this information. A review note does not change occupancy or leasing status, or resolve missing information."
                : "Fix missing information in the source records first. Acknowledging a review does not fill required gaps."}
            </p>
            {!editing && !resume && (
              <button disabled={!scope.canWrite} onClick={() => setEditing(true)}>
                {area === "occupancy" ? "Add review note" : `Review ${words(area)} information`}
              </button>
            )}
          </section>
        </div>
      )}
      {current && (!resume || recovery.data) && (editing || resume) && (
        <ReviewEditor
          key={`${kind}:${id}:${area}:${resume}`}
          current={current}
          recovered={recovery.data}
          refresh={() => void result.refetch()}
        />
      )}
      {recovery.error && <p role="alert">{recovery.error.message}</p>}
      {resume && (
        <button
          onClick={() => {
            const next = new URLSearchParams(params);
            next.delete("reviewResume");
            setParams(next);
          }}
        >
          Close saved review
        </button>
      )}
    </section>
  );
}

export function CoverageLinks({ propertyId, spaceId }: { propertyId?: string; spaceId?: string }) {
  return (
    <nav aria-label="Information review">
      {propertyId && (
        <Link to={`/coverage/property/${propertyId}/maintenance`}>
          Maintenance information review
        </Link>
      )}
      {spaceId &&
        (["occupancy", "lease", "rent", "deposit"] as const).map((area) => (
          <Link key={area} to={`/coverage/space/${spaceId}/${area}`}>
            {words(area).replace(/^./, (character) => character.toUpperCase())} information review
          </Link>
        ))}
    </nav>
  );
}

function ReviewPropertyPage({ kind, id, area }: { kind: Kind; id: string; area: Area }) {
  const { scope } = useWorkspace();
  const space = useQuery({
    queryKey: scope.key("coverage-resolution-space", id),
    enabled: kind === "space",
    retry: false,
    queryFn: async ({ signal }) =>
      readResult(
        await api.GET("/api/spaces/{space_id}/status", {
          signal,
          params: { path: { space_id: id } },
        }),
      ),
  });
  const propertyId = kind === "property" ? id : space.data?.propertyId;
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
  const back = propertyId ? (
    <ParentBackLink to={`/properties/${propertyId}/overview`}>
      ← Back to {property.data?.displayName ?? "property"}
    </ParentBackLink>
  ) : space.error ? (
    <p role="alert">Property navigation unavailable: {space.error.message}</p>
  ) : (
    <p role="status">Loading property navigation…</p>
  );
  return (
    <div className="information-review-page">
      {back}
      <CoveragePanel
        kind={kind}
        id={id}
        area={area}
        propertyName={property.data?.displayName}
        unitsLabel={property.data ? propertyUnitsLabel(property.data.inventoryLayout) : undefined}
        unitName={space.data ? rentableUnitLabel(space.data.spaceKind) : undefined}
      />
      <footer>
        <p className="information-review-intro">
          Check whether the app has enough recorded information and whether it needs your review.
          This is not insurance or service coverage, continuous monitoring, or certification of
          legal compliance. Needs review is an information prompt, not necessarily a property
          problem.
        </p>
      </footer>
    </div>
  );
}

export function CoveragePage() {
  const { kind, id = "", area } = useParams();
  const areas: Area[] = ["occupancy", "lease", "rent", "deposit", "maintenance"];
  const selected = areas.find((value) => value === area);
  if (
    !selected ||
    (kind !== "property" && kind !== "space") ||
    (selected === "maintenance") !== (kind === "property")
  )
    return <p role="alert">This information review subject and area combination is unavailable.</p>;
  return <ReviewPropertyPage key={`${kind}:${id}:${area}`} kind={kind} id={id} area={selected} />;
}

export function CoverageResume() {
  const { id = "" } = useParams();
  const { scope } = useWorkspace();
  const result = useQuery({
    queryKey: scope.key("coverage-resume", id),
    queryFn: async ({ signal }) => {
      const value = readResult(
        await api.GET("/api/operator/recovery/{record_id}", {
          signal,
          params: { path: { record_id: id } },
        }),
      );
      if (value.formKey !== "coverage.review")
        throw new Error("This saved form is not an information review.");
      if (!["active", "outcome_unknown", "reconciled"].includes(value.status))
        throw new Error("This saved review is no longer reusable.");
      return value;
    },
  });
  const payload = result.data?.payload;
  return payload ? (
    <Navigate
      replace
      to={`/coverage/${String(payload.subjectKind)}/${String(payload.subjectId)}/${String(payload.area)}?reviewResume=${id}`}
    />
  ) : (
    <p role={result.error ? "alert" : "status"}>
      {result.error?.message ?? "Loading saved review…"}
    </p>
  );
}
