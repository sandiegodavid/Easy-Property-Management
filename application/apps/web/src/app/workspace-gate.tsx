import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { QueryClientProvider, useQuery } from "@tanstack/react-query";
import { api } from "@epm/contracts";
import { Page } from "@epm/ui";
import { BootstrapFailure, queryClient, WorkspaceScope, type Bootstrap } from "./workspace-scope";

const brandAssets = [
  {
    appearance: "light",
    icon: new URL("../assets/brand/logo-4-light.png", import.meta.url).href,
    wordmark: new URL("../assets/brand/logo-text-4-light.png", import.meta.url).href,
  },
  {
    appearance: "dark",
    icon: new URL("../assets/brand/logo-4-dark.png", import.meta.url).href,
    wordmark: new URL("../assets/brand/logo-text-4-dark.png", import.meta.url).href,
  },
];

async function loadBootstrap(signal: AbortSignal): Promise<Bootstrap> {
  let result;
  try {
    result = await api.GET("/api/operator/bootstrap", { signal });
  } catch (error) {
    if (signal.aborted) throw error;
    throw new BootstrapFailure(error instanceof TypeError);
  }
  if (!result.data || result.error) throw new BootstrapFailure(false);
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
      <Workspace.Provider value={{ scope, bootstrap }}>{children}</Workspace.Provider>
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
  if (bootstrap.isFetching || bootstrap.isPending) {
    return <p role="status">Checking workspace readiness…</p>;
  }
  if (bootstrap.isError) {
    return (
      <>
        <p role="alert">
          {bootstrap.error instanceof BootstrapFailure && bootstrap.error.network
            ? "Cannot connect to the local server. Check that it is running."
            : "The local server returned an unusable response. Workspace access is paused."}
        </p>
        <button onClick={retry}>Retry connection</button>
      </>
    );
  }
  const data = bootstrap.data;
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
  return (
    <Admitted
      key={`${data.workspaceId}:${data.runtimeEpoch}:${String(data.canWrite)}`}
      bootstrap={data}
    >
      {children}
    </Admitted>
  );
}

export function WorkspaceGate({ children }: { children: ReactNode }) {
  const [client] = useState(queryClient);
  return (
    <Page
      title="Easy Property Management"
      brand={
        <>
          {brandAssets.map(({ appearance, icon, wordmark }) => (
            <picture key={appearance} className={`workspace-brand workspace-brand-${appearance}`}>
              <source media="(max-width: 767px)" srcSet={icon} />
              <img src={wordmark} alt="Easy Property Management" width="2172" height="724" />
            </picture>
          ))}
        </>
      }
    >
      <QueryClientProvider client={client}>
        <Gate>{children}</Gate>
      </QueryClientProvider>
    </Page>
  );
}
