import { useCallback, useEffect, useRef, useState } from "react";
import {
  adminFetch,
  formatTimestamp,
  type AdminControlPoint,
  type AdminControlPreview,
  type AdminControlRecoveryStatus,
  type AdminSession,
  type OperationOutcome,
} from "./admin-api";

function createKey(prefix: string): string {
  const random =
    typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
      ? crypto.randomUUID()
      : `${Date.now()}`;
  return `${prefix}-${random}`;
}

function pointCapturedAt(point: AdminControlPoint): number | null {
  return point.captured_at ?? point.summary?.captured_at ?? null;
}

function pointVerifiedAt(point: AdminControlPoint): number | null {
  return point.verified_at ?? point.summary?.verified_at ?? null;
}

export function AdminRecovery({ session, onBack }: { session: AdminSession; onBack?: () => void }) {
  const [statusData, setStatusData] = useState<AdminControlRecoveryStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [selectedPointId, setSelectedPointId] = useState("");
  const [preview, setPreview] = useState<AdminControlPreview | null>(null);
  const [confirmKey, setConfirmKey] = useState(() => createKey("control-restore"));
  const [confirmChecked, setConfirmChecked] = useState(false);
  const [mfaConfirmed, setMfaConfirmed] = useState(false);
  const [lastOperationId, setLastOperationId] = useState("");
  const [busy, setBusy] = useState(false);
  const [feedback, setFeedback] = useState("");
  const headingRef = useRef<HTMLHeadingElement>(null);
  const confirmHeadingRef = useRef<HTMLHeadingElement>(null);

  const loadStatus = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const data = await adminFetch<AdminControlRecoveryStatus>("/api/admin/recovery/status");
      setStatusData(data);
      const items = data.catalog.items ?? [];
      setSelectedPointId((prev) => {
        if (prev && items.some((item) => item.resource_id === prev)) return prev;
        return items[0]?.resource_id ?? "";
      });
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Admin control-plane recovery status is unavailable.",
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let active = true;
    headingRef.current?.focus();
    void adminFetch<AdminControlRecoveryStatus>("/api/admin/recovery/status").then(
      (data) => {
        if (!active) return;
        setStatusData(data);
        setError("");
        const items = data.catalog.items ?? [];
        setSelectedPointId((prev) => {
          if (prev && items.some((item) => item.resource_id === prev)) return prev;
          return items[0]?.resource_id ?? "";
        });
        setLoading(false);
      },
      (err: unknown) => {
        if (!active) return;
        setError(
          err instanceof Error
            ? err.message
            : "Admin control-plane recovery status is unavailable.",
        );
        setLoading(false);
      },
    );
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (preview) {
      confirmHeadingRef.current?.focus();
    }
  }, [preview]);

  async function handlePreview() {
    if (!selectedPointId) return;
    setBusy(true);
    setError("");
    setFeedback("");
    try {
      const result = await adminFetch<AdminControlPreview>("/api/admin/recovery/preview", {
        method: "POST",
        csrf: session.csrfToken,
        body: { point_id: selectedPointId },
      });
      setPreview(result);
      setConfirmKey(createKey("control-restore"));
      setConfirmChecked(false);
      setMfaConfirmed(false);
      setFeedback(
        "Control-plane restore preview prepared. Confirm bootstrap MFA step-up below to restore.",
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not preview control-plane restore.");
    } finally {
      setBusy(false);
    }
  }

  async function handleConfirm(event: React.FormEvent) {
    event.preventDefault();
    if (!preview || !confirmChecked || !mfaConfirmed) return;
    setBusy(true);
    setError("");
    setFeedback("");
    try {
      const outcome = await adminFetch<OperationOutcome>("/api/admin/recovery/confirm", {
        method: "POST",
        csrf: session.csrfToken,
        body: {
          point_id: preview.pointId,
          preview_id: preview.previewId,
          idempotency_key: confirmKey,
          confirmed_request_hash: preview.exactRequestHash,
        },
      });
      setLastOperationId(outcome.operation.operation_id);
      setFeedback(
        outcome.state === "succeeded"
          ? `Control-plane restore switched (operation ${outcome.operation.operation_id}). Verify control state and accept.`
          : `Control-plane restore finished with state ${outcome.state}.`,
      );
      await loadStatus();
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Control-plane restore could not be confirmed.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function handleAccept() {
    if (!lastOperationId) return;
    setBusy(true);
    setError("");
    try {
      await adminFetch("/api/admin/recovery/accept", {
        method: "POST",
        csrf: session.csrfToken,
        body: { operation_id: lastOperationId },
      });
      setPreview(null);
      setFeedback("Control-plane restore accepted.");
      await loadStatus();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not accept control-plane restore.");
    } finally {
      setBusy(false);
    }
  }

  async function handleReconstruct() {
    setBusy(true);
    setError("");
    setFeedback("");
    try {
      const result = await adminFetch<{
        scannedManifests: number;
        importedPoints: number;
        skippedPoints: number;
      }>("/api/admin/recovery/reconstruct", {
        method: "POST",
        csrf: session.csrfToken,
      });
      setFeedback(
        `Control catalog reconstructed: ${result.importedPoints} point(s) imported from ${result.scannedManifests} manifest(s).`,
      );
      await loadStatus();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Control catalog reconstruction failed.");
    } finally {
      setBusy(false);
    }
  }

  const points = statusData?.catalog.items ?? [];

  return (
    <div className="admin-panel">
      {onBack && (
        <button type="button" className="link-button" onClick={onBack}>
          ← Back to operators
        </button>
      )}
      <h2 tabIndex={-1} ref={headingRef}>
        Admin control-plane recovery
      </h2>
      <p className="muted">
        Operates independently of the main Admin database using protected bootstrap authority and
        verified off-host control-plane backups. Customer workspace data is never accessed here.
      </p>

      {error && <p role="alert">{error}</p>}
      {feedback && <p role="status">{feedback}</p>}

      {loading ? (
        <p role="status">Loading control-plane recovery status…</p>
      ) : statusData ? (
        <div className="detail-grid">
          <article className="card">
            <h3>Control-plane mode</h3>
            <p>
              <strong>Mode:</strong>{" "}
              {statusData.mode === "recovery" ? (
                <span>
                  <span aria-hidden="true">⚠ </span>Admin recovery mode
                </span>
              ) : (
                <span>
                  <span aria-hidden="true">✓ </span>Normal
                </span>
              )}
            </p>
            {statusData.reason && (
              <p>
                <strong>Reason:</strong> {statusData.reason}
              </p>
            )}
            <p>
              <strong>Active admin database ref:</strong>{" "}
              <code>{statusData.activeAdminResourceRef ?? "Unavailable"}</code>
            </p>
            <div className="action-row">
              <button
                type="button"
                className="secondary"
                disabled={busy}
                onClick={() => void loadStatus()}
              >
                Refresh status
              </button>
              <button
                type="button"
                className="secondary"
                disabled={busy || !session.csrfToken}
                onClick={() => void handleReconstruct()}
              >
                Reconstruct catalog
              </button>
            </div>
          </article>

          <article className="card">
            <h3>Verified control recovery points</h3>
            {points.length === 0 ? (
              <p>No verified control recovery points are listed. Reconstruct catalog to scan.</p>
            ) : (
              <>
                <fieldset className="radio-group">
                  <legend>Select control recovery point</legend>
                  {points.map((point, index) => (
                    <label key={point.resource_id}>
                      <input
                        type="radio"
                        name="controlRecoveryPoint"
                        value={point.resource_id}
                        checked={selectedPointId === point.resource_id}
                        onChange={() => setSelectedPointId(point.resource_id)}
                      />{" "}
                      <strong>{index === 0 ? "Latest verified point" : "Verified point"}</strong> —{" "}
                      captured {formatTimestamp(pointCapturedAt(point))} · verified{" "}
                      {formatTimestamp(pointVerifiedAt(point))}
                    </label>
                  ))}
                </fieldset>
                <button
                  type="button"
                  disabled={busy || !selectedPointId || !session.csrfToken}
                  onClick={() => void handlePreview()}
                >
                  Preview control restore
                </button>
              </>
            )}
          </article>

          {preview && (
            <article className="card">
              <h3 tabIndex={-1} ref={confirmHeadingRef}>
                Confirm control-plane restore
              </h3>
              <p>
                Point <code>{preview.pointId}</code> (captured{" "}
                {formatTimestamp(preview.selectedCapturedAt)}) · Hash:{" "}
                <code>{preview.exactRequestHash.slice(0, 16)}…</code>
              </p>
              <form
                onSubmit={(event) => {
                  void handleConfirm(event);
                }}
              >
                <label>
                  <input
                    type="checkbox"
                    checked={mfaConfirmed}
                    onChange={(event) => setMfaConfirmed(event.target.checked)}
                  />{" "}
                  Bootstrap Google + TOTP MFA step-up verified for this restore
                </label>
                <label>
                  <input
                    type="checkbox"
                    checked={confirmChecked}
                    onChange={(event) => setConfirmChecked(event.target.checked)}
                  />{" "}
                  I understand this restores the Admin control-plane database into a staged path and
                  switches atomically.
                </label>
                <div className="action-row">
                  <button
                    type="submit"
                    disabled={busy || !confirmChecked || !mfaConfirmed || !session.csrfToken}
                  >
                    {busy ? "Restoring…" : "Confirm control restore"}
                  </button>
                </div>
              </form>
            </article>
          )}

          {lastOperationId && (
            <article className="card">
              <h3>Accept restored control plane</h3>
              <p>
                Operation: <code>{lastOperationId}</code>
              </p>
              <button
                type="button"
                disabled={busy || !session.csrfToken}
                onClick={() => void handleAccept()}
              >
                Accept control restore
              </button>
            </article>
          )}
        </div>
      ) : null}
    </div>
  );
}
