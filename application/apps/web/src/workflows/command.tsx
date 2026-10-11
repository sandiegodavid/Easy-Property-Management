import { useCallback, useState } from "react";
import { useWatch } from "react-hook-form";
import { Link, useLocation, useSearchParams } from "react-router-dom";
import { api } from "@epm/contracts";
import {
  workflows,
  dispatchWorkflow,
  record,
  scalar,
  validateRequest,
  type Workflow,
} from "@epm/contracts/workflows";
import { useQuery } from "@tanstack/react-query";
import { useWorkspace } from "../app/workspace-gate";
import { useRecoverableForm, RecoveryNavigation } from "../shared/use-recoverable-form";
import { mutation } from "../shared/mutations";
import type { Recovery } from "../shared/recovery";
import { clean, Fields, type Choices } from "./fields";
import { Facts, readResult } from "./reads";

export function workflowUrl(formKey: string, sourceId?: string, childId?: string) {
  const params = new URLSearchParams({ workflow: formKey });
  if (sourceId) params.set("target", sourceId);
  if (childId) params.set("child", childId);
  const family = formKey.startsWith("portfolio.")
    ? "properties"
    : formKey.startsWith("provider.")
      ? "providers"
      : formKey.startsWith("lease.") ||
          formKey.startsWith("inspection.") ||
          formKey === "file.link.archive"
        ? "leasing"
        : "parties";
  return `/${family}?${params}`;
}

function toPayload(definition: Workflow, body: Record<string, unknown>, child?: string) {
  const values = { ...body };
  delete values.idempotencyKey;
  let payload = values;
  if (definition.formKey.startsWith("lease.")) {
    const { expectedLeaseRevision, expectedRevision, ...rest } = values;
    payload = { ...rest, expectedRevision: expectedLeaseRevision };
    if (expectedRevision !== undefined) payload.expectedSpaceRevision = expectedRevision;
  }
  if (definition.nesting === "changes") {
    const { expectedPropertyRevision, ...changes } = values;
    payload = { expectedPropertyRevision, changes };
  }
  if (definition.nesting === "occupancy") {
    const { occupancy, ...rest } = values;
    payload = { ...record(occupancy), ...rest };
  }
  if (definition.childKey) payload[definition.childKey] = child;
  return payload;
}
function toBody(definition: Workflow, payload: Record<string, unknown>, key?: string) {
  const values = { ...payload };
  if (definition.childKey) delete values[definition.childKey];
  let body = values;
  if (definition.formKey.startsWith("lease.")) {
    const { expectedRevision, expectedSpaceRevision, ...rest } = values;
    body = { ...rest, expectedLeaseRevision: expectedRevision };
    if (expectedSpaceRevision !== undefined) body.expectedRevision = expectedSpaceRevision;
  }
  if (definition.nesting === "changes") {
    const { changes, ...rest } = values;
    body = { ...rest, ...record(changes) };
  }
  if (definition.nesting === "occupancy") {
    const { reason, expectedRevision, ...occupancy } = values;
    body = { reason, expectedRevision, occupancy };
  }
  return key ? { ...body, idempotencyKey: key } : body;
}

export function CommandLinks({
  keys,
  target,
  child,
  title = "Actions",
}: {
  keys: string[];
  target?: string;
  child?: string;
  title?: string;
}) {
  const { scope } = useWorkspace();
  const location = useLocation();
  if (!scope.canWrite) return <p>Workspace writes are unavailable.</p>;
  return (
    <details className="workflow-actions">
      <summary>{title}</summary>
      <nav aria-label={title}>
        {keys.map((key) => {
          const definition = workflows.find((item) => item.formKey === key);
          return (
            definition && (
              <Link
                key={key}
                to={workflowUrl(key, target, child)}
                state={{ returnTo: location.pathname + location.search }}
              >
                {definition.title}
              </Link>
            )
          );
        })}
      </nav>
    </details>
  );
}

