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
  async function reconcile(id: string) {
    setPending(true);
    setError(undefined);
    try {
      scope.requireWrite();
      const current = await api.GET("/api/operator/recovery/{record_id}", {
        params: { path: { record_id: id } },
      });
      if (!current.data) throw new Error("This recovery record could not be loaded.");
      if (current.data.status === "outcome_unknown")
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
        restart. An unresolved attempt must be reconciled before another submission.
      </p>
      {records.isPending && <p role="status">Loading unfinished forms…</p>}
      {records.error && <p role="alert">{records.error.message}</p>}
      {error && <p role="alert">{error}</p>}
      {records.data && (
        <>
          <PageAsOf asOf={records.data.asOf} />
          <p>{records.data.matchingTotal} forms</p>
          {records.data.items.length === 0 && <p>No unfinished forms on this page.</p>}
          <ul>
            {records.data.items.map((record) => (
              <li key={record.id}>
                {record.formKey} · {record.status} · Saved {record.savedAt}
                {record.status === "outcome_unknown" && (
                  <button
                    disabled={pending || !scope.canWrite}
                    onClick={() => {
                      void reconcile(record.id);
                    }}
                  >
                    Reconcile attempt
                  </button>
                )}
                {record.formKey === "coverage.review" &&
                  ["active", "outcome_unknown"].includes(record.status) && (
                    <Link to={`/coverage/reviews/${record.id}`}>Resume information review</Link>
                  )}
                {workflows.some((workflow) => workflow.formKey === record.formKey) &&
                ["active", "outcome_unknown"].includes(record.status) ? (
                  <Link
                    to={`${workflowUrl(record.formKey, record.sourceId ?? undefined)}&resume=${record.id}`}
                  >
                    Resume {record.formKey}
                  </Link>
                ) : (
                  record.status === "active" && (
                    <span> — Resume from the owning workflow when its editor is available.</span>
                  )
                )}
              </li>
            ))}
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
