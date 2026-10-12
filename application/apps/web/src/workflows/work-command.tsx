import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "@epm/contracts";
import { workflows, record, scalar, type Workflow } from "@epm/contracts/workflows";
import { useWorkspace } from "../app/workspace-gate";
import { CommandLoader } from "./command";
import { Facts, IdentityLookup, readResult } from "./reads";
import { type Choices } from "./fields";
import { loadWorkRecord, workChildren } from "./work-records";
import { workUrl, type WorkKind } from "./work-links";

function sourceKind(definition: Workflow): WorkKind {
  return definition.sourceKind === "task"
    ? "task"
    : definition.sourceKind === "communication"
      ? "communication"
      : definition.sourceKind === "owner_concern"
        ? "concern"
        : "issue";
}
type Source = {
  revision: number;
  value: Record<string, unknown>;
  children: Record<string, unknown>[];
  choices: Choices;
};
async function source(
  definition: Workflow,
  target?: string,
  signal?: AbortSignal,
): Promise<Source> {
  const result: Source = { revision: 0, value: {}, children: [], choices: {} };
  if (definition.sourceKind) {
    if (!target) throw new Error("Select the owning record before this command.");
    result.value = await loadWorkRecord(sourceKind(definition), target, signal);
    result.revision = Number(result.value.revision);
    if (definition.sourceKind === "maintenance_issue") {
      for (const key of ["appointments", "quotes", "assignments", "costContexts", "expenseLinks"])
        result.children.push(...workChildren(result.value, key));
      result.choices.quoteId = workChildren(result.value, "quotes")
        .filter((item) => !item.withdrawnAt)
        .map((item) => ({
          id: scalar(item.id),
          label: `${scalar(item.providerDisplayNameSnapshot)} · ${scalar(item.label)}`,
        }));
      result.choices.assignmentId = workChildren(result.value, "assignments").map((item) => ({
        id: scalar(item.id),
        label: `${scalar(item.providerDisplayNameSnapshot)} · ${item.endedAt ? "Ended" : "Current"}`,
      }));
    }
    if (definition.childKey === "reminderId") {
      result.children = readResult(
        await api.GET("/api/tasks/{task_id}/reminders", {
          signal,
          params: { path: { task_id: target }, query: { limit: 100 } },
        }),
      ).map(record);
    }
  }
  if (["maintenance.issue.create", "owner_concern.create"].includes(definition.formKey)) {
    const properties = readResult(
      await api.GET("/api/properties", {
        signal,
        params: { query: { pageSize: 100, status: "active" } },
      }),
    );
    result.choices.propertyId = properties.items.map((item) => ({
      id: item.id,
      label: item.displayName,
    }));
  }
  if (["maintenance.quote.create", "maintenance.assignment.create"].includes(definition.formKey)) {
    const providers = readResult(
      await api.GET("/api/providers", {
        signal,
        params: { query: { limit: 100, archiveState: "active" } },
      }),
    );
    result.choices.providerPartyId = providers.items.map((item) => ({
      id: item.party.id,
      label: `${item.party.displayName} · ${item.profile.selectionStatus}`,
    }));
  }
  return result;
}
export function WorkCommand() {
  const [params] = useSearchParams();
  const { scope } = useWorkspace();
  const definition = workflows.find((item) => item.formKey === params.get("workflow"));
  const target = params.get("target") ?? undefined,
    child = params.get("child") ?? undefined;
  const [identities, setIdentities] = useState<Choices["partyId"]>([]);
  const resume = params.get("resume");
  const saved = useQuery({
    queryKey: scope.key("workflow-recovery", resume),
    enabled: !!resume,
    queryFn: async ({ signal }) =>
      readResult(
        await api.GET("/api/operator/recovery/{record_id}", {
          signal,
          params: { path: { record_id: resume! } },
        }),
      ),
    retry: false,
  });
  const loaded = useQuery({
    queryKey: scope.key("work-command-source", definition?.formKey, target, child),
    enabled: !!definition,
    queryFn: ({ signal }) => source(definition!, target, signal),
    retry: false,
  });
  if (
    !definition ||
    !["task.", "maintenance.", "communication.", "owner_concern."].some((prefix) =>
      definition.formKey.startsWith(prefix),
    )
  )
    return <p role="alert">Unknown work command.</p>;
  if (loaded.isPending) return <p role="status">Loading command context…</p>;
  const originalOnly =
    !!saved.data &&
    saved.data.formKey === definition.formKey &&
    saved.data.sourceId === (target ?? null) &&
    ["outcome_unknown", "reconciled"].includes(saved.data.status);
  if (loaded.error && resume && saved.isPending)
    return <p role="status">Loading original attempt…</p>;
  if (loaded.error && !originalOnly)
    return <p role="alert">Command context unavailable: {loaded.error.message}</p>;
  const context: Source = loaded.data ?? {
    revision: Number(saved.data?.payload.expectedRevision ?? saved.data?.baseSourceRevision ?? 0),
    value: {},
    choices: {},
    children: [],
  };
  let initial: Record<string, unknown> = {};
  if (
    definition.formKey.endsWith(".patch") ||
    definition.formKey === "task.edit" ||
    definition.formKey === "communication.correct"
  )
    initial = Object.fromEntries(
      Object.keys(definition.schema.properties ?? {})
        .filter(
          (key) =>
            context.value[key] !== undefined &&
            !(context.value[key] === null && definition.schema.required?.includes(key)) &&
            !key.startsWith("expected") &&
            key !== "idempotencyKey",
        )
        .map((key) => [key, context.value[key]]),
    );
  if (definition.formKey === "task.create") initial = { priority: "normal", isAllDay: false };
  if (definition.formKey === "maintenance.issue.create")
    initial = { priority: "normal", reporter: { role: "manager", subjectKind: "local_operator" } };
  if (definition.formKey === "communication.create")
    initial = {
      direction: "inbound",
      channel: "phone",
      record: false,
      links: params.get("entityId")
        ? [{ entityType: params.get("entityType"), entityId: params.get("entityId") }]
        : [],
    };
  if (definition.formKey === "maintenance.appointment.finish") initial.cancelled = false;
  if (definition.formKey === "maintenance.appointment.update") {
    const current = context.children.find((item) => item.id === child);
    if (current)
      initial = Object.fromEntries(
        ["startsAtUtc", "endsAtUtc", "purpose", "instructions"].map((key) => [key, current[key]]),
      );
  }
  const contextualParty = workChildren(context.value, "participants").map((item) => ({
    id: scalar(item.partyId),
    label: scalar(item.partyDisplayName),
  }));
  const choices = {
    ...context.choices,
    ...(identities.length || contextualParty.length
      ? { partyId: [...contextualParty, ...identities], ownerPartyId: identities }
      : {}),
  };
  return (
    <>
      {loaded.error && (
        <p role="alert">
          Current source unavailable. Only the original attempt can be reconciled or replayed; no
          new change can be submitted.
        </p>
      )}
      <p>
        Choices are bounded to the first 100 relevant records. Use an existing contextual identity;
        server validation decides effective relationships and historical-selection eligibility.
      </p>
      <Facts
        value={context.value}
        fields={["summary", "subject", "title", "status", "revision", "priority"]}
      />
      {[
        "communication.create",
        "communication.patch",
        "communication.correct",
        "owner_concern.create",
        "maintenance.issue.create",
        "maintenance.reporter.correct",
      ].includes(definition.formKey) && (
        <IdentityLookup
          onSelect={(id, displayName) =>
            setIdentities((current) => [
              ...current.filter((item) => item.id !== id),
              { id, label: displayName },
            ])
          }
        />
      )}
      <CommandLoader
        definition={definition}
        sourceId={target}
        childId={child}
        revision={context.revision}
        initial={initial}
        choices={choices}
        returnTo={
          target
            ? workUrl(sourceKind(definition), target)
            : definition.formKey.startsWith("task.")
              ? "/tasks"
              : definition.formKey.startsWith("communication.")
                ? "/conversations"
                : "/maintenance"
        }
        reviewSource={
          definition.sourceKind
            ? async () => {
                const latest = await source(definition, target);
                return { revision: latest.revision, value: latest.value };
              }
            : undefined
        }
        checkSource={async (values) => {
          const selectedChild = definition.childKey
            ? scalar(values[definition.childKey], child)
            : undefined;
          if (selectedChild) {
            const latest = await source(definition, target);
            if (!latest.children.some((item) => item.id === selectedChild))
              throw new Error(
                "The child record does not belong to this source, or lies beyond the bounded selection. Review it before submission.",
              );
          }
          if (
            definition.formKey === "maintenance.appointment.finish" &&
            values.cancelled === true &&
            !scalar(values.reason).trim()
          )
            throw new Error("Cancellation requires a reason.");
        }}
      />
      <Link to="/settings/recovery">Unfinished forms</Link>
    </>
  );
}
