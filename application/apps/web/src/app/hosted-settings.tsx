import { useCallback, useEffect, useState } from "react";
import { HostedRecovery } from "./hosted-recovery";
import { managedHostedMode } from "./hosted-session-state";

type SectionFreshness = {
  state?: string;
  as_of?: number | null;
  source_revision?: string | null;
  error_code?: string | null;
};

type UsageData = {
  plan: string;
  usable_bytes: number;
  used_bytes: number;
};

type ProtectionData = {
  status: "protected" | "degraded";
  last_verified_at?: number | null;
  point_age_ms?: number | null;
  proof_ref?: string | null;
};

type MaintenanceData = {
  message?: string | null;
  starts_at?: string | null;
  ends_at?: string | null;
};

type UsageBreakdown = {
  committedDbBytes: number;
  retainedFileBytes: number;
  reservedBytes: number;
  remainingBytes: number;
  measurementVersion: string;
};

export type HostedSettingsPayload = {
  surface: string;
  delivery_owner?: string;
  usage: {
    state: string;
    data: UsageData | null;
    freshness?: SectionFreshness | null;
  };
  protection: {
    state: string;
    data: ProtectionData | null;
    freshness?: SectionFreshness | null;
  };
  support_contact: string | null;
  maintenance: {
    state: string;
    data: MaintenanceData | null;
    freshness?: SectionFreshness | null;
  };
  usageBreakdown?: UsageBreakdown | null;
};

type LoadState =
  | { status: "loading" }
  | { status: "ready"; payload: HostedSettingsPayload }
  | { status: "error"; message: string };

function formatDecimalBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) return "0 B";
  if (bytes >= 1_000_000) return `${(bytes / 1_000_000).toFixed(2)} MB`;
  if (bytes >= 1_000) return `${(bytes / 1_000).toFixed(1)} KB`;
  return `${bytes} B`;
}

function formatPlanName(plan: string): string {
  if (plan.toLowerCase() === "free") return "Free pilot";
  return plan;
}

function formatEpochMs(epochMs: number): string {
  return new Date(epochMs).toISOString();
}

async function fetchHostedSettings(signal?: AbortSignal): Promise<HostedSettingsPayload> {
  const response = await fetch("/api/hosted/settings", {
    method: "GET",
    credentials: "same-origin",
    headers: { Accept: "application/json" },
    signal,
  });
  if (!response.ok) {
    throw new Error("Workspace plan and storage details are currently unavailable.");
  }
  return (await response.json()) as HostedSettingsPayload;
}

export function HostedSettings() {
  const hosted = managedHostedMode();
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const [refreshing, setRefreshing] = useState(false);

  useEffect(() => {
    if (!hosted) return;
    const controller = new AbortController();
    let active = true;
    fetchHostedSettings(controller.signal)
      .then((payload) => {
        if (active) setState({ status: "ready", payload });
      })
      .catch((error: unknown) => {
        if (!active || controller.signal.aborted) return;
        setState({
          status: "error",
          message:
            error instanceof Error
              ? error.message
              : "Workspace plan and storage details are currently unavailable.",
        });
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [hosted]);

  const refresh = useCallback(async () => {
    setRefreshing(true);
    try {
      const payload = await fetchHostedSettings();
      setState({ status: "ready", payload });
    } catch (error) {
      setState({
        status: "error",
        message:
          error instanceof Error
            ? error.message
            : "Workspace plan and storage details are currently unavailable.",
      });
    } finally {
      setRefreshing(false);
    }
  }, []);

  if (!hosted) return null;

  return (
    <section aria-labelledby="hosted-settings-heading">
      <h3 id="hosted-settings-heading">Workspace plan and storage</h3>
      {state.status === "loading" && <p role="status">Loading workspace plan and storage…</p>}
      {state.status === "error" && (
        <div>
          <p role="alert">{state.message}</p>
          <button type="button" disabled={refreshing} onClick={() => void refresh()}>
            {refreshing ? "Refreshing…" : "Retry"}
          </button>
        </div>
      )}
      {state.status === "ready" && (
        <div>
          <dl>
            <dt>Plan</dt>
            <dd>
              {state.payload.usage.state === "ready" && state.payload.usage.data
                ? `${formatPlanName(state.payload.usage.data.plan)} (${formatDecimalBytes(state.payload.usage.data.usable_bytes)} logical storage)`
                : "Free pilot (50.00 MB logical storage)"}
            </dd>

            <dt>Storage usage</dt>
            <dd>
              {state.payload.usage.state === "ready" && state.payload.usage.data ? (
                (() => {
                  const usable = Math.max(1, state.payload.usage.data.usable_bytes);
                  const used = Math.max(0, state.payload.usage.data.used_bytes);
                  const remaining =
                    state.payload.usageBreakdown?.remainingBytes ?? Math.max(0, usable - used);
                  const percent = Math.min(100, Math.round((used / usable) * 100));
                  return (
                    <div>
                      <progress
                        aria-label="Free pilot storage usage"
                        max={usable}
                        value={Math.min(used, usable)}
                      />
                      <p>
                        {formatDecimalBytes(used)} of {formatDecimalBytes(usable)} used ({percent}
                        %) — {formatDecimalBytes(remaining)} remaining.
                      </p>
                      {state.payload.usageBreakdown && (
                        <p className="ui-muted">
                          Database:{" "}
                          {formatDecimalBytes(state.payload.usageBreakdown.committedDbBytes)}
                          {" · "}Retained files:{" "}
                          {formatDecimalBytes(state.payload.usageBreakdown.retainedFileBytes)}
                          {state.payload.usageBreakdown.reservedBytes > 0
                            ? ` · Active writes: ${formatDecimalBytes(state.payload.usageBreakdown.reservedBytes)}`
                            : ""}
                        </p>
                      )}
                      {typeof state.payload.usage.freshness?.as_of === "number" && (
                        <p className="ui-muted">
                          Observed at {formatEpochMs(state.payload.usage.freshness.as_of)}
                        </p>
                      )}
                      {percent >= 90 && (
                        <p role="status">
                          Storage is near the Free pilot 50.00 MB limit. Remove unneeded files or
                          contact the administrator if you need help.
                        </p>
                      )}
                    </div>
                  );
                })()
              ) : (
                <p>
                  Unavailable
                  {state.payload.usage.freshness?.error_code
                    ? ` (${state.payload.usage.freshness.error_code})`
                    : ""}
                  .
                </p>
              )}
            </dd>

            <dt>Backup protection</dt>
            <dd>
              {state.payload.protection.state === "ready" && state.payload.protection.data ? (
                <p>
                  {state.payload.protection.data.status === "protected" ? "Protected" : "Degraded"}
                  {typeof state.payload.protection.data.last_verified_at === "number"
                    ? ` — latest verified point: ${formatEpochMs(state.payload.protection.data.last_verified_at)}`
                    : ""}
                </p>
              ) : (
                <p>Unavailable — backup protection is not yet active.</p>
              )}
            </dd>

            <dt>Support contact</dt>
            <dd>{state.payload.support_contact ?? "Contact your workspace administrator."}</dd>

            {state.payload.maintenance.state === "ready" &&
              state.payload.maintenance.data?.message && (
                <>
                  <dt>Maintenance notice</dt>
                  <dd>
                    <p>{state.payload.maintenance.data.message}</p>
                  </dd>
                </>
              )}
          </dl>
          <button type="button" disabled={refreshing} onClick={() => void refresh()}>
            {refreshing ? "Refreshing…" : "Refresh storage usage"}
          </button>
        </div>
      )}
      <HostedRecovery embedded />
    </section>
  );
}
