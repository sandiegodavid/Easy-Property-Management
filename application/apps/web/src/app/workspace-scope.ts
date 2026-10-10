import { QueryClient } from "@tanstack/react-query";
import type { components } from "@epm/contracts/generated";

export type Bootstrap = components["schemas"]["BootstrapResponse"];

export class BootstrapFailure extends Error {
  constructor(public readonly network: boolean) {
    super(network ? "Local server connection failed." : "Local server response could not be used.");
  }
}

export function readRetry(failures: number, error: Error) {
  return error instanceof BootstrapFailure && error.network && failures < 1;
}

export function queryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: readRetry, retryDelay: 250, refetchOnWindowFocus: true },
      mutations: { retry: false },
    },
  });
}

// A scope owns query pages/continuations and is never persisted across workspaces.
export class WorkspaceScope {
  readonly client = queryClient();
  private active = true;
  constructor(
    readonly workspaceId: string,
    readonly runtimeEpoch: string,
    readonly canWrite: boolean,
  ) {}

  key(...parts: readonly unknown[]) {
    return [this.workspaceId, this.runtimeEpoch, ...parts] as const;
  }

  activate() {
    this.active = true;
  }

  requireWrite() {
    if (!this.active || !this.canWrite) throw new Error("Workspace writes are unavailable.");
  }

  dispose() {
    this.active = false;
    void this.client.cancelQueries();
    this.client.clear();
  }
}