export function CommandLoader({
  definition,
  sourceId,
  childId,
  revision,
  initial = {},
  choices = {},
  returnTo,
  reviewSource,
  checkSource,
}: {
  definition: Workflow;
  sourceId?: string;
  childId?: string;
  revision: number;
  initial?: Record<string, unknown>;
  choices?: Choices;
  returnTo?: string;
  reviewSource?: () => Promise<{ revision: number; value: unknown }>;
  checkSource?: (values: Record<string, unknown>) => Promise<void>;
}) {
  const { scope } = useWorkspace();
  const [params] = useSearchParams();
  const recoveryId = params.get("resume");
  const recovery = useQuery({
    queryKey: scope.key("workflow-recovery", recoveryId),
    enabled: !!recoveryId,
    queryFn: async ({ signal }) => {
      const response = await api.GET("/api/operator/recovery/{record_id}", {
        signal,
        params: { path: { record_id: recoveryId! } },
      });
      if (!response.data) throw new Error("Could not load this unfinished form.");
      if (
        response.data.formKey !== definition.formKey ||
        response.data.sourceId !== (sourceId ?? null)
      )
        throw new Error("This form belongs to a different workflow or source.");
      return response.data;
    },
  });
  if (recoveryId && recovery.isPending) return <p role="status">Loading unfinished form…</p>;
  if (recovery.error) return <p role="alert">{recovery.error.message}</p>;
  const selectedChild =
    childId ??
    (definition.childKey && recovery.data
      ? scalar(recovery.data.payload[definition.childKey])
      : undefined);
  return (
    <CommandEditor
      key={`${scope.workspaceId}:${scope.runtimeEpoch}:${definition.formKey}:${sourceId}:${selectedChild}:${recoveryId}`}
      definition={definition}
      sourceId={sourceId}
      childId={selectedChild}
      revision={revision}
      initial={initial}
      choices={choices}
      recovered={recovery.data}
      returnTo={returnTo}
      reviewSource={reviewSource}
      checkSource={checkSource}
    />
  );
}

