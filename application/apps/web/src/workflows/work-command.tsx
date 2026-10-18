import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useLocation, useSearchParams } from "react-router-dom";
import { ParentBackLink, SourceWorkflowLink as Link } from "../shared/home-navigation";
import { api } from "@epm/contracts";
import { workflows, record, scalar, type Workflow } from "@epm/contracts/workflows";
import { useWorkspace } from "../app/workspace-gate";
import { CommandLoader } from "./command";
import { Facts, IdentityLookup, readResult } from "./reads";
import { type Choices } from "./fields";
import { loadWorkRecord, workChildren } from "./work-records";
import { workUrl, type WorkKind } from "./work-links";
import { CommunicationContext } from "./communication-context";
import { MaintenanceContext } from "./maintenance-context";
import { ReporterContext, reporterProblem } from "./reporter-context";
import { QuoteCommandContext, assignmentProblem, quoteProblem } from "./quote-context";
import { JournalCommandContext, journalProblem } from "./work-journal";
import { ConcernContext, concernProblem } from "./concern-context";
import type { components } from "@epm/contracts/generated";

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
  properties?: components["schemas"]["app__modules__portfolio__api__router__PropertyResponse"][];
};
async function source(
  definition: Workflow,
  target?: string,
  signal?: AbortSignal,
  journalCursor?: string,
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
      if (definition.formKey === "maintenance.journal.record") {
        const page = readResult(
          await api.GET("/api/maintenance-issues/{issue_id}/work-journal", {
            signal,
            params: { path: { issue_id: target }, query: { pageSize: 20, cursor: journalCursor } },
          }),
        );
        result.children.push(...page.items.map(record));
        result.choices.correctsEntryId = page.items
          .filter((item) => item.isEffective)
          .map((item) => ({
            id: item.id,
            label: `${item.effectiveKind} · ${item.summary}`,
          }));
      }
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
        params: {
          query: {
            pageSize: 100,
            status: definition.formKey === "owner_concern.create" ? undefined : "active",
          },
        },
      }),
    );
    result.choices.propertyId = properties.items.map((item) => ({
      id: item.id,
      label: `${item.displayName}${item.status === "archived" ? " · Archived — historical selection required" : ""}`,
    }));
    result.properties = properties.items;
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
  if (definition.formKey === "maintenance.expense.link") {
    const expenses = readResult(
      await api.GET("/api/expenses", {
        signal,
        params: { query: { propertyId: scalar(result.value.propertyId), pageSize: 100 } },
      }),
    );
    result.choices.expenseId = expenses.items
      .filter((item) => !item.voidedAt)
      .map((item) => ({
        id: item.id,
        label: `${item.paidOn} · USD ${item.amount} · ${item.payeeName}`,
      }));
  }
  return result;
}
export function WorkCommand() {
  const [params] = useSearchParams();
  const location = useLocation();
  const { scope } = useWorkspace();
  const definition = workflows.find((item) => item.formKey === params.get("workflow"));
  const target = params.get("target") ?? undefined,
    child = params.get("child") ?? undefined;
  const [identities, setIdentities] = useState<Choices["partyId"]>([]);
  const resume = params.get("resume");
  const priorConcern = useQuery({
    queryKey: scope.key("concern-replacement-command-source", params.get("replacesConcernId")),
    enabled:
      definition?.formKey === "owner_concern.create" && params.has("replacesConcernId") && !resume,
    staleTime: Infinity,
    refetchOnWindowFocus: false,
    queryFn: async ({ signal }) => {
      const prior = await loadWorkRecord("concern", params.get("replacesConcernId")!, signal);
      if (prior.status !== "dismissed" || record(prior.successor).id)
        throw new Error("Select a dismissed concern without a replacement.");
      return prior;
    },
  });
  const communicationIssue = useQuery({
    queryKey: scope.key("communication-issue-reporter", params.get("entityId")),
    enabled:
      definition?.formKey === "communication.create" &&
      params.get("entityType") === "maintenance_issue" &&
      !!params.get("entityId") &&
      !resume,
    queryFn: async ({ signal }) =>
      readResult(
        await api.GET("/api/maintenance-issues/{issue_id}", {
          signal,
          params: { path: { issue_id: params.get("entityId")! } },
        }),
      ),
  });
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
    queryKey: scope.key(
      "work-command-source",
      definition?.formKey,
      target,
      child,
      params.get("journalCursor"),
    ),
    enabled: !!definition,
    queryFn: ({ signal }) =>
      source(definition!, target, signal, params.get("journalCursor") ?? undefined),
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
  if (priorConcern.isEnabled && priorConcern.isPending)
    return <p role="status">Loading retained concern context…</p>;
  if (priorConcern.error) return <p role="alert">{priorConcern.error.message}</p>;
  if (communicationIssue.isEnabled && communicationIssue.isPending)
    return <p role="status">Loading issue reporter context…</p>;
  if (communicationIssue.error)
    return <p role="alert">Issue context unavailable: {communicationIssue.error.message}</p>;
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
    (context.value.isWaiting === true &&
      ["task.waiting.set", "task.waiting.reschedule"].includes(definition.formKey)) ||
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
  if (definition.formKey === "owner_concern.create") {
    initial.priority = "normal";
    if (params.get("independentReview") === "true" && !resume) {
      const retained = record(record(location.state).concernReview);
      for (const key of [
        "ownerPartyId",
        "propertyId",
        "spaceId",
        "leaseId",
        "tenantPartyId",
        "concernType",
        "summary",
        "description",
        "priority",
        "raisedAtUtc",
        "historicalSelectionConfirmed",
        "historicalSelectionReason",
      ])
        if (retained[key] !== undefined) initial[key] = retained[key];
      initial.duplicateConfirmed = false;
    }
    if (priorConcern.data) {
      for (const key of [
        "ownerPartyId",
        "propertyId",
        "spaceId",
        "leaseId",
        "tenantPartyId",
        "concernType",
        "summary",
        "description",
        "priority",
        "raisedAtUtc",
      ])
        initial[key] = priorConcern.data[key] ?? undefined;
      initial.replacesConcernId = priorConcern.data.id;
    }
  }
  if (definition.formKey === "maintenance.reporter.correct") {
    const reporter = record(context.value.reporter);
    initial.reporter = {
      role: reporter.role,
      subjectKind: reporter.subjectKind,
      ...(reporter.partyId ? { partyId: reporter.partyId } : {}),
    };
  }
  if (definition.formKey === "communication.create")
    initial = {
      direction: "inbound",
      channel: "phone",
      record: false,
      participants:
        communicationIssue.data?.reporter.subjectKind === "party" &&
        communicationIssue.data.reporter.partyId
          ? [{ partyId: communicationIssue.data.reporter.partyId, role: "reporter" }]
          : [],
      links: params.get("entityId")
        ? [{ entityType: params.get("entityType"), entityId: params.get("entityId") }]
        : [],
    };
  if (definition.formKey === "maintenance.appointment.finish") initial.cancelled = false;
  if (definition.formKey === "maintenance.journal.record") {
    initial = { entryKind: "general_note", sourceKind: "operator_observation" };
    if (params.has("correctsEntryId")) {
      const previous = context.children.find((item) => item.id === params.get("correctsEntryId"));
      if (!originalOnly && !previous?.isEffective)
        return <p role="alert">Select an effective entry from this journal page for correction.</p>;
      if (previous) {
        for (const key of [
          "assignmentId",
          "sourceKind",
          "occurredAtUtc",
          "summary",
          "detail",
          "outcomeStatus",
          "outcomeSummary",
          "followUpRequired",
          "operatorVerified",
        ])
          initial[key] = previous[key] ?? undefined;
        initial.entryKind = "correction";
        initial.correctsEntryId = previous.id;
        initial.correctedEntryKind = previous.effectiveKind;
      }
    }
  }
  if (definition.formKey === "maintenance.cost.create" && params.has("replacesCostContextId")) {
    const previous = context.children.find(
      (item) => item.id === params.get("replacesCostContextId"),
    );
    if (!previous?.voidedAt)
      return <p role="alert">Select a voided cost context from this issue.</p>;
    for (const key of ["contextKind", "label", "observedOn", "sourceNote"])
      initial[key] = previous[key] ?? undefined;
    initial.replacesCostContextId = previous.id;
  }
  if (definition.formKey === "maintenance.quote.create" && params.has("replacesQuoteId")) {
    const previous = context.children.find((item) => item.id === params.get("replacesQuoteId"));
    if (!previous?.withdrawnAt)
      return <p role="alert">Select a withdrawn quote from this issue for replacement.</p>;
    for (const key of [
      "providerPartyId",
      "label",
      "scopeSummary",
      "receivedOn",
      "validThrough",
      "earliestWorkStartOn",
      "estimatedWorkFinishOn",
      "termsNotes",
    ])
      initial[key] = previous[key] ?? undefined;
    initial.replacesQuoteId = previous.id;
  }
  if (definition.formKey === "maintenance.assignment.create") {
    for (const key of ["quoteId", "providerPartyId"])
      if (params.get(key)) initial[key] = params.get(key);
    if (params.has("replacesAssignmentId")) {
      const previous = context.children.find(
        (item) => item.id === params.get("replacesAssignmentId"),
      );
      if (!previous || previous.endedAt)
        return <p role="alert">Select the current assignment from this issue for reassignment.</p>;
      initial.replacesAssignmentId = previous.id;
    }
  }
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
  const parentTarget = target
    ? workUrl(sourceKind(definition), target)
    : definition.formKey.startsWith("task.")
      ? "/tasks"
      : definition.formKey.startsWith("communication.")
        ? "/conversations"
        : "/maintenance";
  const choices = {
    ...context.choices,
    ...(identities.length || contextualParty.length
      ? { partyId: [...contextualParty, ...identities], ownerPartyId: identities }
      : {}),
  };
  return (
    <>
      <ParentBackLink to={parentTarget} />
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
        showParentLink={false}
        definition={definition}
        sourceId={target}
        childId={child}
        revision={context.revision}
        initial={initial}
        choices={choices}
        canSubmit={(values) =>
          definition.formKey === "owner_concern.create"
            ? !concernProblem(values)
            : definition.formKey === "maintenance.journal.record"
              ? !journalProblem(
                  values,
                  ["resolved", "cancelled"].includes(scalar(context.value.status)),
                )
              : definition.formKey === "maintenance.quote.create"
                ? !quoteProblem(values)
                : !["maintenance.issue.create", "maintenance.reporter.correct"].includes(
                    definition.formKey,
                  ) || !reporterProblem(values)
        }
        choicesForValues={(values) =>
          definition.formKey === "maintenance.assignment.create"
            ? {
                ...choices,
                quoteId: context.children
                  .filter(
                    (item) =>
                      item.providerPartyId === values.providerPartyId &&
                      "scopeSummary" in item &&
                      !item.withdrawnAt,
                  )
                  .map((item) => ({
                    id: scalar(item.id),
                    label: `${scalar(item.providerDisplayNameSnapshot)} · ${scalar(item.label)}`,
                  })),
              }
            : context.properties
              ? {
                  ...choices,
                  spaceId:
                    context.properties
                      .find((property) => property.id === values.propertyId)
                      ?.spaces.filter(
                        (space) =>
                          definition.formKey === "owner_concern.create" ||
                          space.status === "active",
                      )
                      .map((space) => ({
                        id: space.id,
                        label: `${space.displayName}${space.status === "archived" ? " · Archived — historical selection required" : ""}`,
                      })) ?? [],
                }
              : choices
        }
        renderContext={(values, locked, onChange) =>
          definition.formKey.startsWith("communication.") ? (
            <CommunicationContext
              values={values}
              locked={locked}
              onChange={onChange}
              source={context.value}
            />
          ) : definition.formKey.startsWith("maintenance.") ? (
            <>
              <MaintenanceContext
                formKey={definition.formKey}
                values={values}
                source={context.value}
              />
              {definition.formKey === "maintenance.journal.record" && (
                <JournalCommandContext
                  values={values}
                  terminal={["resolved", "cancelled"].includes(scalar(context.value.status))}
                />
              )}
              {["maintenance.quote.create", "maintenance.assignment.create"].includes(
                definition.formKey,
              ) && <QuoteCommandContext values={values} source={context.value} />}
              {["maintenance.issue.create", "maintenance.reporter.correct"].includes(
                definition.formKey,
              ) && (
                <ReporterContext
                  values={values}
                  source={context.value}
                  locked={locked}
                  onChange={onChange}
                />
              )}
            </>
          ) : definition.formKey.startsWith("owner_concern.") ? (
            <ConcernContext values={values} source={context.value} />
          ) : null
        }
        returnTo={parentTarget}
        reviewSource={
          definition.sourceKind
            ? async () => {
                const latest = await source(definition, target);
                return { revision: latest.revision, value: latest.value };
              }
            : undefined
        }
        checkSource={async (values) => {
          if (definition.formKey === "owner_concern.create") {
            const problem = concernProblem(values);
            if (problem) throw new Error(problem);
          }
          if (definition.formKey === "maintenance.journal.record") {
            const problem = journalProblem(
              values,
              ["resolved", "cancelled"].includes(scalar(context.value.status)),
            );
            if (problem) throw new Error(problem);
            if (values.correctsEntryId) {
              const latest = await source(
                definition,
                target,
                undefined,
                params.get("journalCursor") ?? undefined,
              );
              if (
                !latest.children.some(
                  (item) => item.id === values.correctsEntryId && item.isEffective,
                )
              )
                throw new Error(
                  "Correction target is not effective on this issue's bounded journal page.",
                );
            }
          }
          if (definition.formKey === "maintenance.quote.create") {
            const problem = quoteProblem(values);
            if (problem) throw new Error(problem);
          }
          if (definition.formKey === "maintenance.assignment.create") {
            const problem = assignmentProblem(values);
            if (problem) throw new Error(problem);
            const quote = context.children.find((item) => item.id === values.quoteId);
            if (values.quoteId && (!quote || quote.providerPartyId !== values.providerPartyId))
              throw new Error("Select a quote from this issue and Provider.");
          }
          if (
            ["maintenance.issue.create", "maintenance.reporter.correct"].includes(
              definition.formKey,
            )
          ) {
            const problem = reporterProblem(values);
            if (problem) throw new Error(problem);
          }
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
