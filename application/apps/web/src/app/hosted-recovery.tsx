import { useCallback, useEffect, useRef, useState } from "react";
import { hostedCsrfToken, managedHostedMode } from "./hosted-session-state";

export type RecoveryProtectionState = string;

export type RecoveryPointSummary = {
  resource_id: string;
  revision?: number;
  state?: string;
  captured_at?: number | null;
  verified_at?: number | null;
  schema_compatible?: boolean;
  summary?: {
    captured_at?: number | null;
    verified_at?: number | null;
    schema_compatible?: boolean;
    business_schema_revision?: string | null;
  } | null;
};

export type OperatorRecoveryStatusPayload = {
  mode: "normal" | "recovery";
  state: "unavailable" | "choose_point" | "confirm" | "running" | "outcome_unknown" | "completed";
  availability_reason?: string | null;
  selected_point_id?: string | null;
  catalog: {
    state: string;
    data: {
      items: RecoveryPointSummary[];
      freshness?: { state?: string; as_of?: number | null; error_code?: string | null } | null;
    } | null;
  };
  protection: {
    state: RecoveryProtectionState;
    lastPointId: string | null;
    lastCapturedAt: number | null;
    lastVerifiedAt: number | null;
    lastCheckedAt: number | null;
    dirtySince: number | null;
    lastErrorCode: string | null;
  };
  startup: {
    mode: "normal" | "recovery";
    reason: string | null;
    interruptedRestoreId: string | null;
    pendingAcceptanceId: string | null;
  };
};

export type RestorePreviewPayload = {
  previewId: string;
  pointId: string;
  workspaceId: string;
  sourceEpoch: number;
  sourceGeneration: number;
  currentBusinessRevision: string | null;
  selectedCapturedAt: number;
  selectedVerifiedAt: number;
  exactRequestHash: string;
  expiresAt: number;
  recoveryMode: boolean;
  stepUpChallengeId: string;
  stepUpExpiresAt: number;
};

export type RestoreOperationDetail = {
  operationId: string;
  pointId: string;
  previewId: string;
  phase: string;
  state: string;
  priorBusinessRef?: string | null;
  priorTreeKind?: string | null;
  targetBusinessRef?: string | null;
  newSourceGeneration?: number | null;
  newAccessEpoch?: number | null;
  startedAt?: number | null;
  updatedAt?: number | null;
  acceptedAt?: number | null;
  errorCode?: string | null;
};

type LoadState =
  | { status: "loading" }
  | { status: "ready"; payload: OperatorRecoveryStatusPayload }
  | { status: "unavailable"; message: string };

function createIdempotencyKey(prefix: string): string {
  const random =
    typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
      ? crypto.randomUUID()
      : `${Date.now()}`;
  return `${prefix}-${random}`;
}

function formatEpoch(epochMs: number | null | undefined): string {
  if (typeof epochMs !== "number" || !Number.isFinite(epochMs)) return "Unavailable";
  return new Date(epochMs).toISOString();
}

function protectionPresentation(state: RecoveryProtectionState): {
  icon: string;
  label: string;
} {
  switch (state) {
    case "healthy":
      return { icon: "✓", label: "Protected" };
    case "unchanged":
      return { icon: "✓", label: "Protected — unchanged since verified point" };
    case "overdue":
      return { icon: "⚠", label: "Degraded" };
    case "unknown":
      return { icon: "?", label: "Unknown" };
    default:
      return { icon: "!", label: "Unavailable" };
  }
}

function pointCapturedAt(point: RecoveryPointSummary): number | null {
  return point.captured_at ?? point.summary?.captured_at ?? null;
}

function pointVerifiedAt(point: RecoveryPointSummary): number | null {
  return point.verified_at ?? point.summary?.verified_at ?? null;
}

function pointSchemaCompatible(point: RecoveryPointSummary): boolean {
  return point.schema_compatible ?? point.summary?.schema_compatible ?? true;
}