function CommandEditor({
  definition,
  sourceId,
  childId,
  revision,
  initial,
  choices,
  recovered,
  returnTo,
  reviewSource,
  checkSource,
}: {
  definition: Workflow;
  sourceId?: string;
  childId?: string;
  revision: number;
  initial: Record<string, unknown>;
  choices: Choices;
  recovered?: Recovery;
  returnTo?: string;
  reviewSource?: () => Promise<{ revision: number; value: unknown }>;
  checkSource?: (values: Record<string, unknown>) => Promise<void>;
}) {
  const { scope } = useWorkspace();
  const location = useLocation();
  const [id] = useState(() => recovered?.id ?? crypto.randomUUID());
  const [error, setError] = useState<string>();
  const [review, setReview] = useState<{
    revision: number;
    value: unknown;
    spaceRevision?: number;
  }>();
  const [attachment, setAttachment] = useState<File>();
  const [selecting, setSelecting] = useState(false);
  const evidence = definition.formKey === "inspection.evidence.attach";
  const [removalConfirmed, setRemovalConfirmed] = useState(false);
  const requiresRemovalConfirmation = definition.formKey === "lease.participant.remove";
  const [candidates, setCandidates] = useState<string[]>([]);
  const revisionField =
    definition.sourceKind === "property" || definition.formKey === "portfolio.property.create"
      ? "expectedPropertyRevision"
      : definition.formKey.startsWith("lease.")
        ? "expectedLeaseRevision"
        : "expectedRevision";
  const project = useCallback(
    (values: { data: Record<string, unknown> }) =>
      toPayload(definition, record(clean(definition.schema, values.data)), childId),
    [definition, childId],
  );
  const { form, controller, state, blocker } = useRecoverableForm({
    id,
    identity: {
      formKey: definition.formKey,
      schemaVersion: 1,
      sourceKind: definition.sourceKind,
      sourceId: sourceId ?? null,
      baseSourceRevision: definition.sourceKind ? String(revision) : null,
    },
    initial: {
      data: recovered
        ? toBody(definition, recovered.payload)
        : { ...initial, [revisionField]: revision },
    },
    recovered,
    project,
  });
  const values = useWatch({ control: form.control, name: "data" }) ?? {};
  const locked =
    state.command === "submitting" ||
    state.command === "outcome_unknown" ||
    state.command === "committed" ||
    state.draft === "conflicted";
  async function dispatch(saved: Recovery) {
    const key = saved.attemptKey;
    if (!key) throw new Error("Prepare the original command identity first.");
    return mutation<unknown>(async () => {
      if (evidence) {
        if (!attachment) throw new Error("Reselect the original evidence before retrying.");
        const selected = await evidenceMetadata(attachment);
        for (const key of Object.keys(selected))
          if (selected[key] !== saved.payload[key])
            throw new Error(
              "Selected evidence does not match the saved file. Reselect the original file.",
            );
        const body = new FormData();
        body.append("file", attachment);
        body.append("purpose", scalar(saved.payload.purpose));
        body.append("expected_revision", scalar(saved.payload.expectedRevision));
        body.append("idempotency_key", key);
        return api.POST("/api/condition-observations/{observation_id}/evidence", {
          params: { path: { observation_id: sourceId! } },
          body: {
            file: "",
            purpose: saved.payload.purpose as "condition_photo" | "supporting_document",
            expected_revision: Number(saved.payload.expectedRevision),
            idempotency_key: key,
          },
          bodySerializer: () => body,
        });
      }
      const response = await dispatchWorkflow(
        definition.formKey,
        sourceId ?? "",
        scalar(saved.payload[definition.childKey ?? ""], childId),
        toBody(definition, saved.payload, key),
      );
      const identifiers = record(record(response.error).detail).candidatePartyIds;
      if (Array.isArray(identifiers))
        setCandidates(
          identifiers.filter((item): item is string => typeof item === "string").slice(0, 10),
        );
      return response;
    });
  }
  async function action(operation: () => Promise<unknown>) {
    setError(undefined);
    try {
      await operation();
      await scope.client.invalidateQueries({
        predicate: (query) =>
          query.queryKey[0] === scope.workspaceId &&
          !scalar(query.queryKey[2]).endsWith("command-source") &&
          query.queryKey[2] !== "workflow-recovery" &&
          query.queryKey[2] !== "recovery",
      });
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Command failed.");
      await scope.client.invalidateQueries({
        predicate: (query) =>
          query.queryKey[0] === scope.workspaceId &&
          !scalar(query.queryKey[2]).endsWith("command-source") &&
          query.queryKey[2] !== "recovery" &&
          query.queryKey[2] !== "workflow-recovery",
      });
    }
  }
  async function readCurrent() {
    if (!sourceId) throw new Error("This command has no current source.");
    if (reviewSource) {
      setReview(await reviewSource());
      return;
    }
    switch (definition.sourceKind) {
      case "lease": {
        const lease = readResult(
          await api.GET("/api/leases/{lease_id}", { params: { path: { lease_id: sourceId } } }),
        );
        const space =
          "expectedRevision" in (definition.schema.properties ?? {})
            ? readResult(
                await api.GET("/api/spaces/{space_id}/status", {
                  params: { path: { space_id: lease.spaceId } },
                }),
              )
            : undefined;
        setReview({ revision: lease.leaseRevision, value: lease, spaceRevision: space?.revision });
        break;
      }
      case "property": {
        const item = readResult(
          await api.GET("/api/properties/{property_id}", {
            params: { path: { property_id: sourceId } },
          }),
        );
        setReview({ revision: item.propertyRevision, value: item });
        break;
      }
      case "space": {
        const item = readResult(
          await api.GET("/api/spaces/{space_id}/status", {
            params: { path: { space_id: sourceId } },
          }),
        );
        setReview({ revision: item.revision, value: item });
        break;
      }
      case "party": {
        const item = readResult(
          await api.GET("/api/parties/{party_id}", { params: { path: { party_id: sourceId } } }),
        );
        setReview({ revision: item.revision, value: item });
        break;
      }
      case "tenant": {
        const item = readResult(
          await api.GET("/api/tenants/{party_id}", { params: { path: { party_id: sourceId } } }),
        );
        setReview({ revision: item.profile.revision, value: item.profile });
        break;
      }
      case "provider": {
        const item = readResult(
          await api.GET("/api/providers/{party_id}", { params: { path: { party_id: sourceId } } }),
        );
        setReview({ revision: item.profile.revision, value: item.profile });
        break;
      }
      case "provider_category": {
        const items = readResult(
          await api.GET("/api/provider-categories", { params: { query: { archiveState: "all" } } }),
        );
        const item = items.find((value) => value.id === sourceId);
        if (!item) throw new Error("Category unavailable.");
        setReview({ revision: item.revision, value: item });
        break;
      }
    }
  }
  const back =
    typeof record(location.state).returnTo === "string"
      ? String(record(location.state).returnTo)
      : (returnTo ??
        (definition.sourceKind === "property"
          ? `/properties/${sourceId}/details`
          : definition.sourceKind === "space"
            ? `/properties?space=${sourceId}`
            : definition.sourceKind === "provider"
              ? `/providers/${sourceId}/details`
              : definition.sourceKind === "party" || definition.sourceKind === "tenant"
                ? `/parties?identity=${sourceId}`
                : `/${definition.formKey.startsWith("provider.") ? "providers" : definition.formKey.startsWith("lease.") || definition.formKey.startsWith("inspection.") ? "leasing" : "properties"}`));
  return (
    <section aria-label={definition.title} className="command-editor">
      <h2>{definition.title}</h2>
      <p>
        Review the displayed record and make an explicit change. Saved input is an unfinished form,
        not an official record.
      </p>
      <p>
        Displayed source revision: {scalar(values[revisionField], String(revision))}. This command
        retains its original revision and attempt identity.
      </p>
      <p role="status">
        Draft {state.draft} · Command {state.command}
      </p>
      {(error ?? state.error) && <p role="alert">{error ?? state.error}</p>}
      {candidates.length > 0 && (
        <section aria-label="Possible duplicate identities">
          <h3>Review possible duplicate identities</h3>
          <p>
            The server has not confirmed a new record. Review these shared identities before
            deciding whether a separate identity is needed.
          </p>
          {candidates.map((candidate) => (
            <p key={candidate}>
              <Link to={`/parties?identity=${candidate}`}>Review identity {candidate}</Link>
            </p>
          ))}
        </section>
      )}
      {state.problem && (
        <ul>
          {Object.entries(state.problem.fieldErrors).map(([name, errors]) => (
            <li key={name}>
              {name}: {errors.join(" ")}
            </li>
          ))}
        </ul>
      )}
      <form
        onSubmit={(event) => {
          event.preventDefault();
          void action(async () => {
            if (evidence && !attachment)
              throw new Error("Select the evidence file before submitting.");
            if (requiresRemovalConfirmation && !removalConfirmed)
              throw new Error("Confirm removal of this Lease participant.");
            validateRequest(definition.schema, {
              ...record(clean(definition.schema, values)),
              idempotencyKey: crypto.randomUUID(),
            });
            if (checkSource) await checkSource(values);
            await controller.submit(dispatch);
          });
        }}
      >
        <fieldset disabled={locked || !scope.canWrite}>
          <legend>Requested change</legend>
          {requiresRemovalConfirmation && (
            <label>
              <input
                type="checkbox"
                checked={removalConfirmed}
                onChange={(event) => setRemovalConfirmed(event.target.checked)}
              />
              I confirm removal of this Lease participant
            </label>
          )}
          {evidence && (
            <>
              <p>
                Files are never saved in unfinished forms. After restart, reselect the original
                file; its name, size and SHA-256 must match before replay.
              </p>
              <label>
                Evidence file (required)
                <input
                  type="file"
                  disabled={selecting}
                  onChange={(event) => {
                    const file = event.target.files?.[0];
                    setAttachment(undefined);
                    if (!file) return;
                    setSelecting(true);
                    void evidenceMetadata(file)
                      .then((metadata) => {
                        if (
                          recovered &&
                          Object.entries(metadata).some(
                            ([key, value]) => recovered.payload[key] !== value,
                          )
                        )
                          throw new Error("Selected evidence does not match the saved file.");
                        form.setValue("data", { ...form.getValues("data"), ...metadata });
                        setAttachment(file);
                        setError(undefined);
                      })
                      .catch((cause: unknown) =>
                        setError(
                          cause instanceof Error ? cause.message : "Could not read evidence.",
                        ),
                      )
                      .finally(() => setSelecting(false));
                  }}
                />
              </label>
              <Facts
                value={values}
                fields={["originalName", "mediaType", "sizeBytes", "contentSha256"]}
              />
            </>
          )}
          <Fields
            schema={
              evidence
                ? {
                    ...definition.schema,
                    properties: { purpose: definition.schema.properties!.purpose },
                  }
                : definition.schema
            }
            value={values}
            onChange={(next) => form.setValue("data", record(next))}
            choices={choices}
            disabled={locked}
          />
        </fieldset>
        {!locked && (
          <>
            <button type="submit" disabled={!scope.canWrite || selecting}>
              Save {definition.title.toLowerCase()}
            </button>
            <button
              type="button"
              onClick={() => {
                void action(() => controller.flush());
              }}
            >
              Save unfinished form
            </button>
          </>
        )}
      </form>
      {state.command === "outcome_unknown" && (
        <>
          <p>The outcome is unresolved. Check the original receipt before continuing.</p>
          <button
            onClick={() => {
              void action(() => controller.reconcile());
            }}
          >
            Check original result
          </button>
          <button
            onClick={() => {
              void action(() => controller.replay(dispatch));
            }}
          >
            Retry original attempt
          </button>
        </>
      )}
      {state.draft === "failed" && !locked && (
        <button
          onClick={() => {
            void action(() => controller.flush());
          }}
        >
          Retry saving input
        </button>
      )}
      {state.draft === "conflicted" && (
        <p>
          Your input is retained. Return to the current record to review its latest revision before
          starting a new command.
        </p>
      )}
      {definition.sourceKind &&
        state.command !== "outcome_unknown" &&
        state.command !== "committed" &&
        state.command !== "submitting" && (
          <button
            onClick={() => {
              void action(readCurrent);
            }}
          >
            Review current source
          </button>
        )}
      {review && (
        <section aria-label="Current source review">
          <h3>Current source revision {review.revision}</h3>
          <Facts
            value={review.value}
            fields={[
              "displayName",
              "status",
              "archivedAt",
              "updatedAt",
              "selectionStatus",
              "notes",
            ]}
          />
          <p>
            Your requested business fields remain unchanged. Only the concurrency revision will
            change after you confirm this review.
          </p>
          <button
            onClick={() => {
              void action(async () => {
                const response = await api.GET("/api/operator/recovery/{record_id}", {
                  params: { path: { record_id: id } },
                });
                if (!response.data && response.response.status !== 404)
                  throw new Error("Could not check the saved form.");
                controller.reviewSource(
                  response.data,
                  review.revision,
                  definition.formKey.startsWith("lease.") ? "expectedRevision" : revisionField,
                );
                form.setValue("data", {
                  ...values,
                  [revisionField]: review.revision,
                  ...(review.spaceRevision === undefined
                    ? {}
                    : { expectedRevision: review.spaceRevision }),
                });
                await controller.flush();
                setReview(undefined);
              });
            }}
          >
            Keep my edits with this reviewed revision
          </button>
        </section>
      )}
      {state.record?.receipt && (
        <section aria-label="Committed result">
          <h3>Committed result</h3>
          <p>Operation {state.record.receipt.receiptId}</p>
          <FactsResult value={state.record.receipt.result} />
          {(definition.formKey.startsWith("lease.") ||
            definition.formKey.startsWith("inspection.")) && (
            <OriginalWorkflowResult
              family={definition.formKey.startsWith("lease.") ? "lease" : "inspection"}
              operationId={state.record.receipt.receiptId}
            />
          )}
        </section>
      )}
      <Link to={back}>Return to current record</Link>
      <RecoveryNavigation controller={controller} blocker={blocker} />
    </section>
  );
}

