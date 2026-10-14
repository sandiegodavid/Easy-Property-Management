import { useQuery } from "@tanstack/react-query";
import { SourceWorkflowLink as Link } from "../shared/home-navigation";
import { api } from "@epm/contracts";
import { record, scalar, type Workflow } from "@epm/contracts/workflows";
import { useWorkspace } from "../app/workspace-gate";
import { Facts, readResult } from "./reads";
import { workUrl } from "./work-links";

export function OriginalWorkResult({
  definition,
  attemptKey,
  operationId,
  sourceId,
}: {
  definition: Workflow;
  attemptKey: string;
  operationId: string;
  sourceId?: string;
}) {
  const { scope } = useWorkspace();
  const result = useQuery({
    queryKey: scope.key("original-work-result", definition.formKey, attemptKey),
    queryFn: async ({ signal }) => {
      if (definition.formKey.startsWith("maintenance."))
        return record(
          readResult(
            await api.GET("/api/maintenance-command-receipts/{operation_id}", {
              signal,
              params: { path: { operation_id: operationId } },
            }),
          ).response,
        );
      if (definition.formKey.startsWith("communication."))
        return record(
          readResult(
            await api.GET("/api/communications/operations/{operation_id}", {
              signal,
              params: { path: { operation_id: operationId } },
            }),
          ),
        );
      if (definition.formKey.startsWith("owner_concern."))
        return record(
          readResult(
            await api.GET("/api/owner-concerns/operations/by-key/{key}", {
              signal,
              params: { path: { key: attemptKey } },
            }),
          ),
        );
      if (definition.formKey === "task.create")
        return record(
          readResult(
            await api.GET("/api/tasks/creation-operations/{key}", {
              signal,
              params: { path: { key: attemptKey } },
            }),
          ),
        );
      if (definition.formKey.startsWith("task.waiting."))
        return record(
          readResult(
            await api.GET("/api/tasks/waiting-operations/{key}", {
              signal,
              params: { path: { key: attemptKey } },
            }),
          ),
        );
      return record(
        readResult(
          await api.GET("/api/tasks/mutation-operations/{key}", {
            signal,
            params: { path: { key: attemptKey } },
          }),
        ),
      );
    },
  });
  const value = result.data,
    item = record(value?.task ?? value);
  const kind = definition.formKey.startsWith("task.")
    ? "task"
    : definition.formKey.startsWith("communication.")
      ? "communication"
      : definition.formKey.startsWith("owner_concern.")
        ? "concern"
        : "issue";
  return (
    <>
      {result.isPending && <p role="status">Loading original work receipt…</p>}
      {result.error && (
        <p role="alert">
          The command committed, but its original details are unavailable: {result.error.message}
        </p>
      )}
      {value && (
        <>
          <p>This is the original committed response.</p>
          <Facts
            value={item}
            fields={[
              "summary",
              "subject",
              "title",
              "status",
              "revision",
              "priority",
              "waitingForKind",
              "waitingForLabel",
              "followUpAt",
              "dueAtUtc",
              "outcomeNote",
              "outcomeStatus",
              "operatorVerified",
              "startsAtUtc",
              "endsAtUtc",
              "updatedAt",
              "updatedAtUtc",
            ]}
          />
          <Facts
            value={value.reminder}
            fields={["status", "remindAtUtc", "acknowledgedAtUtc", "dismissedAtUtc"]}
          />
          {[
            ...(Array.isArray(item.followUpTasks) ? item.followUpTasks.map(record) : []),
            ...(value.followUpTask ? [record(value.followUpTask)] : []),
            ...(definition.formKey === "maintenance.follow_up.create" ? [item] : []),
          ].map((task) => (
            <p key={scalar(task.id)}>
              Original follow-up: {scalar(task.title)} · {scalar(task.status)} ·{" "}
              {scalar(task.dueAtUtc, "No deadline")} ·{" "}
              <Link to={workUrl("task", scalar(task.id))}>Open follow-up task</Link>
            </p>
          ))}
          <Link
            to={workUrl(
              kind,
              scalar(
                kind === "issue" ? (sourceId ?? item.issueId ?? item.id) : (item.id ?? sourceId),
              ),
            )}
          >
            Open current work record
          </Link>
        </>
      )}
    </>
  );
}
