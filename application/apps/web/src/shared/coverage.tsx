import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, Navigate, useParams, useSearchParams } from "react-router-dom";
import { api } from "@epm/contracts";
import type { components } from "@epm/contracts/generated";
import { useWorkspace } from "../app/workspace-gate";
import { readResult } from "../workflows/reads";
import { useRecoverableForm, RecoveryNavigation } from "./use-recoverable-form";
import { mutation } from "./mutations";
import type { Recovery } from "./recovery";

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
    "Unknown occupancy or availability needs source information; acknowledging a review cannot fill that gap.",
  lease:
    "Occupied rentals need an applicable lease and term. Review the lease source to resolve missing context.",
  rent: "Rent tracking needs a confirmed schedule for an executed lease. Relevant term changes require review or synchronization.",
  deposit: "Applicable deposit tracking must exist and agree with the lease terms.",
  maintenance:
    "Review recorded issues explicitly. An empty issue list does not establish the absence of problems.",
};
const words = (value: string) => value.replaceAll("_", " ");
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
    <section aria-label="Coverage review">
      <h3>Review {current.area}</h3>
      <p>Evidence revision: {displayed}</p>
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
export function CoveragePanel({ kind, id, area }: { kind: Kind; id: string; area: Area }) {
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
    <section aria-label={`${area} coverage`}>
      <h3>{area} coverage</h3>
      <p>{explain[area]}</p>
      {result.error ? (
        <p role="alert">{result.error.message}</p>
      ) : !current ? (
        <p role="status">Loading coverage…</p>
      ) : current.availability === "unavailable" ? (
        <p role="alert">Coverage source unavailable; no state can be inferred.</p>
      ) : (
        <>
          <p>
            {words(current.state ?? "unavailable")} ·{" "}
            {words(current.applicability ?? "unavailable")}
          </p>
          <ul>
            {current.causes.map((cause) => (
              <li key={cause}>{words(cause)}</li>
            ))}
          </ul>
          {current.trigger && <p role="status">Review prompt: {words(current.trigger)}</p>}
          <p>
            As of {current.asOf} · Local date {current.effectiveLocalDate}
          </p>
          <p>Last manual review: {current.lastManualReviewAt ?? "Not recorded"}</p>
          {current.leaseId && <Link to={`/leases/${current.leaseId}`}>Review lease source</Link>}
          <Link
            to={
              area === "maintenance"
                ? `/maintenance?propertyId=${id}`
                : area === "occupancy"
                  ? `/search?sourceType=space&sourceId=${id}`
                  : area === "lease"
                    ? `/leasing?spaceId=${id}`
                    : current.leaseId
                      ? `/money?leaseId=${current.leaseId}`
                      : "/money"
            }
          >
            Open {area} sources
          </Link>
          {!editing && !resume && (
            <button disabled={!scope.canWrite} onClick={() => setEditing(true)}>
              Review {area} coverage
            </button>
          )}
        </>
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
      <button onClick={() => void result.refetch()}>Refresh {area} coverage</button>
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
    <nav aria-label="Information coverage">
      {propertyId && (
        <Link to={`/coverage/property/${propertyId}/maintenance`}>Maintenance coverage</Link>
      )}
      {spaceId &&
        (["occupancy", "lease", "rent", "deposit"] as const).map((area) => (
          <Link key={area} to={`/coverage/space/${spaceId}/${area}`}>
            {words(area)} coverage
          </Link>
        ))}
    </nav>
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
    return <p role="alert">This coverage subject and area combination is unavailable.</p>;
  return (
    <>
      <h2>Information coverage</h2>
      <p>
        Coverage describes recorded responsibilities; it does not imply continuous monitoring or
        legal compliance.
      </p>
      <CoveragePanel key={`${kind}:${id}:${area}`} kind={kind} id={id} area={selected} />
    </>
  );
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
        throw new Error("This saved form is not a coverage review.");
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