async function recoveryFetch<T>(
  path: string,
  options?: { method?: "GET" | "POST"; body?: object; signal?: AbortSignal },
): Promise<T> {
  const method = options?.method ?? (options?.body ? "POST" : "GET");
  const csrf = hostedCsrfToken();
  const response = await fetch(path, {
    method,
    credentials: "same-origin",
    headers: {
      Accept: "application/json",
      ...(options?.body ? { "Content-Type": "application/json" } : {}),
      ...(method === "POST" && csrf ? { "X-EPM-CSRF": csrf } : {}),
    },
    body: options?.body ? JSON.stringify(options.body) : undefined,
    signal: options?.signal,
  });
  const parsed = (await response.json().catch(() => ({}))) as {
    error?: { code?: string; message?: string };
    state?: string;
  };
  if (!response.ok) {
    const code = parsed.error?.code ?? parsed.state ?? `http_${response.status}`;
    throw new Error(parsed.error?.message ?? `Recovery request could not be completed (${code}).`);
  }
  return parsed as T;
}

export function HostedRecovery({
  embedded = false,
  forceVisible = false,
}: {
  embedded?: boolean;
  forceVisible?: boolean;
}) {
  const hosted = forceVisible || managedHostedMode();
  const [loadState, setLoadState] = useState<LoadState>({ status: "loading" });
  const [selectedPointId, setSelectedPointId] = useState<string>("");
  const [preview, setPreview] = useState<RestorePreviewPayload | null>(null);
  const [confirmKey, setConfirmKey] = useState<string>(() => createIdempotencyKey("restore"));
  const [recentAuthGrant, setRecentAuthGrant] = useState<string>("");
  const [confirmChecked, setConfirmChecked] = useState(false);
  const [operationId, setOperationId] = useState<string>("");
  const [operationDetail, setOperationDetail] = useState<RestoreOperationDetail | null>(null);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string>("");
  const [actionStatus, setActionStatus] = useState<string>("");
  const confirmHeadingRef = useRef<HTMLHeadingElement>(null);

  const loadStatus = useCallback(async (signal?: AbortSignal) => {
    try {
      const payload = await recoveryFetch<OperatorRecoveryStatusPayload>(
        "/api/hosted/recovery/status",
        { signal },
      );
      setLoadState({ status: "ready", payload });
      const items = payload.catalog.data?.items ?? [];
      setSelectedPointId((prev) => {
        if (prev && items.some((item) => item.resource_id === prev)) return prev;
        return payload.selected_point_id ?? items[0]?.resource_id ?? "";
      });
      const existingOp =
        payload.startup.pendingAcceptanceId ?? payload.startup.interruptedRestoreId ?? "";
      if (existingOp) {
        setOperationId((prev) => prev || existingOp);
      }
    } catch (error: unknown) {
      if (signal?.aborted) return;
      setLoadState({
        status: "unavailable",
        message:
          error instanceof Error
            ? error.message
            : "Backup and recovery details are currently unavailable.",
      });
    }
  }, []);

  useEffect(() => {
    if (!hosted) return;
    const controller = new AbortController();
    let active = true;
    void recoveryFetch<OperatorRecoveryStatusPayload>("/api/hosted/recovery/status", {
      signal: controller.signal,
    }).then(
      (payload) => {
        if (!active) return;
        setLoadState({ status: "ready", payload });
        const items = payload.catalog.data?.items ?? [];
        setSelectedPointId((prev) => {
          if (prev && items.some((item) => item.resource_id === prev)) return prev;
          return payload.selected_point_id ?? items[0]?.resource_id ?? "";
        });
        const existingOp =
          payload.startup.pendingAcceptanceId ?? payload.startup.interruptedRestoreId ?? "";
        if (existingOp) {
          setOperationId((prev) => prev || existingOp);
        }
      },
      (error: unknown) => {
        if (!active || controller.signal.aborted) return;
        setLoadState({
          status: "unavailable",
          message:
            error instanceof Error
              ? error.message
              : "Backup and recovery details are currently unavailable.",
        });
      },
    );
    return () => {
      active = false;
      controller.abort();
    };
  }, [hosted]);

  useEffect(() => {
    if (preview) {
      confirmHeadingRef.current?.focus();
    }
  }, [preview]);

  async function handlePreview() {
    if (!selectedPointId) return;
    setBusy(true);
    setActionError("");
    setActionStatus("");
    try {
      const result = await recoveryFetch<RestorePreviewPayload>("/api/hosted/recovery/preview", {
        method: "POST",
        body: { point_id: selectedPointId },
      });
      setPreview(result);
      setConfirmKey(createIdempotencyKey("restore"));
      setConfirmChecked(false);
      setActionStatus(
        "Restore preview prepared. Complete fresh verification and confirm below to proceed.",
      );
    } catch (error: unknown) {
      setActionError(error instanceof Error ? error.message : "Could not prepare restore preview.");
    } finally {
      setBusy(false);
    }
  }

  async function handleConfirmRestore(event: React.FormEvent) {
    event.preventDefault();
    if (!preview || !confirmChecked || !recentAuthGrant.trim()) return;
    setBusy(true);
    setActionError("");
    setActionStatus("");
    try {
      const outcome = await recoveryFetch<{
        operation?: { operation_id?: string };
        state?: string;
        error_code?: string | null;
      }>("/api/hosted/recovery/confirm", {
        method: "POST",
        body: {
          point_id: preview.pointId,
          preview_id: preview.previewId,
          idempotency_key: confirmKey,
          recent_auth_grant: recentAuthGrant.trim(),
        },
      });
      const opId = outcome.operation?.operation_id ?? "";
      if (opId) setOperationId(opId);
      setRecentAuthGrant("");
      setActionStatus(
        outcome.state === "succeeded"
          ? "Workspace restore switched. Sign in again if prompted, inspect your data, and accept the restore."
          : `Restore outcome is ${outcome.state ?? "unknown"}. Check restore status before retrying.`,
      );
      await loadStatus();
    } catch (error: unknown) {
      setActionError(
        error instanceof Error
          ? error.message
          : "Restore outcome could not be confirmed. Check restore status before retrying.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function handleCheckOperation(targetOpId: string) {
    if (!targetOpId) return;
    setBusy(true);
    setActionError("");
    try {
      const detail = await recoveryFetch<RestoreOperationDetail>(
        `/api/hosted/recovery/operations/${encodeURIComponent(targetOpId)}`,
      );
      setOperationDetail(detail);
      setActionStatus(`Restore operation ${detail.operationId} is in phase ${detail.phase}.`);
    } catch (error: unknown) {
      setActionError(
        error instanceof Error ? error.message : "Could not read restore operation status.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function handleAcceptRestore(targetOpId: string) {
    if (!targetOpId) return;
    setBusy(true);
    setActionError("");
    setActionStatus("");
    try {
      await recoveryFetch("/api/hosted/recovery/accept", {
        method: "POST",
        body: { operation_id: targetOpId },
      });
      setPreview(null);
      setOperationDetail(null);
      setActionStatus("Restored workspace accepted.");
      await loadStatus();
    } catch (error: unknown) {
      setActionError(
        error instanceof Error ? error.message : "Could not accept restored workspace.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function handleReconstructCatalog() {
    setBusy(true);
    setActionError("");
    setActionStatus("");
    try {
      const result = await recoveryFetch<{
        scannedManifests: number;
        importedPoints: number;
        skippedPoints: number;
      }>("/api/hosted/recovery/reconstruct", { method: "POST" });
      setActionStatus(
        `Catalog scan finished: ${result.importedPoints} verified point(s) imported from ${result.scannedManifests} manifest(s).`,
      );
      await loadStatus();
    } catch (error: unknown) {
      setActionError(
        error instanceof Error
          ? error.message
          : "Catalog reconstruction failed. Contact your workspace administrator.",
      );
    } finally {
      setBusy(false);
    }
  }

  if (!hosted) return null;

  const headingId = embedded ? "hosted-recovery-heading" : "minimal-recovery-heading";

  if (loadState.status === "loading") {
    return (
      <section aria-labelledby={headingId}>
        <h3 id={headingId}>Data and backup</h3>
        <p role="status">Loading backup and recovery status…</p>
      </section>
    );
  }

  if (loadState.status === "unavailable") {
    return (
      <section aria-labelledby={headingId}>
        <h3 id={headingId}>Data and backup</h3>
        <p role={embedded ? "status" : "alert"}>
          Backup and recovery details are currently unavailable.
        </p>
        {!embedded && (
          <p>
            If your workspace cannot open normally, verify your sign-in and contact your workspace
            administrator for assistance.
          </p>
        )}
        <button type="button" disabled={busy} onClick={() => void loadStatus()}>
          Refresh recovery status
        </button>
      </section>
    );
  }

  const { payload } = loadState;
  const isRecoveryMode = payload.mode === "recovery" || payload.startup.mode === "recovery";
  const protection = protectionPresentation(payload.protection.state);
  const points = payload.catalog.data?.items ?? [];

  return (
    <section aria-labelledby={headingId}>
      {isRecoveryMode ? (
        <div role="status" aria-live="polite">
          <h2 id={headingId}>Workspace recovery mode</h2>
          <p>
            <span aria-hidden="true">⚠ </span>
            <strong>Recovery mode active:</strong> Normal workspace editing is paused until a
            verified backup is restored. No empty workspace was created.
            {payload.startup.reason ? ` (${payload.startup.reason})` : ""}
          </p>
        </div>
      ) : (
        <h3 id={headingId}>Data and backup</h3>
      )}

      <dl>
        <dt>Protection status</dt>
        <dd>
          <p>
            <span aria-hidden="true">{protection.icon} </span>
            <strong>{protection.label}</strong>
          </p>
          {payload.protection.lastCapturedAt !== null && (
            <p className="ui-muted">
              Latest verified capture: {formatEpoch(payload.protection.lastCapturedAt)}
              {payload.protection.lastVerifiedAt !== null
                ? ` · Verified: ${formatEpoch(payload.protection.lastVerifiedAt)}`
                : ""}
            </p>
          )}
          {payload.protection.state === "unchanged" &&
            payload.protection.lastCheckedAt !== null && (
              <p className="ui-muted">
                Last checked: {formatEpoch(payload.protection.lastCheckedAt)} (workspace unchanged
                since verified point)
              </p>
            )}
          {payload.protection.state === "overdue" && (
            <p className="ui-muted">
              Backup verification is overdue
              {payload.protection.lastErrorCode ? ` (${payload.protection.lastErrorCode})` : ""}.
            </p>
          )}
        </dd>
      </dl>

      {actionStatus && <p role="status">{actionStatus}</p>}
      {actionError && <p role="alert">{actionError}</p>}

      {payload.startup.interruptedRestoreId && (
        <div role="status">
          <p>
            An interrupted restore operation (<code>{payload.startup.interruptedRestoreId}</code>)
            was detected. Check its status before starting a new restore.
          </p>
          <button
            type="button"
            disabled={busy}
            onClick={() => void handleCheckOperation(payload.startup.interruptedRestoreId ?? "")}
          >
            Check interrupted restore
          </button>
        </div>
      )}

      {payload.startup.pendingAcceptanceId && (
        <div role="status">
          <p>
            A restored workspace (<code>{payload.startup.pendingAcceptanceId}</code>) is awaiting
            your acceptance after inspection.
          </p>
          <button
            type="button"
            disabled={busy}
            onClick={() => void handleAcceptRestore(payload.startup.pendingAcceptanceId ?? "")}
          >
            Accept restored workspace
          </button>
        </div>
      )}

      {points.length === 0 ? (
        <div>
          <p>
            No verified recovery points are currently listed in this workspace catalog.
            {payload.availability_reason ? ` (${payload.availability_reason})` : ""}
          </p>
          <button type="button" disabled={busy} onClick={() => void handleReconstructCatalog()}>
            {busy ? "Scanning…" : "Reconstruct catalog from off-host backup"}
          </button>
        </div>
      ) : (
        <div>
          <fieldset>
            <legend>Verified recovery points</legend>
            <p className="ui-muted">
              Restoring replaces current workspace data with the selected verified point and signs
              out active sessions on all devices.
            </p>
            {points.map((point, index) => {
              const captured = pointCapturedAt(point);
              const verified = pointVerifiedAt(point);
              const compatible = pointSchemaCompatible(point);
              return (
                <label key={point.resource_id} style={{ display: "block", marginBottom: "0.5rem" }}>
                  <input
                    type="radio"
                    name="recoveryPoint"
                    value={point.resource_id}
                    checked={selectedPointId === point.resource_id}
                    disabled={!compatible || busy}
                    onChange={() => setSelectedPointId(point.resource_id)}
                  />{" "}
                  <strong>{index === 0 ? "Latest verified point" : "Verified point"}</strong> —{" "}
                  captured {formatEpoch(captured)}
                  {verified !== null ? ` · verified ${formatEpoch(verified)}` : ""}
                  {compatible ? " · compatible" : " · incompatible schema"}
                </label>
              );
            })}
          </fieldset>
          <button
            type="button"
            disabled={busy || !selectedPointId}
            onClick={() => void handlePreview()}
          >
            {busy ? "Preparing preview…" : "Preview restore"}
          </button>
        </div>
      )}

      {preview && (
        <form
          onSubmit={(event) => {
            void handleConfirmRestore(event);
          }}
          aria-labelledby="restore-confirm-heading"
        >
          <h4 id="restore-confirm-heading" tabIndex={-1} ref={confirmHeadingRef}>
            Confirm workspace restore
          </h4>
          <p>
            Point <code>{preview.pointId}</code> (captured {formatEpoch(preview.selectedCapturedAt)}
            ) will replace the current workspace. Preview expires at{" "}
            {formatEpoch(preview.expiresAt)}.
          </p>
          <p className="ui-muted">
            Step-up challenge: <code>{preview.stepUpChallengeId}</code> · Request hash:{" "}
            <code>{preview.exactRequestHash.slice(0, 16)}…</code>
          </p>
          <label htmlFor="recent-auth-grant">Fresh authentication verification token</label>
          <input
            id="recent-auth-grant"
            type="password"
            required
            autoComplete="off"
            value={recentAuthGrant}
            onChange={(event) => setRecentAuthGrant(event.target.value)}
          />
          <label style={{ display: "block", marginTop: "0.5rem" }}>
            <input
              type="checkbox"
              checked={confirmChecked}
              onChange={(event) => setConfirmChecked(event.target.checked)}
            />{" "}
            I understand that restoring rolls back changes made after{" "}
            {formatEpoch(preview.selectedCapturedAt)} and signs out active sessions.
          </label>
          <button
            type="submit"
            disabled={busy || !confirmChecked || recentAuthGrant.trim().length < 16}
          >
            {busy ? "Restoring…" : "Confirm restore"}
          </button>
        </form>
      )}

      {operationId && (
        <div>
          <p className="ui-muted">
            Tracked restore operation: <code>{operationId}</code>
          </p>
          <button
            type="button"
            disabled={busy}
            onClick={() => void handleCheckOperation(operationId)}
          >
            Check restore status
          </button>
          {operationDetail && (
            <div>
              <p>
                Phase: <strong>{operationDetail.phase}</strong> ({operationDetail.state})
                {operationDetail.errorCode ? ` — ${operationDetail.errorCode}` : ""}
              </p>
              {operationDetail.phase === "switched" && !operationDetail.acceptedAt && (
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => void handleAcceptRestore(operationDetail.operationId)}
                >
                  Accept restored workspace
                </button>
              )}
            </div>
          )}
        </div>
      )}

      <button type="button" disabled={busy} onClick={() => void loadStatus()}>
        Refresh recovery status
      </button>
    </section>
  );
}
