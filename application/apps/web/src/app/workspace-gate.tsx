import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { QueryClientProvider, useQuery } from "@tanstack/react-query";
import { api } from "@epm/contracts";
import { Page } from "@epm/ui";
import { StedanaBrand } from "./stedana-brand";
import { BootstrapFailure, queryClient, WorkspaceScope, type Bootstrap } from "./workspace-scope";
import { HostedChanges } from "./hosted-changes";
import { HostedRecovery } from "./hosted-recovery";
import { hostedMode, managedHostedMode } from "./hosted-session-state";

class RecoveryModeActiveError extends Error {
  constructor() {
    super("recovery_mode_active");
  }
}

function isRecoveryModeErrorPayload(errorPayload: unknown): boolean {
  if (!errorPayload || typeof errorPayload !== "object") return false;
  const record = errorPayload as { code?: unknown; detail?: unknown };
  if (record.code === "recovery_mode_active") return true;
  if (
    record.detail &&
    typeof record.detail === "object" &&
    "code" in record.detail &&
    (record.detail as { code?: unknown }).code === "recovery_mode_active"
  ) {
    return true;
  }
  return false;
}

function isMaintenanceInProgressPayload(errorPayload: unknown): boolean {
  if (!errorPayload || typeof errorPayload !== "object") return false;
  const record = errorPayload as { code?: unknown; detail?: unknown };
  if (record.code === "maintenance_in_progress") return true;
  if (
    record.detail &&
    typeof record.detail === "object" &&
    "code" in record.detail &&
    (record.detail as { code?: unknown }).code === "maintenance_in_progress"
  ) {
    return true;
  }
  return false;
}

async function checkRecoveryModeStatus(signal: AbortSignal): Promise<boolean> {
  try {
    const response = await fetch("/api/hosted/recovery/status", {
      credentials: "same-origin",
      headers: { Accept: "application/json" },
      signal,
    });
    if (!response.ok) return false;
    const payload = (await response.json().catch(() => null)) as {
      mode?: unknown;
      startup?: { mode?: unknown };
    } | null;
    return payload?.mode === "recovery" || payload?.startup?.mode === "recovery";
  } catch {
    return false;
  }
}

async function loadBootstrap(signal: AbortSignal): Promise<Bootstrap> {
  let result;
  try {
    result = await api.GET("/api/operator/bootstrap", { signal });
  } catch (error) {
    if (signal.aborted) throw error;
    throw new BootstrapFailure(error instanceof TypeError);
  }
  if (!result.data || result.error) {
    if (
      result.response.status === 503 &&
      (isRecoveryModeErrorPayload(result.error) ||
        (managedHostedMode() && (await checkRecoveryModeStatus(signal))))
    ) {
      throw new RecoveryModeActiveError();
    }
    if (result.response.status === 503 && isMaintenanceInProgressPayload(result.error)) {
      throw new BootstrapFailure(
        false,
        "Updating your workspace. Unfinished drafts are preserved on this device; retry explicitly after the maintenance window finishes.",
      );
    }
    if (hostedMode() && [503, 507].includes(result.response.status)) {
      throw new BootstrapFailure(
        false,
        "Workspace storage or maintenance is preventing access. Contact the administrator; retry explicitly after it is resolved.",
      );
    }
    throw new BootstrapFailure(false);
  }
  const data = result.data;
  if (
    data.contractVersion !== 1 ||
    typeof data.serverTimeUtc !== "string" ||
    !Number.isFinite(Date.parse(data.serverTimeUtc)) ||
    !/(Z|\+00:00)$/.test(data.serverTimeUtc) ||
    !["ready", "busy", "unavailable"].includes(data.state) ||
    typeof data.runtimeEpoch !== "string" ||
    typeof data.canWrite !== "boolean" ||
    !Array.isArray(data.capabilities) ||
    !Array.isArray(data.recoveryActions) ||
    !data.recoveryActions.every((action) => action && typeof action.action === "string") ||
    (data.state === "ready" && !data.workspaceId)
  ) {
    throw new BootstrapFailure(false);
  }
  return data;
}

const Workspace = createContext<{ scope: WorkspaceScope; bootstrap: Bootstrap } | null>(null);

export function useWorkspace() {
  const value = useContext(Workspace);
  if (!value) throw new Error("Domain reads require an admitted workspace.");
  return value;
}