function OriginalWorkflowResult({
  family,
  operationId,
}: {
  family: "lease" | "inspection";
  operationId: string;
}) {
  const { scope } = useWorkspace();
  const result = useQuery({
    queryKey: scope.key("original-workflow-result", family, operationId),
    queryFn: async ({ signal }) => {
      if (family === "lease")
        return readResult(
          await api.GET("/api/leases/operations/{operation_id}", {
            signal,
            params: { path: { operation_id: operationId } },
          }),
        ).response;
      return readResult(
        await api.GET("/api/inspection-commands/{operation_id}", {
          signal,
          params: { path: { operation_id: operationId } },
        }),
      ).result;
    },
  });
  return (
    <>
      {result.isPending && <p role="status">Loading original committed snapshot…</p>}
      {result.error && (
        <p role="alert">
          The primary result is committed. Its detailed receipt is unavailable:{" "}
          {result.error.message}
        </p>
      )}
      {result.data && (
        <>
          <Facts
            value={result.data}
            fields={["id", "status", "leaseRevision", "revision", "updatedAt", "operationId"]}
          />
          {family === "lease" && "spaceId" in result.data && (
            <Link to={`/leases/${result.data.id}/details`}>
              Open committed Lease and related setup
            </Link>
          )}
          {family === "inspection" && "leaseId" in result.data && (
            <Link to={`/inspections/${result.data.id}`}>Open committed inspection</Link>
          )}
        </>
      )}
    </>
  );
}

