import { useEffect, useState } from "react";
import { api } from "@epm/contracts";
import { hostedMode, hostedWritesAllowed, pauseHostedSession } from "./hosted-session-state";
import type { WorkspaceScope } from "./workspace-scope";

// Additional signal only; Home still owns time transitions and attention refresh.
export function HostedChanges({ scope }: { scope: WorkspaceScope }) {
  const [stale, setStale] = useState(false);
  useEffect(() => {
    if (!hostedMode()) return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let pending: AbortController | undefined;
    let marker: string | undefined;
    let failures = 0;
    const visible = () => document.visibilityState === "visible" && hostedWritesAllowed();
    const schedule = () => {
      clearTimeout(timer);
      if (!stopped && visible()) {
        const delay = Math.min(60_000, 15_000 * 2 ** failures);
        timer = setTimeout(() => void check(), delay * (0.9 + Math.random() * 0.2));
      }
    };
    async function check() {
      if (stopped || pending || !visible()) return;
      const controller = new AbortController();
      pending = controller;
      try {
        const result = await api.GET("/api/operator/changes", { signal: controller.signal });
        if (stopped || controller.signal.aborted || !visible()) return;
        if (!result.data || result.error) throw new Error("Change check unavailable.");
        const data = result.data;
        if (data.workspaceId !== scope.workspaceId || data.runtimeEpoch !== scope.runtimeEpoch) {
          window.dispatchEvent(new Event("epm-runtime-changed"));
          pauseHostedSession(
            "Workspace runtime changed. Sign in explicitly to reopen current data.",
          );
          return;
        }
        if (marker !== undefined && marker !== data.sourceRevision)
          void scope.client.invalidateQueries();
        marker = data.sourceRevision;
        failures = 0;
        setStale(false);
      } catch {
        if (!stopped && !controller.signal.aborted) {
          failures = Math.min(failures + 1, 2);
          setStale(true);
        }
      } finally {
        pending = undefined;
        schedule();
      }
    }
    const resume = () => {
      clearTimeout(timer);
      if (visible()) void check();
      else pending?.abort();
    };
    const pause = () => {
      clearTimeout(timer);
      pending?.abort();
    };
    window.addEventListener("focus", resume);
    window.addEventListener("online", resume);
    window.addEventListener("epm-session-paused", pause);
    document.addEventListener("visibilitychange", resume);
    void check();
    return () => {
      stopped = true;
      pause();
      window.removeEventListener("focus", resume);
      window.removeEventListener("online", resume);
      window.removeEventListener("epm-session-paused", pause);
      document.removeEventListener("visibilitychange", resume);
    };
  }, [scope]);
  return stale ? (
    <p role="status">
      Updates could not be checked. Displayed data may be stale; no changes are queued offline.
    </p>
  ) : null;
}
