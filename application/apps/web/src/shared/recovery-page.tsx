import { useState } from "react";
import { PageAsOf } from "./page-as-of";
import { useQuery } from "@tanstack/react-query";
import { api } from "@epm/contracts";
import { useWorkspace } from "../app/workspace-gate";
import { normalizeApiError } from "./mutations";
import { recoveryApi } from "./recovery";
import { Link } from "react-router-dom";
import { workflows } from "@epm/contracts/workflows";
import { workflowUrl } from "../workflows/command";
import type { components } from "@epm/contracts/generated";
import { formatHomeTime } from "./home-time";
import { hostedMode } from "../app/hosted-session-state";

const statusLabels: Record<components["schemas"]["RecoveryMetadata"]["status"], string> = {
  active: "Draft saved",
  outcome_unknown: "Submission needs checking",
  reconciled: "Submission checked",
  discarded: "Discarded",
  expired: "Expired",
};

// Bounded metadata only. Feature editors load their own allowlisted payloads.
export function RecoveryPage() {
  const { scope } = useWorkspace();
  const [cursor, setCursor] = useState<string>();
  const [error, setError] = useState<string>();
  const [pending, setPending] = useState(false);
  const records = useQuery({
    queryKey: scope.key("recovery-list", cursor),
    queryFn: async ({ signal }) => {
      const result = await api.GET("/api/operator/recovery", {
        signal,
        params: { query: { limit: 50, cursor } },
      });
      if (!result.data)
        throw new Error(normalizeApiError(result.response.status, result.error).message);
      return result.data;
    },
  });
  async function changeRecord(id: string, discard = false) {
    setPending(true);
    setError(undefined);
    try {
      scope.requireWrite();
      const current = await api.GET("/api/operator/recovery/{record_id}", {
        params: { path: { record_id: id } },
      });
      if (!current.data) throw new Error("This recovery record could not be loaded.");
      if (discard && current.data.status === "active")
        await recoveryApi.discard(id, {
          expectedRevision: current.data.revision,
          idempotencyKey: crypto.randomUUID(),
        });
      else if (!discard && current.data.status === "outcome_unknown")
        await recoveryApi.reconcile(id, {
          expectedRevision: current.data.revision,
          idempotencyKey: crypto.randomUUID(),
        });
      await records.refetch();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Reconciliation failed.");
    } finally {
      setPending(false);
    }
  }
  return (
    <>
      <h2>Unfinished forms</h2>
      <p>
        Saved forms are not official records. Files and credentials must be selected again after
        restart. If a submission was interrupted, check its result before submitting again.
      </p>
      {hostedMode() && (
        <p>
          Resume a saved form and explicitly claim editing before discarding it or checking its
          submission.
        </p>
      )}
      {records.isPending && <p role="status">Loading unfinished forms…</p>}
      {records.error && <p role="alert">{records.error.message}</p>}
      {error && <p role="alert">{error}</p>}
      {records.data && (
        <>
          <PageAsOf asOf={records.data.asOf} />
          <p>
            {records.data.matchingTotal} {records.data.matchingTotal === 1 ? "form" : "forms"}
          </p>
          {!records.data.items.some((record) =>
            ["active", "outcome_unknown"].includes(record.status),
          ) && <p>No unfinished forms on this page.</p>}
          <ul className="result-card-list">
            {records.data.items
              .filter((record) => ["active", "outcome_unknown"].includes(record.status))
              .map((record) => {
                const workflow = workflows.find((workflow) => workflow.formKey === record.formKey);
                const title =
                  workflow?.title ??
                  (record.formKey === "coverage.review" ? "Information review" : "Saved form");
                return (
                  <li className="child-record-card recovery-form-card" key={record.id}>
                    <header className="child-record-heading">
                      <h3>{title}</h3>
                      <span className="record-pill" data-status={record.status}>
                        {statusLabels[record.status]}
                      </span>
                    </header>
                    <p>
                      Saved <time dateTime={record.savedAt}>{formatHomeTime(record.savedAt)}</time>
                    </p>
                    <div className="result-card-actions">
                      {!hostedMode() && record.status === "outcome_unknown" && (
                        <button
                          disabled={pending || !scope.canWrite}
                          onClick={() => {
                            void changeRecord(record.id);
                          }}
                        >
                          Check submission
                        </button>
                      )}
                      {record.formKey === "coverage.review" ? (
                        <Link to={`/coverage/reviews/${record.id}`}>Resume: {title}</Link>
                      ) : workflow ? (
                        <Link
                          to={`${workflowUrl(record.formKey, record.sourceId ?? undefined)}&resume=${record.id}`}
                        >
                          Resume: {title}
                        </Link>
                      ) : (
                        record.status === "active" && (
                          <span>
                            {" "}
                            — Resume from the owning workflow when its editor is available.
                          </span>
                        )
                      )}
                      {!hostedMode() && record.status === "active" && (
                        <button
                          disabled={pending || !scope.canWrite}
                          onClick={() => {
                            if (
                              window.confirm(
                                `Discard the unfinished ${title.toLowerCase()} form? This will not change the official record.`,
                              )
                            )
                              void changeRecord(record.id, true);
                          }}
                        >
                          Discard
                        </button>
                      )}
                    </div>
                  </li>
                );
              })}
          </ul>
          {records.data.nextCursor && (
            <button onClick={() => setCursor(records.data.nextCursor ?? undefined)}>
              Next page
            </button>
          )}
          {cursor && <button onClick={() => setCursor(undefined)}>First page</button>}
        </>
      )}
    </>
  );
}
