import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useParams } from "react-router-dom";
import { ParentBackLink, SourceWorkflowLink as Link } from "../shared/home-navigation";
import { api } from "@epm/contracts";
import type { components } from "@epm/contracts/generated";
import { useWorkspace } from "../app/workspace-gate";
import { canonicalRequest, MutationFailure, mutation } from "../shared/mutations";
import { useAiRecovery } from "./ai-recovery";
import { readResult } from "./reads";
import { SavedItem } from "./saved-item";

type Schema = components["schemas"];
type Settings = Schema["SettingsResponse"];
type Connection = Schema["ModelConnectionResponse"];
type External = Schema["ExternalEffectResponse"];

function json(value: unknown) {
  return JSON.stringify(value, null, 2);
}

function formText(data: FormData, key: string) {
  const value = data.get(key);
  return typeof value === "string" ? value.trim() : "";
}

function ApiError({ error }: { error: Error }) {
  return <p role="alert">{error.message || "AI governance data is unavailable."}</p>;
}

export function AiGovernanceSettings() {
  const { scope } = useWorkspace();
  const cache = useQueryClient();
  const recovery = useAiRecovery();
  const writable = scope.canWrite && !recovery.blocked;
  const settings = useQuery({
    queryKey: scope.key("ai-settings"),
    queryFn: async ({ signal }) => readResult(await api.GET("/api/ai/settings", { signal })),
  });
  const connections = useQuery({
    queryKey: scope.key("ai-connections"),
    queryFn: async ({ signal }) => readResult(await api.GET("/api/ai/connections", { signal })),
  });
  const limits = useQuery({
    queryKey: scope.key("ai-limits"),
    queryFn: async ({ signal }) => readResult(await api.GET("/api/ai/limits", { signal })),
  });
  const profiles = useQuery({
    queryKey: scope.key("ai-redaction-profiles"),
    queryFn: async ({ signal }) =>
      readResult(await api.GET("/api/ai/redaction-profiles", { signal })),
  });
  const [draftStatus, setDraftStatus] = useState<Schema["DraftSummaryResponse"]["status"] | "all">(
    "proposed",
  );
  const [draftCursor, setDraftCursor] = useState<string | undefined>();
  const drafts = useQuery({
    queryKey: scope.key("ai-drafts", draftStatus, draftCursor),
    queryFn: async ({ signal }) =>
      readResult(
        await api.GET("/api/ai/drafts", {
          signal,
          params: {
            query: {
              pageSize: 100,
              status: draftStatus === "all" ? undefined : draftStatus,
              cursor: draftCursor,
            },
          },
        }),
      ),
  });
  const [modeChoice, setModeChoice] = useState<"off" | "on_device" | "cloud" | null>(null);
  const [connectionId, setConnectionId] = useState("");
  const [message, setMessage] = useState("");
  const pendingKey =
    recovery.current?.formKey.includes("credential") ||
    recovery.current?.formKey === "ai.connection.probe"
      ? ""
      : (recovery.current?.attemptKey ?? "");
  const [pendingExternal, setPendingExternal] = useState<External | null>(null);
  const externalKey =
    recovery.current?.formKey.includes("credential") ||
    recovery.current?.formKey === "ai.connection.probe"
      ? (recovery.current.attemptKey ?? "")
      : "";
  const [working, setBusy] = useState(false);
  const [savedConnection, setSavedConnection] = useState<unknown>();
  const busy = working;
  const [adapterId, setAdapterId] = useState("");
  const [modelIdentifier, setModelIdentifier] = useState("");
  const [disclosureAccepted, setDisclosureAccepted] = useState(false);
  const [probeResults, setProbeResults] = useState<
    Record<string, { revision: number; ready: boolean }>
  >({});

  if (settings.isPending || connections.isPending || limits.isPending || profiles.isPending)
    return <p role="status">Loading AI assistance settings…</p>;
  const readError = settings.error ?? connections.error ?? limits.error ?? profiles.error;
  if (readError) return <ApiError error={readError} />;
  if (!settings.data || !connections.data || !limits.data || !profiles.data)
    return <p role="alert">AI assistance settings are unavailable.</p>;

  const state: Settings = settings.data;
  const connectionRows = connections.data;
  const limitRows = limits.data;
  const profileRows = profiles.data;
  const available = state.registeredAdapters;
  const activeMode = !state.builtInEnabled
    ? "off"
    : (connections.data.find((item) => item.id === state.defaultConnectionId)?.executionLocation ??
      "off");
  const mode = modeChoice ?? activeMode;
  const modeConnections = connectionRows.filter((item) => item.executionLocation === mode);
  const selectedAdapter = available.find(
    (item) => `${item.adapterId}@${item.adapterVersion}` === adapterId,
  );
  const actions = state.actions;

  async function command<T>(
    key: string,
    call: () => Promise<T>,
    success: string,
    intent: Parameters<typeof recovery.prepare>,
  ) {
    if (!writable || busy || (pendingKey && key !== pendingKey)) return;
    scope.requireWrite();
    setBusy(true);
    setMessage("");
    try {
      await recovery.prepare(...intent);
      const result = await call();
      scope.requireWrite();
      await recovery.reconcile();
      if (intent[0] === "ai.connection.create") setSavedConnection(result);
      setMessage(success);
      await Promise.all([
        cache.invalidateQueries({ queryKey: scope.key("ai-settings") }),
        cache.invalidateQueries({ queryKey: scope.key("ai-connections") }),
        cache.invalidateQueries({ queryKey: scope.key("ai-limits") }),
      ]);
    } catch (error) {
      setMessage(
        error instanceof Error
          ? `${error.message} ${key ? "Check the original command receipt before starting another change." : ""}`
          : "Command outcome is unknown. Check its receipt before continuing.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function reconcileCommand() {
    if (!pendingKey) return;
    const response = await api.GET("/api/ai/command-operations/by-key/{key}", {
      params: { path: { key: pendingKey } },
    });
    if (!response.data) {
      setMessage(
        "No receipt is available yet. Keep this key and check again before a new command.",
      );
      return;
    }
    setMessage("The original command receipt was found. Settings are being refreshed.");
    await recovery.reconcile();
    if (response.data.action === "connection_create") setSavedConnection(response.data.result);
    await Promise.all([
      cache.invalidateQueries({ queryKey: scope.key("ai-settings") }),
      cache.invalidateQueries({ queryKey: scope.key("ai-connections") }),
      cache.invalidateQueries({ queryKey: scope.key("ai-limits") }),
    ]);
  }

  async function updateMode() {
    const key = pendingKey || crypto.randomUUID();
    const chosen =
      mode === "off"
        ? null
        : connectionId || (mode === activeMode ? (state.defaultConnectionId ?? "") : "");
    if (mode !== "off" && !chosen) {
      setMessage("Choose a configured connection for this destination first.");
      return;
    }
    const target = connectionRows.find((item) => item.id === chosen);
    if (mode === "cloud" && target && !target.disclosureAcceptedAt) {
      setMessage("Review and save the cloud data disclosure before enabling this destination.");
      return;
    }
    await command(
      key,
      () =>
        mutation(() =>
          api.PUT("/api/ai/settings", {
            body: {
              expectedRevision: state.revision,
              idempotencyKey: key,
              builtInEnabled: mode !== "off",
              defaultConnectionId: chosen,
            },
          }),
        ),
      "AI destination settings saved.",
      [
        "ai.settings.update",
        "1",
        {
          expectedRevision: state.revision,
          builtInEnabled: mode !== "off",
          defaultConnectionId: chosen,
        },
        key,
      ],
    );
  }

  async function createConnection(form: HTMLFormElement) {
    if (!selectedAdapter) return;
    const data = new FormData(form);
    const location = selectedAdapter.executionLocation;
    const key = crypto.randomUUID();
    await command(
      key,
      () =>
        mutation(() =>
          api.POST("/api/ai/connections", {
            body: {
              expectedRevision: 0,
              idempotencyKey: key,
              label: formText(data, "label"),
              adapterId: selectedAdapter.adapterId,
              adapterVersion: selectedAdapter.adapterVersion,
              modelIdentifier,
              executionLocation: location,
              enabled: true,
              ...(location === "on_device"
                ? {
                    modelArtifactDigest: formText(data, "modelArtifactDigest"),
                    quantization: formText(data, "quantization"),
                    runtimeId: formText(data, "runtimeId"),
                    runtimeVersion: formText(data, "runtimeVersion"),
                  }
                : {}),
            },
          }),
        ),
      "Connection saved. Add cloud disclosure and credentials separately before testing it.",
      [
        "ai.connection.create",
        null,
        {
          expectedRevision: 0,
          label: formText(data, "label"),
          adapterId: selectedAdapter.adapterId,
          adapterVersion: selectedAdapter.adapterVersion,
          modelIdentifier,
          executionLocation: location,
          enabled: true,
          ...(location === "on_device"
            ? {
                modelArtifactDigest: formText(data, "modelArtifactDigest"),
                quantization: formText(data, "quantization"),
                runtimeId: formText(data, "runtimeId"),
                runtimeVersion: formText(data, "runtimeVersion"),
              }
            : {}),
        },
        key,
      ],
    );
  }

  async function externalEffect(
    connection: Connection,
    effect: "credential_set" | "credential_delete" | "connection_probe",
    credential?: string,
  ) {
    if (!writable || busy) return;
    const key = crypto.randomUUID();
    setBusy(true);
    setMessage("The external action may take time. It will not be repeated automatically.");
    try {
      await recovery.prepare(
        effect === "credential_set"
          ? "ai.connection.credential.set"
          : effect === "credential_delete"
            ? "ai.connection.credential.delete"
            : "ai.connection.probe",
        connection.id,
        { expectedRevision: connection.revision },
        key,
      );
      const call = () => {
        const body = { expectedRevision: connection.revision, idempotencyKey: key };
        if (effect === "credential_set")
          return api.PUT("/api/ai/connections/{connection_id}/credential", {
            params: { path: { connection_id: connection.id } },
            body: { ...body, credential: credential ?? "" },
          });
        if (effect === "credential_delete")
          return api.DELETE("/api/ai/connections/{connection_id}/credential", {
            params: { path: { connection_id: connection.id } },
            body,
          });
        return api.POST("/api/ai/connections/{connection_id}/test", {
          params: { path: { connection_id: connection.id } },
          body,
        });
      };
      const result = await mutation(call);
      setPendingExternal(result.status === "outcome_unknown" ? result : null);
      if (result.status !== "outcome_unknown") await recovery.reconcile();
      const probeResult = result.result;
      if (
        effect === "connection_probe" &&
        result.status === "completed" &&
        probeResult?.status === "completed" &&
        "ready" in probeResult
      ) {
        const ready = probeResult.ready;
        const revision = result.revision;
        setProbeResults((current) => ({
          ...current,
          [connection.id]: { revision, ready },
        }));
      }
      setMessage(
        result.status === "completed"
          ? effect === "connection_probe"
            ? result.result?.status === "completed" &&
              "ready" in result.result &&
              result.result.ready
              ? "Synthetic connection test passed."
              : "Synthetic connection test did not pass. Review its reported reason."
            : "Credential operation completed. The secret was not retained by this page."
          : "Outcome is unknown. Reconcile the saved operation; do not submit it again.",
      );
      await cache.invalidateQueries({ queryKey: scope.key("ai-connections") });
    } catch (error) {
      setMessage(
        `${error instanceof MutationFailure && !error.outcomeUnknown ? "The external request was rejected. " : ""}${error instanceof Error ? error.message : "External operation outcome is unknown."} Reconcile the original key; no automatic retry was made.`,
      );
    } finally {
      setBusy(false);
    }
  }

  async function reconcileExternal() {
    if (!externalKey) return;
    const response = await api.GET("/api/ai/external-operations/by-key/{key}", {
      params: { path: { key: externalKey } },
    });
    if (!response.data) {
      setMessage("No external-operation receipt is available yet. Reconcile again later.");
      return;
    }
    setPendingExternal(response.data.status === "outcome_unknown" ? response.data : null);
    if (response.data.status !== "outcome_unknown") await recovery.reconcile();
    const probeResult = response.data.result;
    if (
      response.data.action === "connection_probe" &&
      response.data.status === "completed" &&
      probeResult?.status === "completed" &&
      "ready" in probeResult
    ) {
      const ready = probeResult.ready;
      const revision = response.data.revision;
      const connectionId = response.data.connectionId;
      setProbeResults((current) => ({
        ...current,
        [connectionId]: { revision, ready },
      }));
    }
    setMessage(`External operation status: ${response.data.status}.`);
    await cache.invalidateQueries({ queryKey: scope.key("ai-connections") });
  }

  async function acknowledgeUnknown() {
    if (!pendingExternal || !scope.canWrite) return;
    const response = await mutation(() =>
      api.POST("/api/ai/external-operations/{operation_id}/acknowledge-unknown", {
        params: { path: { operation_id: pendingExternal.operationId } },
        body: { acknowledgeUnknownOutcome: true },
      }),
    );
    setPendingExternal(null);
    await recovery.reconcile();
    setMessage(`Uncertainty was recorded as ${response.status}; no provider action was repeated.`);
  }

  async function recover(check: () => Promise<void>) {
    if (busy || !scope.canWrite) return;
    setBusy(true);
    try {
      scope.requireWrite();
      await check();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Original attempt remains unresolved.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main>
      <h2>Built-in AI assistance</h2>
      <p>
        Use built-in models to summarize records and prepare drafts for review. This does not
        connect a personal assistant or approve work automatically.
      </p>
      {!scope.canWrite && <p>AI configuration changes require workspace write access.</p>}
      {recovery.blocked && (
        <p role="status">
          Checking or resolving the original AI attempt. New changes are locked until recovery
          completes.
        </p>
      )}
      <section aria-labelledby="ai-destination-heading">
        <h3 id="ai-destination-heading">Destination</h3>
        <p>
          Current state:{" "}
          {state.killSwitch
            ? "Paused globally"
            : activeMode === "off"
              ? "Off"
              : activeMode === "cloud"
                ? "Cloud service"
                : "On this device"}
          .{state.readiness.ready ? " Tested and ready." : " Not currently verified."}
        </p>
        <fieldset disabled={!writable || busy || !!pendingKey}>
          <legend>Choose where new built-in requests may run</legend>
          {(["off", "on_device", "cloud"] as const).map((option) => (
            <label key={option}>
              <input
                type="radio"
                name="ai-destination"
                checked={mode === option}
                onChange={() => {
                  setModeChoice(option);
                  setConnectionId("");
                }}
              />
              {option === "off" ? "Off" : option === "cloud" ? "Cloud service" : "On this device"}
            </label>
          ))}
          {mode !== "off" && (
            <label>
              Configured connection
              <select
                value={
                  connectionId || (mode === activeMode ? (state.defaultConnectionId ?? "") : "")
                }
                onChange={(event) => setConnectionId(event.target.value)}
              >
                <option value="">Select a connection</option>
                {modeConnections.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.label} · {item.modelIdentifier}
                  </option>
                ))}
              </select>
            </label>
          )}
          <label>
            <input
              type="checkbox"
              checked={state.killSwitch}
              onChange={(event) => {
                const enabled = event.target.checked;
                const key = crypto.randomUUID();
                void command(
                  key,
                  () =>
                    mutation(() =>
                      api.PUT("/api/ai/settings", {
                        body: {
                          expectedRevision: state.revision,
                          idempotencyKey: key,
                          killSwitch: enabled,
                        },
                      }),
                    ),
                  enabled ? "All AI assistance is paused." : "AI pause is cleared.",
                  [
                    "ai.settings.update",
                    "1",
                    { expectedRevision: state.revision, killSwitch: enabled },
                    key,
                  ],
                );
              }}
            />
            Pause all AI assistance
          </label>
        </fieldset>
        <button disabled={!writable || busy || !!pendingKey} onClick={() => void updateMode()}>
          Save destination
        </button>
      </section>

      <section aria-labelledby="ai-connections-heading">
        <h3 id="ai-connections-heading">Model connections</h3>
        <p>
          Only registered adapters and models are selectable. No automatic downloads or fallback
          transports are used.
        </p>
        {available.length === 0 && (
          <p role="status">
            No AI adapters are registered in this installation. Manual workflows remain available.
          </p>
        )}
        <ul>
          {connectionRows.map((item) => (
            <li key={item.id}>
              <strong>{item.label}</strong> · {item.adapterId} {item.adapterVersion} ·{" "}
              {item.modelIdentifier} ·{" "}
              {item.executionLocation === "cloud" ? "Cloud service" : "On this device"}
              <p>
                Credential: {item.credentialPresent ? "Configured" : "Not configured"}. Connection:{" "}
                {item.enabled ? "Enabled" : "Disabled"}.
                {probeResults[item.id]?.revision === item.revision
                  ? probeResults[item.id].ready
                    ? " Synthetic test passed for this revision."
                    : " Synthetic test did not pass for this revision."
                  : " This revision has not passed a synthetic test in this session."}
              </p>
              <label>
                <input
                  type="checkbox"
                  checked={item.enabled}
                  disabled={!writable || busy || !!pendingKey || pendingExternal !== null}
                  onChange={(event) => {
                    const enabled = event.target.checked;
                    const key = crypto.randomUUID();
                    void command(
                      key,
                      () =>
                        mutation(() =>
                          api.PATCH("/api/ai/connections/{connection_id}", {
                            params: { path: { connection_id: item.id } },
                            body: {
                              expectedRevision: item.revision,
                              idempotencyKey: key,
                              enabled,
                            },
                          }),
                        ),
                      "Connection status saved.",
                      [
                        "ai.connection.update",
                        item.id,
                        { expectedRevision: item.revision, enabled },
                        key,
                      ],
                    );
                  }}
                />
                Enable this connection
              </label>
              {item.executionLocation === "cloud" && (
                <fieldset disabled={!writable || busy || !!pendingKey || pendingExternal !== null}>
                  <legend>Cloud disclosure</legend>
                  <p>
                    Requests sent to this connection leave this device. Required data classes:{" "}
                    {actions
                      .flatMap((action) => action.requiredDataClasses)
                      .filter((value, index, all) => all.indexOf(value) === index)
                      .join(", ") || "none currently registered"}
                    .
                  </p>
                  <label>
                    <input
                      type="checkbox"
                      checked={disclosureAccepted}
                      onChange={(event) => setDisclosureAccepted(event.target.checked)}
                    />
                    I understand this named cloud destination receives the listed data classes.
                  </label>
                  <button
                    disabled={!disclosureAccepted || busy}
                    onClick={() => {
                      const key = crypto.randomUUID();
                      const dataClasses = actions
                        .flatMap((action) => action.requiredDataClasses)
                        .filter((value, index, all) => all.indexOf(value) === index);
                      void command(
                        key,
                        () =>
                          mutation(() =>
                            api.PUT("/api/ai/connections/{connection_id}/disclosure", {
                              params: { path: { connection_id: item.id } },
                              body: {
                                expectedRevision: item.revision,
                                idempotencyKey: key,
                                disclosureVersion: "AI-GOV-001-v1",
                                dataClasses,
                              },
                            }),
                          ),
                        "Cloud disclosure saved for this connection.",
                        [
                          "ai.connection.disclosure",
                          item.id,
                          {
                            expectedRevision: item.revision,
                            disclosureVersion: "AI-GOV-001-v1",
                            dataClasses,
                          },
                          key,
                        ],
                      );
                    }}
                  >
                    Record cloud disclosure
                  </button>
                </fieldset>
              )}
              {item.executionLocation === "cloud" && (
                <CredentialControls
                  connection={item}
                  writable={writable}
                  busy={busy || pendingExternal !== null}
                  onEffect={externalEffect}
                />
              )}
              <button
                disabled={!writable || busy || pendingExternal !== null}
                onClick={() => void externalEffect(item, "connection_probe")}
              >
                Run synthetic connection test
              </button>
            </li>
          ))}
        </ul>
        {savedConnection !== undefined ? (
          <SavedItem title="Connection saved" value={savedConnection} embedded>
            <p>Add disclosure and credentials separately before testing this connection.</p>
            <button
              type="button"
              onClick={() => {
                setSavedConnection(undefined);
                setAdapterId("");
                setModelIdentifier("");
              }}
            >
              Add another connection
            </button>
          </SavedItem>
        ) : (
          available.length > 0 && (
            <form
              onSubmit={(event) => {
                event.preventDefault();
                void createConnection(event.currentTarget);
              }}
            >
              <h4>Add a registered connection</h4>
              <label>
                Connection label
                <input name="label" required maxLength={120} />
              </label>
              <label>
                Adapter and version
                <select
                  value={adapterId}
                  required
                  onChange={(event) => {
                    setAdapterId(event.target.value);
                    setModelIdentifier("");
                  }}
                >
                  <option value="">Select registered adapter</option>
                  {available.map((item) => (
                    <option
                      key={`${item.adapterId}@${item.adapterVersion}`}
                      value={`${item.adapterId}@${item.adapterVersion}`}
                    >
                      {item.adapterId} {item.adapterVersion} · {item.executionLocation}
                    </option>
                  ))}
                </select>
              </label>
              {selectedAdapter && (
                <label>
                  Model
                  <select
                    value={modelIdentifier}
                    required
                    onChange={(event) => setModelIdentifier(event.target.value)}
                  >
                    <option value="">Select registered model</option>
                    {selectedAdapter.models.map((model) => (
                      <option key={model}>{model}</option>
                    ))}
                  </select>
                </label>
              )}
              {selectedAdapter?.executionLocation === "on_device" && (
                <fieldset>
                  <legend>Validated local runtime provenance</legend>
                  <label>
                    Model digest
                    <input name="modelArtifactDigest" required maxLength={256} />
                  </label>
                  <label>
                    Quantization
                    <input name="quantization" required maxLength={128} />
                  </label>
                  <label>
                    Runtime ID
                    <input name="runtimeId" required maxLength={128} />
                  </label>
                  <label>
                    Runtime version
                    <input name="runtimeVersion" required maxLength={128} />
                  </label>
                  <p>
                    Installation and runtime setup are operator-assisted. This form does not
                    download model files.
                  </p>
                </fieldset>
              )}
              <div className="command-form-actions" role="group" aria-label="Connection actions">
                <button
                  type="submit"
                  disabled={
                    !writable || busy || !!pendingKey || !selectedAdapter || !modelIdentifier
                  }
                >
                  Create connection
                </button>
              </div>
            </form>
          )
        )}
        {externalKey && (
          <button
            disabled={busy || !scope.canWrite}
            onClick={() => void recover(reconcileExternal)}
          >
            Check external-operation status
          </button>
        )}
        {pendingExternal && (
          <>
            <p role="alert">
              The external result is still unknown. Acknowledging closes uncertainty but does not
              claim success.
            </p>
            <button
              disabled={!scope.canWrite || busy}
              onClick={() => void recover(acknowledgeUnknown)}
            >
              Acknowledge unknown outcome
            </button>
          </>
        )}
      </section>

      <section aria-labelledby="ai-action-limits-heading">
        <h3 id="ai-action-limits-heading">Supported tasks and safeguards</h3>
        {actions.length === 0 && (
          <p>No AI actions are registered. Tasks unavailable here remain manual.</p>
        )}
        {actions.map((action) => {
          const limit = limitRows.find((item) => item.actionType === action.actionType);
          if (!limit)
            return <p key={action.actionType}>{action.actionType}: limit settings unavailable.</p>;
          const compatibleAdapters = available.filter(
            (adapter) =>
              action.requiredCapabilities.every((item) => adapter.capabilities.includes(item)) &&
              action.requiredInputModalities.every((item) =>
                adapter.inputModalities.includes(item),
              ),
          );
          const compatibleConnections = connectionRows.filter((connection) => {
            const adapter = available.find(
              (item) =>
                item.adapterId === connection.adapterId &&
                item.adapterVersion === connection.adapterVersion,
            );
            return (
              !!adapter &&
              action.requiredCapabilities.every((item) => adapter.capabilities.includes(item)) &&
              action.requiredInputModalities.every((item) => adapter.inputModalities.includes(item))
            );
          });
          const selectedConnection = compatibleConnections.find(
            (item) => item.id === limit.connectionId,
          );
          const selectedProbe = selectedConnection
            ? probeResults[selectedConnection.id]
            : undefined;
          const taskAvailability =
            compatibleAdapters.length === 0
              ? "Unsupported: no registered adapter satisfies this action’s capabilities and input modalities. Continue manually."
              : compatibleConnections.length === 0
                ? "Supported by a registered adapter, but no compatible connection is configured."
                : !limit.enabled
                  ? "This action is disabled."
                  : !selectedConnection
                    ? "Choose a compatible connection in the action limit controls."
                    : !selectedConnection.enabled
                      ? "The selected connection is disabled."
                      : !limit.allowedModels.includes(
                            `${selectedConnection.adapterId}@${selectedConnection.adapterVersion}:${selectedConnection.modelIdentifier}`,
                          )
                        ? "The selected model is not allowed for this action. Update the allowed models or choose another connection."
                        : selectedConnection.executionLocation === "cloud" &&
                            !action.requiredDataClasses.every((item) =>
                              selectedConnection.cloudDataClasses.includes(item),
                            )
                          ? "The cloud connection lacks the required data disclosure. Review it before use."
                          : selectedConnection.executionLocation === "cloud" &&
                              !selectedConnection.credentialPresent
                            ? "The cloud connection needs credentials before it can be tested."
                            : selectedProbe?.revision !== selectedConnection.revision
                              ? "Run a synthetic test for this exact connection revision before relying on it."
                              : selectedProbe.ready
                                ? "Available for new requests. Global pause and current policy still apply."
                                : "The latest synthetic test failed. Review the connection; continue manual work.";
          const modelChoices = compatibleConnections.map(
            (item) => `${item.adapterId}@${item.adapterVersion}:${item.modelIdentifier}`,
          );
          return (
            <details key={action.actionType}>
              <summary>
                {action.actionType} · {action.owningModule}
              </summary>
              <p>
                Required capabilities: {action.requiredCapabilities.join(", ") || "none"}. Input:{" "}
                {action.requiredInputModalities.join(", ")}. Cloud data classes:{" "}
                {action.requiredDataClasses.join(", ") || "none"}.
              </p>
              <p>
                Registered limits: {action.maxRunsPerUtcDay} runs/day, {action.maxPromptTokens}{" "}
                prompt tokens and {action.maxCompletionTokens} completion tokens.
              </p>
              <p role="status">{taskAvailability}</p>
              <label>
                <input
                  type="checkbox"
                  checked={limit.enabled}
                  disabled={!writable || busy || !!pendingKey}
                  onChange={(event) => void putLimit(limit, { enabled: event.target.checked })}
                />
                Enable this action
              </label>
              <label>
                Allowed connection
                <select
                  value={limit.connectionId ?? ""}
                  disabled={!writable || busy || !!pendingKey}
                  onChange={(event) =>
                    void putLimit(limit, { connectionId: event.target.value || null })
                  }
                >
                  <option value="">No connection</option>
                  {compatibleConnections.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.label} · {item.adapterId}@{item.adapterVersion}:{item.modelIdentifier}
                    </option>
                  ))}
                </select>
              </label>
              <fieldset>
                <legend>Allowed registered models</legend>
                {modelChoices.map((identity) => (
                  <label key={identity}>
                    <input
                      type="checkbox"
                      checked={limit.allowedModels.includes(identity)}
                      disabled={
                        !writable ||
                        busy ||
                        !!pendingKey ||
                        (limit.allowedModels.includes(identity) && limit.allowedModels.length === 1)
                      }
                      onChange={(event) =>
                        void putLimit(limit, {
                          allowedModels: event.target.checked
                            ? [...new Set([...limit.allowedModels, identity])]
                            : limit.allowedModels.filter((value) => value !== identity),
                        })
                      }
                    />
                    {identity}
                  </label>
                ))}
              </fieldset>
              <label>
                Daily runs
                <input
                  type="number"
                  min={1}
                  max={action.maxRunsPerUtcDay}
                  key={`${action.actionType}:daily:${limit.revision}`}
                  defaultValue={limit.maxRunsPerUtcDay}
                  disabled={!writable || busy || !!pendingKey}
                  onBlur={(event) => {
                    const value = Number(event.currentTarget.value);
                    if (Number.isInteger(value) && value > 0 && value <= action.maxRunsPerUtcDay)
                      void putLimit(limit, { maxRunsPerUtcDay: value });
                    else setMessage(`Daily runs must be between 1 and ${action.maxRunsPerUtcDay}.`);
                  }}
                />
              </label>
              <label>
                Prompt token limit
                <input
                  type="number"
                  min={1}
                  max={action.maxPromptTokens}
                  key={`${action.actionType}:prompt:${limit.revision}`}
                  defaultValue={limit.maxPromptTokens}
                  disabled={!writable || busy}
                  onBlur={(event) => {
                    const value = Number(event.currentTarget.value);
                    if (Number.isInteger(value) && value > 0 && value <= action.maxPromptTokens)
                      void putLimit(limit, { maxPromptTokens: value });
                    else
                      setMessage(`Prompt tokens must be between 1 and ${action.maxPromptTokens}.`);
                  }}
                />
              </label>
              <label>
                Completion token limit
                <input
                  type="number"
                  min={1}
                  max={action.maxCompletionTokens}
                  key={`${action.actionType}:completion:${limit.revision}`}
                  defaultValue={limit.maxCompletionTokens}
                  disabled={!writable || busy}
                  onBlur={(event) => {
                    const value = Number(event.currentTarget.value);
                    if (Number.isInteger(value) && value > 0 && value <= action.maxCompletionTokens)
                      void putLimit(limit, { maxCompletionTokens: value });
                    else
                      setMessage(
                        `Completion tokens must be between 1 and ${action.maxCompletionTokens}.`,
                      );
                  }}
                />
              </label>
            </details>
          );
        })}
        <h4>Redaction profiles</h4>
        {profileRows.map((profile) => (
          <details key={`${profile.name}:${profile.version}`}>
            <summary>
              {profile.name} v{profile.version} · {profile.actionTypes.join(", ")}
            </summary>
            <ul>
              {Object.entries(profile.fieldHandling).map(([field, handling]) => (
                <li key={field}>
                  {field}: {handling}
                </li>
              ))}
            </ul>
          </details>
        ))}
      </section>

      <section aria-labelledby="ai-drafts-heading">
        <h3 id="ai-drafts-heading">Drafts for review</h3>
        <label>
          Draft status
          <select
            value={draftStatus}
            onChange={(event) => {
              setDraftStatus(
                event.target.value as Schema["DraftSummaryResponse"]["status"] | "all",
              );
              setDraftCursor(undefined);
            }}
          >
            <option value="proposed">Proposed</option>
            <option value="edited">Edited</option>
            <option value="approved">Approved</option>
            <option value="dismissed">Dismissed</option>
            <option value="superseded">Superseded</option>
            <option value="all">All statuses</option>
          </select>
        </label>
        {drafts.isPending && <p role="status">Loading AI drafts…</p>}
        {drafts.error && <ApiError error={drafts.error} />}
        {drafts.data?.items.length === 0 && <p>No AI drafts match this status on this page.</p>}
        <ul>
          {drafts.data?.items.map((draft) => (
            <li key={draft.id}>
              <Link to={`/ai/review/${draft.id}`}>
                {draft.entityKind} · {draft.actionType}
              </Link>{" "}
              · {draft.status} · {draft.owningModule}
            </li>
          ))}
        </ul>
        {drafts.data?.nextCursor && (
          <button onClick={() => setDraftCursor(drafts.data?.nextCursor ?? undefined)}>
            Next drafts
          </button>
        )}
        {draftCursor && (
          <button onClick={() => setDraftCursor(undefined)}>First drafts page</button>
        )}
      </section>
      {pendingKey && (
        <p>
          <button disabled={busy || !scope.canWrite} onClick={() => void recover(reconcileCommand)}>
            Check original command receipt
          </button>
        </p>
      )}
      {message && <p role="status">{message}</p>}
    </main>
  );

  async function putLimit(
    limit: Schema["ActionLimitResponse"],
    patch: Partial<Schema["LimitInput"]>,
  ) {
    const key = crypto.randomUUID();
    const body: Schema["LimitInput"] = {
      expectedRevision: limit.revision,
      idempotencyKey: key,
      enabled: patch.enabled ?? limit.enabled,
      connectionId: patch.connectionId === undefined ? limit.connectionId : patch.connectionId,
      maxRunsPerUtcDay: patch.maxRunsPerUtcDay ?? limit.maxRunsPerUtcDay,
      maxPromptTokens: patch.maxPromptTokens ?? limit.maxPromptTokens,
      maxCompletionTokens: patch.maxCompletionTokens ?? limit.maxCompletionTokens,
      allowedModels: patch.allowedModels ?? limit.allowedModels,
    };
    await command(
      key,
      () =>
        mutation(() =>
          api.PUT("/api/ai/limits/{action_type}", {
            params: { path: { action_type: limit.actionType } },
            body,
          }),
        ),
      "Action safeguards saved.",
      ["ai.action_limit.update", limit.actionType, body, key],
    );
  }
}