function Admitted({ bootstrap, children }: { bootstrap: Bootstrap; children: ReactNode }) {
  const [scope] = useState(
    () =>
      new WorkspaceScope(bootstrap.workspaceId ?? "", bootstrap.runtimeEpoch, bootstrap.canWrite),
  );
  useEffect(() => {
    scope.activate();
    return () => scope.dispose();
  }, [scope]);
  return (
    <QueryClientProvider client={scope.client}>
      <Workspace.Provider value={{ scope, bootstrap }}>
        <HostedChanges scope={scope} />
        {children}
      </Workspace.Provider>
    </QueryClientProvider>
  );
}

const explanations: Record<string, string> = {
  workspace_missing:
    "Workspace not found. Locate your existing workspace or set one up explicitly.",
  workspace_busy: "Workspace is busy. Close the other local server before reopening this one.",
  workspace_invalid:
    "Workspace could not be validated. Restore a verified backup or check its configuration.",
  workspace_migration_required:
    "Workspace format is unsupported. Use a compatible application or a supported backup. No automatic migration is available.",
};

function Gate({ children }: { children: ReactNode }) {
  const bootstrap = useQuery({
    queryKey: ["operator-bootstrap"],
    queryFn: ({ signal }) => loadBootstrap(signal),
    staleTime: 0,
    refetchOnReconnect: true,
  });
  const retry = () => void bootstrap.refetch();
  // Background readiness checks must not unmount admitted forms and discard input.
  // Errors and changed workspace identities are still handled below after the check.
  if (bootstrap.isPending) {
    return <p role="status">Checking workspace readiness…</p>;
  }
  if (bootstrap.isError && bootstrap.error instanceof RecoveryModeActiveError) {
    return <HostedRecovery forceVisible />;
  }
  const errorMessage = bootstrap.isError
    ? bootstrap.error instanceof BootstrapFailure && bootstrap.error.explanation
      ? bootstrap.error.explanation
      : bootstrap.error instanceof BootstrapFailure && bootstrap.error.network
        ? "Cannot connect to the local server. Check that it is running."
        : "The local server returned an unusable response. Workspace access is paused."
    : null;
  if (bootstrap.data?.state === "ready") {
    const data = bootstrap.data;
    return (
      <>
        {errorMessage && (
          <div role="alert" data-testid="workspace-refetch-banner">
            <p>{errorMessage}</p>
            <button onClick={retry}>Retry connection</button>
          </div>
        )}
        <div
          className="workspace-admitted"
          hidden={Boolean(errorMessage)}
          aria-hidden={errorMessage ? "true" : undefined}
          inert={Boolean(errorMessage) || undefined}
        >
          <Admitted
            key={`${data.workspaceId}:${data.runtimeEpoch}:${String(data.canWrite)}`}
            bootstrap={data}
          >
            {children}
          </Admitted>
        </div>
      </>
    );
  }
  if (errorMessage) {
    return (
      <>
        <p role="alert">{errorMessage}</p>
        <button onClick={retry}>Retry connection</button>
      </>
    );
  }
  const data = bootstrap.data;
  if (!data) {
    return null;
  }
  if (data.state !== "ready") {
    const reason = data.state === "busy" ? "workspace_busy" : (data.reasonCode ?? "");
    const supportsRetry = data.recoveryActions.some(
      (action) => action.kind === "api_operation" && action.action === "getOperatorBootstrap",
    );
    return (
      <>
        <p role="status">{explanations[reason] ?? "Local workspace unavailable."}</p>
        {supportsRetry && <button onClick={retry}>Retry workspace check</button>}
        <p>
          To locate a workspace, stop the local server and update localWorkspacePath in its local
          configuration. To restore a backup, use the local restore command with a new empty
          destination, then select that destination and restart the server.
        </p>
        {reason === "workspace_missing" && (
          <p>For a new workspace, run the explicit initialize-workspace command, then restart.</p>
        )}
      </>
    );
  }
  return null;
}

export function WorkspaceGate({ children }: { children: ReactNode }) {
  const [client] = useState(queryClient);
  return (
    <Page title="Easy Property Management" brand={<StedanaBrand variant="operator" />}>
      <QueryClientProvider client={client}>
        <Gate>{children}</Gate>
      </QueryClientProvider>
    </Page>
  );
}
