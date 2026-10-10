import { api } from "@epm/contracts";
import { RecoveryController, recoveryApi, type Recovery } from "../src/shared/recovery";
import { mutation, canonicalRequest, normalizeApiError } from "../src/shared/mutations";
import { WorkspaceScope } from "../src/app/workspace-scope";

export async function setup() {
  const bootstrap = await api.GET("/api/operator/bootstrap");
  if (!bootstrap.data?.workspaceId) throw new Error("Workspace unavailable.");
  const task = await mutation(() =>
    api.POST("/api/tasks", {
      body: {
        title: "Recovery proof",
        status: "open",
        priority: "normal",
        isAllDay: false,
        expectedRevision: 0,
        idempotencyKey: crypto.randomUUID(),
      },
    }),
  );
  const scope = new WorkspaceScope(bootstrap.data.workspaceId, bootstrap.data.runtimeEpoch, true);
  const id = crypto.randomUUID();
  const initial = { expectedRevision: task.revision, changes: { title: "Recovered edit" } };
  const identity = {
    formKey: "task.edit" as const,
    schemaVersion: 1,
    sourceKind: "task" as const,
    sourceId: task.id,
    baseSourceRevision: String(task.revision),
  };
  const controller = new RecoveryController(scope, id, identity, initial);
  return { controller, scope, id, task, initial, identity };
}
async function dispatch(record: Recovery) {
  if (!record.sourceId || !record.attemptKey) throw new Error("Missing prepared command.");
  const changes = record.payload.changes as { title: string };
  return mutation(() =>
    api.PATCH("/api/tasks/{task_id}", {
      params: { path: { task_id: record.sourceId ?? "" } },
      body: {
        ...changes,
        expectedRevision: record.payload.expectedRevision as number,
        idempotencyKey: record.attemptKey ?? "",
      },
    }),
  );
}
const fixture = {
  setup,
  dispatch,
  api,
  mutation,
  canonicalRequest,
  normalizeApiError,
  RecoveryController,
  recoveryApi,
};
declare global {
  interface Window {
    recoveryFixture: typeof fixture;
  }
}
window.recoveryFixture = fixture;
