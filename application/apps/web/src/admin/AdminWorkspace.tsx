import { useCallback, useEffect, useRef, useState } from "react";
import { AdminRecovery } from "./AdminRecovery";
import {
  AdminApiError,
  adminFetch,
  formatMegabytes,
  formatProtectionLabel,
  formatTimestamp,
  type AdminBootstrapResponse,
  type AdminDetailResponse,
  type AdminListResponse,
  type AdminSession,
  type IssuedInvitationResponse,
  type OperationOutcome,
  type OperatorSummary,
} from "./admin-api";

type ViewState =
  | { kind: "list" }
  | { kind: "add" }
  | { kind: "detail"; operatorId: string }
  | { kind: "recovery" };

interface AddFormDraft {
  displayName: string;
  email: string;
  slug: string;
  supportContact: string;
  releaseId: string;
  initialData: "empty" | "synthetic";
  seedBundle: string;
}

function createKey(prefix: string): string {
  const random =
    typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
      ? crypto.randomUUID()
      : `${Date.now()}`;
  return `${prefix}-${random}`;
}

export function AdminWorkspace({ session }: { session: AdminSession }) {
  const [view, setView] = useState<ViewState>({ kind: "list" });
  const [bootstrap, setBootstrap] = useState<AdminBootstrapResponse | null>(null);
  const [bootstrapError, setBootstrapError] = useState("");
  const [listData, setListData] = useState<AdminListResponse | null>(null);
  const [listError, setListError] = useState("");
  const [loadingList, setLoadingList] = useState(false);
  const [search, setSearch] = useState("");
  const [setupFilter, setSetupFilter] = useState("all");
  const [accessFilter, setAccessFilter] = useState("all");
  const [cursor, setCursor] = useState<string | null>(null);

  const [draft, setDraft] = useState<AddFormDraft>({
    displayName: "",
    email: "",
    slug: "",
    supportContact: "",
    releaseId: "",
    initialData: "empty",
    seedBundle: "",
  });
  const [draftKey, setDraftKey] = useState(() => createKey("create-operator"));
  const [submittingAdd, setSubmittingAdd] = useState(false);
  const [addFeedback, setAddFeedback] = useState("");

  const [detail, setDetail] = useState<AdminDetailResponse | null>(null);
  const [detailError, setDetailError] = useState("");
  const [detailBusy, setDetailBusy] = useState(false);
  const [detailStatus, setDetailStatus] = useState("");
  const [issuedInvite, setIssuedInvite] = useState<IssuedInvitationResponse | null>(null);
  const [inviteDelivered, setInviteDelivered] = useState(false);
  const [repairConfirmChecked, setRepairConfirmChecked] = useState(false);
  const [repairKey, setRepairKey] = useState(() => createKey("repair-runtime"));
  const [repairOperation, setRepairOperation] = useState<OperationOutcome | null>(null);
  const sectionHeading = useRef<HTMLHeadingElement>(null);

  const loadBootstrap = useCallback(async () => {
    try {
      const data = await adminFetch<AdminBootstrapResponse>("/api/admin/bootstrap");
      setBootstrap(data);
      setBootstrapError("");
      setDraft((prev) => ({
        ...prev,
        releaseId: prev.releaseId || data.qualifiedOperatorReleases[0]?.release_id || "",
      }));
    } catch (error) {
      setBootstrapError(
        error instanceof Error ? error.message : "Deployment metadata is unavailable.",
      );
    }
  }, []);

  const loadList = useCallback(
    async (pageCursor: string | null) => {
      setLoadingList(true);
      setListError("");
      try {
        const params = new URLSearchParams({
          limit: "20",
          setup_state: setupFilter,
          access_state: accessFilter,
        });
        if (search.trim()) params.set("search", search.trim());
        if (pageCursor) params.set("cursor", pageCursor);
        const data = await adminFetch<AdminListResponse>(`/api/admin/operators?${params}`);
        setListData(data);
      } catch (error) {
        setListError(error instanceof Error ? error.message : "Operator directory is unavailable.");
      } finally {
        setLoadingList(false);
      }
    },
    [accessFilter, search, setupFilter],
  );

  const loadDetail = useCallback(async (operatorId: string) => {
    setDetailBusy(true);
    setDetailError("");
    try {
      const data = await adminFetch<AdminDetailResponse>(`/api/admin/operators/${operatorId}`);
      setDetail(data);
    } catch (error) {
      setDetailError(error instanceof Error ? error.message : "Operator details are unavailable.");
    } finally {
      setDetailBusy(false);
    }
  }, []);

  useEffect(() => {
    let active = true;
    void adminFetch<AdminBootstrapResponse>("/api/admin/bootstrap").then(
      (data) => {
        if (!active) return;
        setBootstrap(data);
        setBootstrapError("");
        setDraft((prev) => ({
          ...prev,
          releaseId: prev.releaseId || data.qualifiedOperatorReleases[0]?.release_id || "",
        }));
      },
      (error: unknown) => {
        if (!active) return;
        setBootstrapError(
          error instanceof Error ? error.message : "Deployment metadata is unavailable.",
        );
      },
    );
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    let active = true;
    if (view.kind === "list") {
      const params = new URLSearchParams({
        limit: "20",
        setup_state: setupFilter,
        access_state: accessFilter,
      });
      if (search.trim()) params.set("search", search.trim());
      if (cursor) params.set("cursor", cursor);
      void adminFetch<AdminListResponse>(`/api/admin/operators?${params}`).then(
        (data) => {
          if (!active) return;
          setListData(data);
          setListError("");
          setLoadingList(false);
        },
        (error: unknown) => {
          if (!active) return;
          setListError(
            error instanceof Error ? error.message : "Operator directory is unavailable.",
          );
          setLoadingList(false);
        },
      );
    } else if (view.kind === "detail") {
      void adminFetch<AdminDetailResponse>(`/api/admin/operators/${view.operatorId}`).then(
        (data) => {
          if (!active) return;
          setDetail(data);
          setDetailError("");
          setDetailBusy(false);
        },
        (error: unknown) => {
          if (!active) return;
          setDetailError(
            error instanceof Error ? error.message : "Operator details are unavailable.",
          );
          setDetailBusy(false);
        },
      );
    }
    return () => {
      active = false;
    };
  }, [view, cursor, search, setupFilter, accessFilter]);

  useEffect(() => {
    sectionHeading.current?.focus();
  }, [view]);

  async function submitAdd(event: React.FormEvent) {
    event.preventDefault();
    if (!bootstrap?.freePolicy || !bootstrap.admissionCommitment) {
      setAddFeedback("Pinned Free policy or host capacity profile is unavailable.");
      return;
    }
    setSubmittingAdd(true);
    setAddFeedback("");
    try {
      const outcome = await adminFetch<{ operation: { operation_id: string } }>(
        "/api/admin/operators",
        {
          method: "POST",
          csrf: session.csrfToken,
          body: {
            idempotencyKey: draftKey,
            expectedRevision: bootstrap.registryGeneration,
            displayName: draft.displayName.trim(),
            email: draft.email.trim(),
            slug: draft.slug.trim().toLowerCase(),
            supportContact: draft.supportContact.trim(),
            releaseId: draft.releaseId,
            policyId: bootstrap.freePolicy.policy_id,
            admissionCommitment: bootstrap.admissionCommitment,
            initialData: draft.initialData,
            seedBundle: draft.initialData === "synthetic" ? draft.seedBundle.trim() || null : null,
          },
        },
      );
      setAddFeedback(
        `Operator queued for manual provisioning (operation ${outcome.operation.operation_id}).`,
      );
      setDraft({
        displayName: "",
        email: "",
        slug: "",
        supportContact: draft.supportContact,
        releaseId: bootstrap.qualifiedOperatorReleases[0]?.release_id || "",
        initialData: "empty",
        seedBundle: "",
      });
      setDraftKey(createKey("create-operator"));
      await loadBootstrap();
      setCursor(null);
      setView({ kind: "list" });
    } catch (error) {
      if (error instanceof AdminApiError && error.status === 409) {
        void loadBootstrap();
      }
      if (error instanceof AdminApiError && error.limitingResources.length > 0) {
        setAddFeedback(
          `${error.message} Limiting resources: ${error.limitingResources.join(", ")}.`,
        );
      } else {
        setAddFeedback(
          error instanceof Error
            ? error.message
            : "Creation outcome is uncertain. Keep your input and check the directory before retrying.",
        );
      }
    } finally {
      setSubmittingAdd(false);
    }
  }

  async function handleRefreshSource() {
    if (!detail) return;
    setDetailBusy(true);
    setDetailStatus("");
    try {
      const outcome = await adminFetch<{ state: string; error_code?: string | null }>(
        `/api/admin/operators/${detail.operator.operator_id}/refresh`,
        {
          method: "POST",
          csrf: session.csrfToken,
          body: {
            idempotencyKey: createKey("refresh-source"),
            expectedRevision: detail.operatorRevision ?? detail.operator.operation?.revision ?? 1,
          },
        },
      );
      setDetailStatus(
        outcome.state === "succeeded"
          ? "Source observation refreshed."
          : `Source refresh needs attention (${outcome.error_code ?? "source_unreachable"}).`,
      );
      await loadDetail(detail.operator.operator_id);
    } catch (error) {
      setDetailStatus(error instanceof Error ? error.message : "Source refresh failed.");
    } finally {
      setDetailBusy(false);
    }
  }

  async function handleIssueInvitation() {
    if (!detail) return;
    setDetailBusy(true);
    setDetailStatus("");
    setInviteDelivered(false);
    try {
      const issued = await adminFetch<IssuedInvitationResponse>(
        `/api/admin/operators/${detail.operator.operator_id}/invitations`,
        {
          method: "POST",
          csrf: session.csrfToken,
          body: {
            idempotencyKey: createKey("issue-invitation"),
            expectedRevision: detail.operatorRevision ?? detail.operator.operation?.revision ?? 1,
          },
        },
      );
      setIssuedInvite(issued);
      setDetailStatus("Invitation issued. Share the one-time link and confirm delivery.");
      await loadDetail(detail.operator.operator_id);
    } catch (error) {
      setDetailStatus(error instanceof Error ? error.message : "Invitation could not be issued.");
    } finally {
      setDetailBusy(false);
    }
  }

  async function handleMarkDelivered() {
    if (!detail || !issuedInvite?.invitationId) return;
    setDetailBusy(true);
    try {
      await adminFetch(
        `/api/admin/operators/${detail.operator.operator_id}/invitations/${issuedInvite.invitationId}/delivered`,
        {
          method: "POST",
          csrf: session.csrfToken,
          body: { expectedRevision: 1 },
        },
      );
      setIssuedInvite(null);
      setInviteDelivered(true);
      setDetailStatus("Invitation marked delivered.");
    } catch (error) {
      setDetailStatus(
        error instanceof Error ? error.message : "Could not confirm invitation delivery.",
      );
    } finally {
      setDetailBusy(false);
    }
  }

  async function handleRepairRuntime() {
    if (!detail || !repairConfirmChecked) return;
    const op = detail.operator;
    if (!op.binding_id || typeof op.resource_generation !== "number") {
      setDetailStatus(
        "Runtime repair is unavailable because the operator binding metadata is missing.",
      );
      return;
    }
    setDetailBusy(true);
    setDetailStatus("");
    try {
      const outcome = await adminFetch<OperationOutcome>(
        `/api/admin/operators/${op.operator_id}/repair-runtime`,
        {
          method: "POST",
          csrf: session.csrfToken,
          body: {
            idempotencyKey: repairKey,
            expectedRevision: detail.operatorRevision ?? op.operation?.revision ?? 1,
            bindingId: op.binding_id,
            releaseId: op.release_id,
            expectedResourceGeneration: op.resource_generation,
          },
        },
      );
      setRepairOperation(outcome);
      setRepairConfirmChecked(false);
      setRepairKey(createKey("repair-runtime"));
      setDetailStatus(
        `Runtime repair operation ${outcome.operation.operation_id} recorded (${outcome.state}).`,
      );
      await loadDetail(op.operator_id);
    } catch (error) {
      setDetailStatus(
        error instanceof Error
          ? error.message
          : "Runtime repair outcome is uncertain. Check operation status before retrying.",
      );
    } finally {
      setDetailBusy(false);
    }
  }

  async function handleCheckOperationStatus(operationId: string) {
    setDetailBusy(true);
    setDetailStatus("");
    try {
      const outcome = await adminFetch<OperationOutcome>(`/api/admin/operations/${operationId}`);
      setRepairOperation(outcome);
      setDetailStatus(
        `Operation ${outcome.operation.operation_id} (${outcome.operation.kind}): ${outcome.state}${outcome.error_code ? ` (${outcome.error_code})` : ""}.`,
      );
    } catch (error) {
      setDetailStatus(error instanceof Error ? error.message : "Could not look up operation.");
    } finally {
      setDetailBusy(false);
    }
  }

  if (view.kind === "recovery") {
    return (
      <AdminRecovery
        session={session}
        onBack={() => {
          setView({ kind: "list" });
        }}
      />
    );
  }

  if (view.kind === "add") {
    return (
      <div className="admin-panel">
        <button
          type="button"
          className="link-button"
          onClick={() => {
            setView({ kind: "list" });
          }}
        >
          ← Back to operators
        </button>
        <h2 tabIndex={-1} ref={sectionHeading}>
          Add operator
        </h2>
        <div className="summary-strip" aria-label="Plan and capacity summary">
          <p>
            <strong>Plan:</strong> Free pilot (50.00 MB logical storage allowance)
          </p>
          <p>
            <strong>Host capacity:</strong>{" "}
            {bootstrap?.capacity.available
              ? `${bootstrap.capacity.profileRef} (snapshot r${bootstrap.capacity.snapshotRevision}, ${bootstrap.capacity.commitmentCount} commitments)`
              : "Capacity observation unavailable"}
          </p>
        </div>
        {bootstrapError && (
          <div className="action-row" role="alert">
            <span>{bootstrapError}</span>
            <button type="button" className="secondary" onClick={() => void loadBootstrap()}>
              Retry metadata
            </button>
          </div>
        )}
        {addFeedback && <p role="alert">{addFeedback}</p>}
        <form
          onSubmit={(event) => {
            void submitAdd(event);
          }}
        >
          <label htmlFor="op-name">Display name</label>
          <input
            id="op-name"
            type="text"
            required
            maxLength={120}
            value={draft.displayName}
            onChange={(event) => setDraft({ ...draft, displayName: event.target.value })}
          />
          <label htmlFor="op-email">Invited email</label>
          <input
            id="op-email"
            type="email"
            required
            maxLength={254}
            value={draft.email}
            onChange={(event) => setDraft({ ...draft, email: event.target.value })}
          />
          <label htmlFor="op-slug">Workspace slug</label>
          <input
            id="op-slug"
            type="text"
            required
            maxLength={63}
            pattern="[a-z0-9](?:[a-z0-9-]*[a-z0-9])?"
            value={draft.slug}
            onChange={(event) => setDraft({ ...draft, slug: event.target.value })}
          />
          <label htmlFor="op-support">Support contact</label>
          <input
            id="op-support"
            type="email"
            required
            maxLength={254}
            value={draft.supportContact}
            onChange={(event) => setDraft({ ...draft, supportContact: event.target.value })}
          />
          <label htmlFor="op-release">Qualified Operator release</label>
          <select
            id="op-release"
            required
            value={draft.releaseId}
            onChange={(event) => setDraft({ ...draft, releaseId: event.target.value })}
          >
            {(bootstrap?.qualifiedOperatorReleases ?? []).map((rel) => (
              <option key={rel.release_id} value={rel.release_id}>
                {rel.artifact_ref} ({rel.release_id.slice(0, 8)})
              </option>
            ))}
          </select>
          <fieldset className="radio-group">
            <legend>Initial workspace data</legend>
            <label>
              <input
                type="radio"
                name="initialData"
                value="empty"
                checked={draft.initialData === "empty"}
                onChange={() => setDraft({ ...draft, initialData: "empty", seedBundle: "" })}
              />{" "}
              Empty workspace (default)
            </label>
            <label>
              <input
                type="radio"
                name="initialData"
                value="synthetic"
                checked={draft.initialData === "synthetic"}
                onChange={() => setDraft({ ...draft, initialData: "synthetic" })}
              />{" "}
              Synthetic sample portfolio
            </label>
          </fieldset>
          {draft.initialData === "synthetic" && (
            <>
              <label htmlFor="op-seed">Pinned seed bundle reference</label>
              <input
                id="op-seed"
                type="text"
                required
                placeholder="synthetic-demo-v1:<sha256>"
                value={draft.seedBundle}
                onChange={(event) => setDraft({ ...draft, seedBundle: event.target.value })}
              />
            </>
          )}
          <div className="action-row">
            <button type="submit" disabled={submittingAdd || !session.csrfToken}>
              {submittingAdd ? "Creating operator…" : "Create operator"}
            </button>
          </div>
        </form>
      </div>
    );
  }

  if (view.kind === "detail") {
    const op = detail?.operator;
    const inviteAction = detail?.actions.find((a) => a.action === "admin_reissue_invitation");
    const claimUrl =
      op && issuedInvite?.invitationId && issuedInvite.token && bootstrap
        ? `https://${op.slug}.${bootstrap.publicBaseDomain}/auth/start#invitation=${encodeURIComponent(issuedInvite.invitationId)}&token=${encodeURIComponent(issuedInvite.token)}`
        : null;
    return (
      <div className="admin-panel">
        <button
          type="button"
          className="link-button"
          onClick={() => {
            setIssuedInvite(null);
            setInviteDelivered(false);
            setDetailStatus("");
            setView({ kind: "list" });
          }}
        >
          ← Back to operators
        </button>
        <h2 tabIndex={-1} ref={sectionHeading}>
          {op ? op.display_name : "Operator details"}
        </h2>
        {detailError && <p role="alert">{detailError}</p>}
        {detailStatus && <p role="status">{detailStatus}</p>}
        {op && detail && (
          <div className="detail-grid">
            <article className="card">
              <h3>Assignment & access</h3>
              <p>
                <strong>Slug:</strong> {op.slug}
              </p>
              <p>
                <strong>Setup state:</strong> {op.setup_state}
              </p>
              <p>
                <strong>Desired access:</strong> {op.desired_enabled ? "Enabled" : "Disabled"}
              </p>
              <p>
                <strong>Cached source access:</strong>{" "}
                {op.access.data
                  ? `${op.access.data.effective_enabled ? "Enabled" : "Disabled"} (${formatTimestamp(op.access.freshness?.as_of)})`
                  : "Unavailable"}
              </p>
              <p>
                <strong>Release:</strong> <code>{op.release_id}</code>
              </p>
            </article>

            <article className="card">
              <h3>Readiness checks ({detail.readiness.data?.state ?? "unavailable"})</h3>
              <ul className="gate-list">
                {(detail.readiness.data?.checks ?? []).map((gate) => (
                  <li key={gate.name}>
                    <strong>{gate.name}:</strong> {gate.state}
                  </li>
                ))}
              </ul>
            </article>

            <article className="card">
              <h3>Free pilot usage</h3>
              <p>
                <strong>Usage:</strong>{" "}
                {op.usage.data
                  ? `${formatMegabytes(op.usage.data.used_bytes)} / ${formatMegabytes(op.usage.data.usable_bytes)} (${formatTimestamp(op.usage.freshness?.as_of)})`
                  : "Unavailable"}
              </p>
              <p>
                <strong>Backup protection:</strong>{" "}
                {(() => {
                  const prot = formatProtectionLabel(op.protection);
                  return (
                    <>
                      <span aria-hidden="true">{prot.icon} </span>
                      {prot.label}
                      {prot.detail ? ` (${prot.detail})` : ""}
                    </>
                  );
                })()}
              </p>
              <button
                type="button"
                disabled={detailBusy || !session.csrfToken}
                onClick={() => {
                  void handleRefreshSource();
                }}
              >
                Refresh source
              </button>
            </article>

            <article className="card">
              <h3>Runtime repair</h3>
              <p className="muted">
                Replaces only the Operator container from a qualified image while retaining IDs,
                workspace files, access/recovery stores, and encryption key references. Does not
                create an empty database or restore customer data.
              </p>
              <label>
                <input
                  type="checkbox"
                  checked={repairConfirmChecked}
                  onChange={(event) => setRepairConfirmChecked(event.target.checked)}
                />{" "}
                I understand this stops and replaces the Operator runtime container only.
              </label>
              <div className="action-row">
                <button
                  type="button"
                  disabled={
                    detailBusy ||
                    !repairConfirmChecked ||
                    !session.csrfToken ||
                    !op.binding_id ||
                    typeof op.resource_generation !== "number"
                  }
                  onClick={() => {
                    void handleRepairRuntime();
                  }}
                >
                  Repair runtime
                </button>
                {(repairOperation?.operation.operation_id ??
                  op.operation?.operation.operation_id) && (
                  <button
                    type="button"
                    className="secondary"
                    disabled={detailBusy}
                    onClick={() => {
                      const targetId =
                        repairOperation?.operation.operation_id ??
                        op.operation?.operation.operation_id;
                      if (targetId) void handleCheckOperationStatus(targetId);
                    }}
                  >
                    Check operation status
                  </button>
                )}
              </div>
              {repairOperation && (
                <p>
                  <strong>Tracked operation:</strong> {repairOperation.operation.kind} —{" "}
                  {repairOperation.state} (<code>{repairOperation.operation.operation_id}</code>)
                </p>
              )}
            </article>

            <article className="card">
              <h3>Manual provisioning & invitations</h3>
              {op.operation ? (
                <p>
                  <strong>Latest operation:</strong> {op.operation.operation.kind} —{" "}
                  {op.operation.state} (<code>{op.operation.operation.operation_id}</code>)
                </p>
              ) : (
                <p>No operations recorded.</p>
              )}
              <button
                type="button"
                disabled={detailBusy || !inviteAction?.enabled || !session.csrfToken}
                onClick={() => {
                  void handleIssueInvitation();
                }}
              >
                Issue / reissue invitation
              </button>
              {!inviteAction?.enabled && (
                <p className="muted">
                  Invitation issuance is available once provisioning completes (ready_for_claim).
                </p>
              )}
              {claimUrl && (
                <div className="invite-box">
                  <p>
                    <strong>One-time claim link:</strong>
                  </p>
                  <code>{claimUrl}</code>
                  <button
                    type="button"
                    disabled={detailBusy}
                    onClick={() => {
                      void handleMarkDelivered();
                    }}
                  >
                    Mark delivered
                  </button>
                </div>
              )}
              {inviteDelivered && <p>Delivery confirmed.</p>}
            </article>
          </div>
        )}
      </div>
    );
  }

  const items: OperatorSummary[] = listData?.directory.data?.items ?? [];
  const total = listData?.directory.data?.matching_total;
  return (
    <div className="admin-panel">
      <div className="toolbar">
        <h2 tabIndex={-1} ref={sectionHeading}>
          Operators{typeof total === "number" ? ` (${total})` : ""}
        </h2>
        <div className="action-row">
          <button
            type="button"
            onClick={() => {
              setAddFeedback("");
              void loadBootstrap();
              setView({ kind: "add" });
            }}
          >
            Add operator
          </button>
          <button
            type="button"
            className="secondary"
            onClick={() => {
              setView({ kind: "recovery" });
            }}
          >
            Control recovery
          </button>
          <button
            type="button"
            className="secondary"
            disabled={loadingList}
            onClick={() => {
              void loadBootstrap();
              void loadList(cursor);
            }}
          >
            Refresh list
          </button>
        </div>
      </div>

      {bootstrapError && (
        <div className="action-row" role="status">
          <span>{bootstrapError}</span>
          <button type="button" className="secondary" onClick={() => void loadBootstrap()}>
            Retry metadata
          </button>
        </div>
      )}
      {listError && <p role="alert">{listError}</p>}

      <div className="filters" role="search" aria-label="Filter operators">
        <label htmlFor="filter-search">Search</label>
        <input
          id="filter-search"
          type="search"
          placeholder="Name, slug, or email"
          value={search}
          onChange={(event) => {
            setCursor(null);
            setSearch(event.target.value);
          }}
        />
        <label htmlFor="filter-setup">Setup state</label>
        <select
          id="filter-setup"
          value={setupFilter}
          onChange={(event) => {
            setCursor(null);
            setSetupFilter(event.target.value);
          }}
        >
          <option value="all">All setup states</option>
          <option value="pending">Pending</option>
          <option value="preparing">Preparing</option>
          <option value="ready_for_claim">Ready for claim</option>
          <option value="active">Active</option>
          <option value="needs_attention">Needs attention</option>
          <option value="retired">Retired</option>
        </select>
        <label htmlFor="filter-access">Source access</label>
        <select
          id="filter-access"
          value={accessFilter}
          onChange={(event) => {
            setCursor(null);
            setAccessFilter(event.target.value);
          }}
        >
          <option value="all">All access states</option>
          <option value="enabled">Enabled</option>
          <option value="disabled">Disabled</option>
          <option value="unknown">Unknown / unavailable</option>
        </select>
      </div>

      {loadingList ? (
        <p role="status">Loading operators…</p>
      ) : items.length === 0 ? (
        <p>No operators match the current filters.</p>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Operator</th>
                <th>Setup</th>
                <th>Source access</th>
                <th>Free usage</th>
                <th>Protection</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr key={item.operator_id}>
                  <td>
                    <strong>{item.display_name}</strong>
                    <div className="muted">{item.slug}</div>
                  </td>
                  <td>{item.setup_state}</td>
                  <td>
                    {item.access.data
                      ? item.access.data.effective_enabled
                        ? "Enabled"
                        : "Disabled"
                      : "Unavailable"}
                  </td>
                  <td>
                    {item.usage.data
                      ? `${formatMegabytes(item.usage.data.used_bytes)} / 50.00 MB`
                      : "Unavailable"}
                  </td>
                  <td>
                    {(() => {
                      const prot = formatProtectionLabel(item.protection);
                      return (
                        <>
                          <span aria-hidden="true">{prot.icon} </span>
                          {prot.label}
                          {prot.detail && <div className="muted">{prot.detail}</div>}
                        </>
                      );
                    })()}
                  </td>
                  <td>
                    <button
                      type="button"
                      className="secondary"
                      onClick={() => {
                        setDetail(null);
                        setDetailError("");
                        setDetailBusy(true);
                        setIssuedInvite(null);
                        setInviteDelivered(false);
                        setDetailStatus("");
                        setRepairOperation(null);
                        setRepairConfirmChecked(false);
                        setRepairKey(createKey("repair-runtime"));
                        setView({ kind: "detail", operatorId: item.operator_id });
                      }}
                    >
                      Inspect
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {listData?.nextCursor && (
        <div className="action-row">
          <button
            type="button"
            className="secondary"
            onClick={() => {
              setCursor(listData.nextCursor ?? null);
            }}
          >
            Next page
          </button>
        </div>
      )}
    </div>
  );
}
