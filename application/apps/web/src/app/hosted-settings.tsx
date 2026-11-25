import { useCallback, useEffect, useState } from "react";
import { HostedRecovery } from "./hosted-recovery";
import { checkHostedResponse, managedHostedMode } from "./hosted-session-state";

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
  state?: "healthy" | "unchanged" | "overdue" | "unavailable" | "unknown" | null;
  last_verified_at?: number | null;
  point_age_ms?: number | null;
  proof_ref?: string | null;
};

type MaintenanceData = {
  message?: string | null;
  starts_at?: number | string | null;
  ends_at?: number | string | null;
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

function formatWindowBoundary(value: number | string | null | undefined): string | null {
  if (typeof value === "number" && Number.isFinite(value)) return formatEpochMs(value);
  if (typeof value === "string" && value.trim()) return value;
  return null;
}

export function isMaintenanceInProgressRevision(
  sourceRevision: string | null | undefined,
): boolean {
  return (
    typeof sourceRevision === "string" && sourceRevision.startsWith("maintenance:in_progress:")
  );
}

export function HostedMaintenanceBanner() {
  const hosted = managedHostedMode();
  const [notice, setNotice] = useState<{
    inProgress: boolean;
    message: string;
    windowLabel: string | null;
  } | null>(null);

  useEffect(() => {
    if (!hosted) return;
    let active = true;
    let controller: AbortController | null = null;
    const refresh = () => {
      if (!active || document.visibilityState === "hidden") return;
      controller?.abort();
      controller = new AbortController();
      fetchHostedSettings(controller.signal)
        .then((payload) => {
          if (!active) return;
          if (payload.maintenance.state === "ready" && payload.maintenance.data?.message) {
            const start = formatWindowBoundary(payload.maintenance.data.starts_at);
            const end = formatWindowBoundary(payload.maintenance.data.ends_at);
            setNotice({
              inProgress: isMaintenanceInProgressRevision(
                payload.maintenance.freshness?.source_revision,
              ),
              message: payload.maintenance.data.message,
              windowLabel: start && end ? `${start} – ${end}` : null,
            });
          } else {
            setNotice(null);
          }
        })
        .catch(() => {
          // Non-blocking banner: never interrupt active workspace editing on background fetch error.
        });
    };
    refresh();
    const timer = window.setInterval(refresh, 60_000);
    window.addEventListener("focus", refresh);
    document.addEventListener("visibilitychange", refresh);
    return () => {
      active = false;
      window.clearInterval(timer);
      window.removeEventListener("focus", refresh);
      document.removeEventListener("visibilitychange", refresh);
      controller?.abort();
    };
  }, [hosted]);

  if (!hosted || !notice) return null;

  return (
    <div
      role="status"
      aria-live="polite"
      data-testid={
        notice.inProgress ? "hosted-maintenance-in-progress" : "hosted-maintenance-announced"
      }
      className="hosted-maintenance-banner"
    >
      <strong>
        {notice.inProgress ? "Updating your workspace" : "Scheduled maintenance window"}
      </strong>
      {": "}
      <span>{notice.message}</span>
      {notice.inProgress && (
        <span> Unfinished drafts are preserved; retry explicitly after the update completes.</span>
      )}
      {notice.windowLabel && <span> ({notice.windowLabel})</span>}
    </div>
  );
}

async function fetchHostedSettings(signal?: AbortSignal): Promise<HostedSettingsPayload> {
  const response = await fetch("/api/hosted/settings", {
    method: "GET",
    credentials: "same-origin",
    headers: { Accept: "application/json" },
    signal,
  });
  await checkHostedResponse(response);
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
    <>
      <section className="settings-card" aria-labelledby="hosted-settings-heading">
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
                    {state.payload.protection.data.state === "unchanged"
                      ? "Protected — unchanged since verified point"
                      : state.payload.protection.data.status === "protected"
                        ? "Protected"
                        : "Degraded"}
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
                      <p>
                        <strong>
                          {isMaintenanceInProgressRevision(
                            state.payload.maintenance.freshness?.source_revision,
                          )
                            ? "Updating your workspace: "
                            : "Scheduled window: "}
                        </strong>
                        {state.payload.maintenance.data.message}
                      </p>
                      {(() => {
                        const start = formatWindowBoundary(
                          state.payload.maintenance.data.starts_at,
                        );
                        const end = formatWindowBoundary(state.payload.maintenance.data.ends_at);
                        return start && end ? (
                          <p className="ui-muted">
                            Window: {start} – {end}
                          </p>
                        ) : null;
                      })()}
                    </dd>
                  </>
                )}
            </dl>
            <p className="ui-muted" data-testid="pilot0-disclosure">
              Free invitation-only pilot · Best-effort support · 24-hour nightly backup objective
              with platform-managed encryption keys (not zero-knowledge) · Shared announced
              maintenance window · No contractual SLA.
            </p>
            <button type="button" disabled={refreshing} onClick={() => void refresh()}>
              {refreshing ? "Refreshing…" : "Refresh storage usage"}
            </button>
          </div>
        )}
      </section>
      <HostedRecovery embedded />
    </>
  );
}
