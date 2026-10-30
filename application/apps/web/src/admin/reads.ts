import { useEffect, useState } from "react";

export type Read<T> = { data?: T; failed: boolean; expired: boolean };
export type Observation<T> = {
  state: "available" | "unknown" | "stale";
  observed?: number | null;
  attempted?: number | null;
  refreshing?: boolean;
  data?: T | null;
};
export type Access = {
  active: boolean;
  binding_matches: boolean;
  pending_enrollments: number;
  starts: number;
  expires: number;
  capabilities: string[];
};
export type Runtime = { service: string; mount_verified: boolean; release_matches: boolean };
export type Recovery = {
  local_archive: number | null;
  off_host_readback: number | null;
  restore_drill: number | null;
  approved_binding: number | null;
  policy_state?: "unknown" | "failed" | "warning" | "overdue" | "verified" | "stale";
  attempted?: number | null;
  acknowledged?: boolean;
};
export type Operator = {
  key: string;
  name: string;
  email: string;
  hostname: string;
  release: string;
  profile: string;
  setup_id?: string | null;
  access: Observation<Access>;
  runtime: Observation<Runtime>;
  recovery: Observation<Recovery>;
};
export type Directory = { items: Operator[]; total: number; offset: number; next: number | null };
export type Capacity = {
  environment_hash: string;
  release: string;
  profile: string;
  memory_total: number;
  memory_committed: number;
  disk_total: number;
  disk_free: number;
  disk_committed: number;
  inventory_clear: boolean;
  active_count: number;
};
export type Qualification = {
  capacity: { ceiling: number; environment_hash: string } | null;
  plans: { id: string; state: string; created: number }[];
  evidence: {
    qualification_id: string;
    kind: string;
    observed: number;
    expires: number;
    passed: boolean;
  }[];
  evidence_limit: number;
};
export type Operation = {
  id: string;
  kind: string;
  target: string;
  state: string;
  created: number;
  updated: number;
  actor: string;
  reason: string;
  error: string | null;
  steps: { sequence: number; kind: string; state: string; checked: number | null }[];
  events: { action: string; recorded: number }[];
};
export type OperationList = {
  items: Pick<Operation, "id" | "kind" | "target" | "state" | "created" | "updated">[];
};

export function useRead<T>(path: string, interval = 30000): Read<T> {
  const [read, setRead] = useState<Read<T> & { path?: string }>({ failed: false, expired: false });
  useEffect(() => {
    let ended = false,
      timer: ReturnType<typeof setTimeout> | undefined;
    let controller: AbortController | undefined;
    let delay = interval;
    const load = async () => {
      if (document.hidden || ended) return;
      controller?.abort();
      controller = new AbortController();
      const current = controller;
      let timedOut = false;
      const deadline = setTimeout(() => {
        timedOut = true;
        current.abort();
      }, 10000);
      try {
        const response = await fetch(path, {
          credentials: "same-origin",
          cache: "no-store",
          signal: current.signal,
        });
        if (response.status === 401 || response.status === 403) {
          if (!ended)
            setRead((prior) => ({
              ...(prior.path === path ? prior : {}),
              path,
              failed: true,
              expired: true,
            }));
          return;
        }
        if (!response.ok) throw new Error("Read unavailable");
        const data = (await response.json()) as T;
        if (current.signal.aborted || current !== controller) return;
        if (!ended) setRead({ data, path, failed: false, expired: false });
        delay = interval;
        if (
          data &&
          typeof data === "object" &&
          "state" in data &&
          ["succeeded", "cancelled"].includes(String(data.state))
        )
          delay = 30000;
      } catch {
        if (ended || current !== controller || (current.signal.aborted && !timedOut)) return;
        if (!ended)
          setRead((prior) => ({
            ...(prior.path === path ? prior : {}),
            path,
            failed: true,
            expired: false,
          }));
        delay = Math.min(delay * 2, 60000);
      } finally {
        clearTimeout(deadline);
      }
      if (!ended)
        timer = setTimeout(() => {
          void load();
        }, delay);
    };
    const visibility = () => {
      if (timer) clearTimeout(timer);
      if (document.hidden) controller?.abort();
      else void load();
    };
    document.addEventListener("visibilitychange", visibility);
    void load();
    return () => {
      ended = true;
      controller?.abort();
      clearTimeout(timer);
      document.removeEventListener("visibilitychange", visibility);
    };
  }, [path, interval]);
  return read.path === path ? read : { failed: false, expired: false };
}

export function words(value: string) {
  const text = value.replaceAll("_", " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}
export function time(value?: number | null) {
  if (value === undefined || value === null) return "Not verified";
  return (
    new Intl.DateTimeFormat(undefined, {
      dateStyle: "medium",
      timeStyle: "long",
    }).format(new Date(value * 1000)) +
    " · " +
    Intl.DateTimeFormat().resolvedOptions().timeZone
  );
}
export function lifecycle(value?: Access | null) {
  if (!value) return "Unknown";
  const now = Date.now() / 1000;
  if (!value.binding_matches) return "Binding needs review";
  if (now >= value.expires) return "Expired";
  if (now < value.starts) return "Scheduled";
  if (value.active) return "Access enabled";
  if (value.pending_enrollments) return "Enrollment needs review";
  return "Access blocked";
}
