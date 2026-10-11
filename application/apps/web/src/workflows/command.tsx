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
      : "parties";
  return `/${family}?${params}`;
}

function toPayload(definition: Workflow, body: Record<string, unknown>, child?: string) {
  const values = { ...body };
  delete values.idempotencyKey;
  let payload = values;
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
}: {
  definition: Workflow;
  sourceId?: string;
  childId?: string;
  revision: number;
  initial?: Record<string, unknown>;
  choices?: Choices;
  returnTo?: string;
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
}: {
  definition: Workflow;
  sourceId?: string;
  childId?: string;
  revision: number;
  initial: Record<string, unknown>;
  choices: Choices;
  recovered?: Recovery;
  returnTo?: string;
}) {
  const { scope } = useWorkspace();
  const location = useLocation();
  const [id] = useState(() => recovered?.id ?? crypto.randomUUID());
  const [error, setError] = useState<string>();
  const [review, setReview] = useState<{ revision: number; value: unknown }>();
  const [candidates, setCandidates] = useState<string[]>([]);
  const revisionField =
    definition.sourceKind === "property" || definition.formKey === "portfolio.property.create"
      ? "expectedPropertyRevision"
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
    switch (definition.sourceKind) {
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
                : `/${definition.formKey.startsWith("provider.") ? "providers" : "properties"}`));
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
            validateRequest(definition.schema, {
              ...record(clean(definition.schema, values)),
              idempotencyKey: crypto.randomUUID(),
            });
            await controller.submit(dispatch);
          });
        }}
      >
        <fieldset disabled={locked || !scope.canWrite}>
          <legend>Requested change</legend>
          <Fields
            schema={definition.schema}
            value={values}
            onChange={(next) => form.setValue("data", record(next))}
            choices={choices}
            disabled={locked}
          />
        </fieldset>
        {!locked && (
          <>
            <button type="submit" disabled={!scope.canWrite}>
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
                controller.reviewSource(response.data, review.revision, revisionField);
                form.setValue("data", { ...values, [revisionField]: review.revision });
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
        </section>
      )}
      <Link to={back}>Return to current record</Link>
      <RecoveryNavigation controller={controller} blocker={blocker} />
    </section>
  );
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