async function evidenceMetadata(file: File): Promise<Record<string, unknown>> {
  if (file.size === 0 || file.size > 50 * 1024 * 1024)
    throw new Error("Evidence must contain 1 byte to 50 MiB.");
  const originalName = file.name.normalize("NFC").trim();
  if (
    !originalName ||
    [".", ".."].includes(originalName) ||
    /[/\\\p{Cc}]/u.test(originalName) ||
    new TextEncoder().encode(originalName).length > 255
  )
    throw new Error("Evidence needs a safe display filename of at most 255 UTF-8 bytes.");
  const declaredType = file.type.trim().toLowerCase();
  const mediaType =
    /^[a-z0-9!#$&^_.+-]+\/[a-z0-9!#$&^_.+-]+(?:;[a-z0-9!#$&^_.+-]+=[a-z0-9!#$&^_.+-]+)*$/.test(
      declaredType,
    )
      ? declaredType
      : "application/octet-stream";
  const hash = await crypto.subtle.digest("SHA-256", await file.arrayBuffer());
  return {
    originalName,
    mediaType,
    sizeBytes: file.size,
    contentSha256: Array.from(new Uint8Array(hash), (value) =>
      value.toString(16).padStart(2, "0"),
    ).join(""),
  };
}

function FactsResult({ value }: { value: unknown }) {
  const result = record(value);
  return (
    <p>
      Result record {scalar(result.targetId ?? result.resultId ?? result.id, "see owning receipt")}{" "}
      · Revision {scalar(result.revision ?? result.resultingRevision, "see owning receipt")} ·{" "}
      {scalar(result.status, "committed")}
    </p>
  );
}
