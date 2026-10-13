import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { api } from "@epm/contracts";
import { record, workflows } from "@epm/contracts/workflows";
import { useWorkspace } from "../app/workspace-gate";
import { CommandLoader } from "./command";
import { readResult } from "./reads";

export function MaintenanceEvidenceArchive() {
  const [params] = useSearchParams();
  const target = params.get("target"),
    issueId = params.get("issueId");
  const { scope } = useWorkspace();
  const link = useQuery({
    queryKey: scope.key("maintenance-evidence-archive", target, issueId),
    enabled: !!target && !!issueId,
    queryFn: async ({ signal }) => {
      const value = readResult(
        await api.GET("/api/file-links/{link_id}", {
          signal,
          params: { path: { link_id: target! } },
        }),
      );
      const issue = readResult(
        await api.GET("/api/maintenance-issues/{issue_id}", {
          signal,
          params: { path: { issue_id: issueId! } },
        }),
      );
      const journal =
        value.entityType === "maintenance_work_journal_entry"
          ? readResult(
              await api.GET("/api/maintenance-issues/{issue_id}/work-journal", {
                signal,
                params: {
                  path: { issue_id: issueId! },
                  query: { pageSize: 20, cursor: params.get("journalCursor") ?? undefined },
                },
              }),
            ).items
          : [];
      const members =
        value.entityType === "maintenance_issue"
          ? [issue]
          : value.entityType === "maintenance_appointment"
            ? issue.appointments
            : value.entityType === "maintenance_cost_context"
              ? issue.costContexts
              : value.entityType === "maintenance_quote"
                ? issue.quotes
                : value.entityType === "maintenance_assignment"
                  ? issue.assignments
                  : journal;
      if (!members.some((member) => member.id === value.entityId))
        throw new Error("Select Maintenance evidence from its owning issue or child record.");
      return value;
    },
  });
  if (!target || !issueId)
    return <p role="alert">Select the issue's evidence association first.</p>;
  if (link.isPending) return <p role="status">Loading retained evidence association…</p>;
  if (link.error) return <p role="alert">{link.error.message}</p>;
  return (
    <>
      <p>
        Archive only this evidence association. The issue, child record, file bytes and contextual
        reason remain retained. This does not resolve a repair or erase evidence history.
      </p>
      {link.data.archivedAt && (
        <p>
          This association is already archived; its file and history remain retained. Reconcile the
          original attempt rather than starting another archive command.
        </p>
      )}
      <CommandLoader
        definition={workflows.find((item) => item.formKey === "file.link.archive")!}
        sourceId={target}
        revision={link.data.revision}
        canSubmit={() => !link.data.archivedAt}
        returnTo={`/maintenance?record=issue&id=${issueId}`}
        reviewSource={async () => {
          const current = readResult(
            await api.GET("/api/file-links/{link_id}", { params: { path: { link_id: target } } }),
          );
          return { revision: current.revision, value: record(current) };
        }}
      />
    </>
  );
}