function CredentialControls({
  connection,
  writable,
  busy,
  onEffect,
}: {
  connection: Connection;
  writable: boolean;
  busy: boolean;
  onEffect: (
    connection: Connection,
    action: "credential_set" | "credential_delete" | "connection_probe",
    credential?: string,
  ) => Promise<void>;
}) {
  const [credential, setCredential] = useState("");
  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        const secret = credential;
        setCredential("");
        void onEffect(connection, "credential_set", secret);
      }}
    >
      <label>
        Provider credential (write-only)
        <input
          type="password"
          autoComplete="new-password"
          value={credential}
          onChange={(event) => setCredential(event.target.value)}
          maxLength={8192}
        />
      </label>
      <button type="submit" disabled={!writable || busy || !credential}>
        Set or replace credential
      </button>
      {connection.credentialPresent && (
        <button
          type="button"
          disabled={!writable || busy}
          onClick={() => void onEffect(connection, "credential_delete")}
        >
          Delete credential
        </button>
      )}
      <p>
        The key is sent once to the OS credential store and is excluded from workspace history and
        backup. This page never saves it.
      </p>
    </form>
  );
}

export function AiDraftReview() {
  const { id = "" } = useParams();
  const { scope } = useWorkspace();
  const cache = useQueryClient();
  const recovery = useAiRecovery(id);
  const detail = useQuery({
    queryKey: scope.key("ai-draft", id),
    enabled: !!id,
    queryFn: async ({ signal }) =>
      readResult(
        await api.GET("/api/ai/drafts/{draft_id}", { signal, params: { path: { draft_id: id } } }),
      ),
  });
  const writable = scope.canWrite && !recovery.blocked;
  const [payload, setPayload] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const [reviewedVersion, setReviewedVersion] = useState<number | null>(null);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [savedEdits, setSavedEdits] = useState<unknown>();
  const attempt = recovery.current;
  if (detail.isPending || detail.error)
    return (
      <>
        <ParentBackLink to="/settings/ai">← Back to AI assistance</ParentBackLink>
        {detail.error ? <ApiError error={detail.error} /> : <p role="status">Loading AI draft…</p>}
      </>
    );
  const draft = detail.data;
  if (!draft)
    return (
      <>
        <ParentBackLink to="/settings/ai">← Back to AI assistance</ParentBackLink>
        <p role="alert">AI draft is unavailable.</p>
      </>
    );
  const active = draft.status === "proposed" || draft.status === "edited";
  const reviewedSource = reviewedVersion === draft.version;
  const displayedPayload = payload ?? json(draft.draftPayload);
  let parseError = "";
  let parsedPayload: Record<string, unknown> | null = null;
  try {
    const parsed: unknown = JSON.parse(displayedPayload);
    if (parsed !== null && typeof parsed === "object" && !Array.isArray(parsed))
      parsedPayload = parsed as Record<string, unknown>;
    else parseError = "Draft payload must be a JSON object.";
  } catch {
    parseError = "Draft payload must be valid JSON.";
  }
  const dirtyPayload =
    !!parseError || canonicalRequest(parsedPayload) !== canonicalRequest(draft.draftPayload);

  async function decide(action: "edit" | "approve" | "dismiss", body: unknown) {
    if (!writable || busy || !active) return;
    if (
      action === "approve" &&
      (!draft.approvalAvailable ||
        dirtyPayload ||
        !reviewedSource ||
        draft.currentSource?.availability !== "available" ||
        draft.currentSource.comparisonState !== "current" ||
        draft.currentSource.tombstoned)
    ) {
      setMessage(
        "Approval requires a registered owner handler and explicit review of an available current source.",
      );
      return;
    }
    if (attempt) return;
    const key = crypto.randomUUID();
    scope.requireWrite();
    setBusy(true);
    setMessage("");
    try {
      const common = {
        idempotencyKey: key,
        version: draft.version,
        operatorNote: note || null,
      };
      await recovery.prepare(
        `ai.draft.${action}`,
        id,
        { ...common, ...(action === "edit" ? { draftPayload: body } : {}) },
        key,
      );
      if (action === "edit") {
        const edited = await mutation(() =>
          api.PATCH("/api/ai/drafts/{draft_id}", {
            params: { path: { draft_id: id } },
            body: { ...common, draftPayload: body as Record<string, unknown> },
          }),
        );
        // Render only after the original OPS attempt is acknowledged below.
        await recovery.reconcile();
        setSavedEdits({ ...edited, draftPayload: body, operatorNote: note || null });
      } else if (action === "approve") {
        await mutation(() =>
          api.POST("/api/ai/drafts/{draft_id}/approve", {
            params: { path: { draft_id: id } },
            body: common,
          }),
        );
      } else {
        await mutation(() =>
          api.POST("/api/ai/drafts/{draft_id}/dismiss", {
            params: { path: { draft_id: id } },
            body: common,
          }),
        );
      }
      if (action !== "edit") await recovery.reconcile();
      setReviewedVersion(null);
      if (action === "edit") setPayload(null);
      setMessage(
        action === "approve"
          ? "The owning domain recorded the approved result."
          : action === "dismiss"
            ? "Draft dismissed."
            : "Draft edits saved.",
      );
      await cache.invalidateQueries({ queryKey: scope.key("ai-draft", id) });
      await cache.invalidateQueries({ queryKey: scope.key("ai-drafts") });
    } catch (error) {
      setMessage(
        error instanceof Error
          ? `${error.message} Review the current source and recover the original command before another decision.`
          : "Command outcome is unknown. Recover the original command before continuing.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function reconcile() {
    if (!attempt || busy || !scope.canWrite) return;
    setBusy(true);
    try {
      scope.requireWrite();
      const result = await api.GET("/api/ai/command-operations/by-key/{key}", {
        params: { path: { key: attempt.attemptKey ?? "" } },
      });
      if (!result.data) {
        setMessage(
          "No receipt is available yet. Preserve this attempt and check again before starting another decision.",
        );
        return;
      }
      await recovery.reconcile();
      setReviewedVersion(null);
      if (result.data.action === "edited")
        setSavedEdits({
          ...result.data.result,
          draftPayload: attempt.payload.draftPayload,
          operatorNote: attempt.payload.operatorNote,
        });
      setPayload(null);
      setMessage("Original AI review receipt found; reloading the draft.");
      await cache.invalidateQueries({ queryKey: scope.key("ai-draft", id) });
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Original review remains unresolved.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main>
      <p>
        <ParentBackLink to="/settings/ai">← Back to AI assistance</ParentBackLink>
      </p>
      <h2>Review AI draft</h2>
      <p>
        Generated with {draft.provenance.transportProvider ?? "registered source"}/
        {draft.provenance.modelIdentifier ?? "external proposal"} ·{" "}
        {draft.provenance.executionLocation ?? "review only"}. Status: {draft.status} · Version{" "}
        {draft.version}.
      </p>
      <section>
        <h3>Source and provenance</h3>
        {draft.currentSource?.comparisonState !== "current" && (
          <p role="alert">
            This draft no longer matches the current source. Review or correct the source in its
            owning workflow before requesting a new draft; this snapshot cannot be approved.
          </p>
        )}
        <dl>
          <dt>Source</dt>
          <dd>
            {draft.sourceEntityType} · {draft.sourceEntityId}
          </dd>
          <dt>Frozen source revision</dt>
          <dd>{draft.sourceRevision}</dd>
          <dt>Frozen source fingerprint</dt>
          <dd>
            <code>{draft.sourceFingerprint}</code>
          </dd>
          <dt>Current source</dt>
          <dd>
            {draft.currentSource
              ? `${draft.currentSource.availability}; ${draft.currentSource.comparisonState}${draft.currentSource.tombstoned ? "; removed" : ""}`
              : "Current source projection unavailable"}
          </dd>
          <dt>Redaction</dt>
          <dd>
            {draft.provenance.redactionProfile} v{draft.provenance.redactionProfileVersion}
          </dd>
          <dt>Template</dt>
          <dd>
            {draft.provenance.promptTemplateId ?? "Not applicable"}{" "}
            {draft.provenance.promptTemplateVersion ?? ""}
          </dd>
          <dt>Usage</dt>
          <dd>
            {draft.provenance.promptTokens ?? "Unknown"} prompt /{" "}
            {draft.provenance.completionTokens ?? "Unknown"} completion tokens
          </dd>
          <dt>Adapter version</dt>
          <dd>{draft.provenance.adapterVersion ?? "Not applicable"}</dd>
          <dt>Model artifact</dt>
          <dd>{draft.provenance.modelArtifactDigest ?? "Not recorded"}</dd>
          <dt>Runtime</dt>
          <dd>
            {draft.provenance.runtimeId ?? "Not recorded"} {draft.provenance.runtimeVersion ?? ""} ·
            quantization {draft.provenance.quantization ?? "Not recorded"}
          </dd>
        </dl>
        {draft.supersedesDraftId && (
          <p>
            <Link to={`/ai/review/${draft.supersedesDraftId}`}>
              View the draft this one replaces
            </Link>
          </p>
        )}
      </section>
      {draft.confidence && (
        <details>
          <summary>Registered confidence and provenance</summary>
          <pre>{json(draft.confidence)}</pre>
        </details>
      )}
      <details>
        <summary>Governed input sent for this draft</summary>
        <pre>{json(draft.governedInput)}</pre>
      </details>
      <section>
        <h3>Suggestion and operator edits</h3>
        {savedEdits !== undefined ? (
          <SavedItem title="AI draft updated" value={savedEdits} embedded>
            <button type="button" onClick={() => setSavedEdits(undefined)}>
              Continue reviewing draft
            </button>
          </SavedItem>
        ) : (
          <>
            <label>
              Draft payload (registered schema)
              <textarea
                rows={12}
                value={displayedPayload}
                onChange={(event) => {
                  setPayload(event.target.value);
                  setReviewedVersion(null);
                }}
                disabled={!active || !writable || busy || !!attempt}
              />
            </label>
            {parseError && <p role="alert">{parseError}</p>}
            {dirtyPayload && <p>Save draft edits before reviewing and approving this version.</p>}
            <label>
              Operator note
              <textarea
                maxLength={1000}
                value={note}
                onChange={(event) => setNote(event.target.value)}
                disabled={!active || !writable || busy || !!attempt}
              />
            </label>
            {active && (
              <div className="command-form-actions" role="group" aria-label="Draft actions">
                <button
                  type="button"
                  className="command-primary-action"
                  disabled={!writable || busy || !!attempt || !!parseError || !parsedPayload}
                  onClick={() => void decide("edit", parsedPayload)}
                >
                  Save draft edits
                </button>
                <button
                  type="button"
                  disabled={!writable || busy || !!attempt}
                  onClick={() => void decide("dismiss", null)}
                >
                  Dismiss draft
                </button>
              </div>
            )}
            {draft.approvalAvailable && active && (
              <fieldset>
                <legend>Source checked approval</legend>
                <p>
                  Approval runs through the owning domain, which checks current source state and
                  records the official result in its transaction.
                </p>
                <label>
                  <input
                    type="checkbox"
                    checked={reviewedSource}
                    onChange={(event) =>
                      setReviewedVersion(event.target.checked ? draft.version : null)
                    }
                    disabled={
                      !writable ||
                      busy ||
                      !!attempt ||
                      dirtyPayload ||
                      draft.currentSource?.availability !== "available" ||
                      draft.currentSource.comparisonState !== "current" ||
                      draft.currentSource.tombstoned
                    }
                  />
                  I reviewed the current source shown above.
                </label>
                <button
                  disabled={
                    !writable ||
                    busy ||
                    !!attempt ||
                    dirtyPayload ||
                    !reviewedSource ||
                    draft.currentSource?.availability !== "available" ||
                    draft.currentSource.comparisonState !== "current" ||
                    draft.currentSource.tombstoned
                  }
                  onClick={() => void decide("approve", null)}
                >
                  Approve through {draft.owningModule}
                </button>
              </fieldset>
            )}
            {!draft.approvalAvailable && active && (
              <p>
                Approval is unavailable because no owning-domain approval handler is registered for
                this draft.
              </p>
            )}
            {attempt && (
              <button disabled={busy || !scope.canWrite} onClick={() => void reconcile()}>
                Reconcile original review command
              </button>
            )}
          </>
        )}
      </section>
      <section>
        <h3>Review history</h3>
        {draft.reviewHistory.length ? (
          <ol>
            {draft.reviewHistory.map((entry) => (
              <li key={entry.id}>
                {entry.decision} · version {entry.draftVersionBefore} → {entry.draftVersionAfter} ·{" "}
                {entry.decidedAt}
                {entry.operatorNote && <p>{entry.operatorNote}</p>}
                {entry.resultEntityType && entry.resultEntityId && (
                  <p>
                    Recorded result: {entry.resultEntityType} · {entry.resultEntityId}
                  </p>
                )}
              </li>
            ))}
          </ol>
        ) : (
          <p>No review decisions yet.</p>
        )}
      </section>
      {message && <p role="status">{message}</p>}
    </main>
  );
}
