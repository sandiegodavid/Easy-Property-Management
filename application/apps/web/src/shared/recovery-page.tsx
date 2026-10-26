import { useState } from "react";
import { PageAsOf } from "./page-as-of";
import { useQuery } from "@tanstack/react-query";
import { api } from "@epm/contracts";
import { useWorkspace } from "../app/workspace-gate";
import { normalizeApiError } from "./mutations";
import { RecoveryController } from "./recovery";
import { Link, useNavigate } from "react-router-dom";
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

function resumeUrl(record: components["schemas"]["RecoveryMetadata"]): string {
  return record.formKey === "coverage.review"
    ? `/coverage/reviews/${record.id}`
    : `${workflowUrl(record.formKey, record.sourceId ?? undefined)}&resume=${record.id}`;
}

// Bounded metadata only. Feature editors load their own allowlisted payloads.
export function RecoveryPage() {
  const { scope } = useWorkspace();
  const navigate = useNavigate();
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
      const saved = current.data;
      const controller = new RecoveryController(
        scope,
        id,
        {
          formKey: saved.formKey as components["schemas"]["RecoveryInput"]["formKey"],
          schemaVersion: saved.schemaVersion,
          sourceKind: saved.sourceKind as components["schemas"]["RecoveryInput"]["sourceKind"],
          sourceId: saved.sourceId,
          baseSourceRevision: saved.baseSourceRevision,
        },
        saved.payload,
        saved,
      );
      try {
        if (hostedMode()) await controller.claimEditing();
        if (discard) await controller.discard();
        else {
          await controller.reconcile();
          await navigate(resumeUrl(saved));
          return;
        }
      } catch (cause) {
        if (controller.getSnapshot().command === "committed") {
          await navigate(resumeUrl(saved));
          return;
        }
        throw cause;
      } finally {
        controller.dispose();
      }
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
          {(["outcome_unknown", "active"] as const).map((group) => (
            <section
              key={group}
              aria-label={group === "active" ? "Continue editing" : "Check submissions"}
            >
              <h3>{group === "active" ? "Continue editing" : "Check submissions"}</h3>
              {!records.data.items.some((item) => item.status === group) && (
                <p>No forms in this group on this page.</p>
              )}
              <ul className="result-card-list">
                {records.data.items
                  .filter((record) => record.status === group)
                  .map((record) => {
                    const workflow = workflows.find(
                      (workflow) => workflow.formKey === record.formKey,
                    );
                    const title =
                      workflow?.title ??
                      (record.formKey === "coverage.review" ? "Information review" : "Saved form");
                    return (
                      <li className="child-record-card recovery-form-card" key={record.id}>
                        <header className="child-record-heading">
                          <h3>
                            {title}
                            {record.label ? ` · ${record.label}` : ""}
                          </h3>
                          <span className="record-pill" data-status={record.status}>
                            {statusLabels[record.status]}
                          </span>
                        </header>
                        <p>
                          Saved{" "}
                          <time dateTime={record.savedAt}>{formatHomeTime(record.savedAt)}</time>
                        </p>
                        <div className="result-card-actions">
                          {record.status === "outcome_unknown" && (
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
                            <Link to={`/coverage/reviews/${record.id}`}>
                              {record.status === "outcome_unknown"
                                ? "View submission"
                                : "Continue editing"}
                              : {title}
                            </Link>
                          ) : workflow ? (
                            <Link
                              to={`${workflowUrl(record.formKey, record.sourceId ?? undefined)}&resume=${record.id}`}
                            >
                              {record.status === "outcome_unknown"
                                ? "View submission"
                                : "Continue editing"}
                              : {title}
                            </Link>
                          ) : (
                            record.status === "active" && (
                              <span>
                                {" "}
                                — Resume from the owning workflow when its editor is available.
                              </span>
                            )
                          )}
                          {["active", "outcome_unknown"].includes(record.status) && (
                            <button
                              disabled={pending || !scope.canWrite}
                              onClick={() => {
                                if (
                                  window.confirm(
                                    `Discard this ${title.toLowerCase()} form? A pending submission will be checked and safely closed first. Existing official records will not be deleted.`,
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
            </section>
          ))}
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
