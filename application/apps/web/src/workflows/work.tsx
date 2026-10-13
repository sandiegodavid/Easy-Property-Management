import { useQuery } from "@tanstack/react-query";
import { MaintenanceFilters } from "./maintenance-context";
import { MaintenanceEvidenceArchive } from "./maintenance-evidence";
import { useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { api } from "@epm/contracts";
import { AttentionQueue, AttentionSection, type AttentionItem } from "@epm/ui";
import type { components } from "@epm/contracts/generated";
import { record, scalar, workflows } from "@epm/contracts/workflows";
import { useWorkspace } from "../app/workspace-gate";
import { CommandLinks, CommandLoader } from "./command";
import { TaskCompletion, TaskOutcome } from "./task-controls";
import { readResult } from "./reads";
import { WorkCommand } from "./work-command";
import { WorkRecord } from "./work-records";
import { workUrl, type WorkKind } from "./work-links";
import { IntakeWorkspace } from "./intake";

export function WorkWorkspace({ kind = "issue" }: { kind?: WorkKind }) {
  const [params] = useSearchParams();
  const path = useParams();
  if (params.get("workflow") === "file.link.archive")
    return <MaintenanceEvidenceArchive key={params.toString()} />;
  if (params.get("intake") === "true" || params.get("workflow")?.startsWith("intake."))
    return <IntakeWorkspace />;
  if (params.has("workflow")) return <WorkCommand key={params.toString()} />;
  const selected = params.get("record") as WorkKind | null;
  if (selected && !["issue", "task", "communication", "concern"].includes(selected))
    return <p role="alert">Unknown work record kind.</p>;
  const id = params.get("id") ?? path.id;
  if (id) return <WorkRecord kind={selected ?? kind} id={id} />;
  const tab = params.get("tab");
  const current = tab === "concerns" ? "concern" : tab === "conversations" ? "communication" : kind;
  return (
    <section aria-label="Work workspace">
      <h2>
        {current === "task"
          ? "Tasks"
          : current === "communication"
            ? "Conversations"
            : "Maintenance and owner concerns"}
      </h2>
      <p>
        Recording a conversation does not send a message. Completing a Task or appointment does not
        resolve an issue or verify physical work.
      </p>
      <nav aria-label="Work views">
        <Link to="/maintenance">Issues</Link>{" "}
        <Link to="/maintenance?tab=concerns">Owner concerns</Link>{" "}
        <Link to="/conversations">Conversations</Link>{" "}
        <Link to="/conversations?intake=true">Retained source evidence</Link>{" "}
        <Link to="/tasks">Tasks</Link>
      </nav>
      {current === "task" && (
        <>
          <TaskQuickAdd />
          <TaskSummary />
        </>
      )}
      <WorkDirectory key={current} kind={current} />
    </section>
  );
}

function WorkDirectory({ kind }: { kind: WorkKind }) {
  const { scope } = useWorkspace();
  const [params, setParams] = useSearchParams();
  const status = params.get("status") ?? undefined;
  const cursor = params.get("cursor") ?? undefined;
  const propertyId = params.get("propertyId") ?? undefined;
  const entityType = params.get("entityType") ?? undefined;
  const entityId = params.get("entityId") ?? undefined;
  const follow = kind === "task" && params.get("followUps") === "true";
  const priority = params.get("priority") ?? undefined;
  const due = params.get("due") ?? undefined;
  const result = useQuery({
    queryKey: scope.key("work-directory", kind, params.toString()),
    retry: false,
    queryFn: async ({ signal }) => {
      switch (kind) {
        case "issue":
          return readResult(
            await api.GET("/api/maintenance-issues", {
              signal,
              params: {
                query: {
                  propertyId,
                  cursor,
                  pageSize: 25,
                  status: status as "open" | "in_progress" | "resolved" | "cancelled" | undefined,
                  spaceId: params.get("spaceId") ?? undefined,
                  reporterRole:
                    (params.get("reporterRole") as
                      "owner" | "tenant" | "manager" | "staff" | undefined) || undefined,
                  reporterSubjectKind:
                    (params.get("reporterSubjectKind") as "party" | "local_operator" | undefined) ||
                    undefined,
                  reporterPartyId: params.get("reporterPartyId") ?? undefined,
                  category:
                    (params.get("category") as components["schemas"]["IssueInput"]["category"]) ||
                    undefined,
                  priority: priority as "low" | "normal" | "high" | "urgent" | undefined,
                  reportedFrom: params.get("reportedFrom") ?? undefined,
                  reportedTo: params.get("reportedTo") ?? undefined,
                  appointmentFrom: params.get("appointmentFrom") ?? undefined,
                  appointmentTo: params.get("appointmentTo") ?? undefined,
                  hasEvidence: params.has("hasEvidence")
                    ? params.get("hasEvidence") === "true"
                    : undefined,
                  hasLinkedExpense: params.has("hasLinkedExpense")
                    ? params.get("hasLinkedExpense") === "true"
                    : undefined,
                  hasActiveTask: params.has("hasActiveTask")
                    ? params.get("hasActiveTask") === "true"
                    : undefined,
                },
              },
            }),
          );
        case "concern":
          return readResult(
            await api.GET("/api/owner-concerns", {
              signal,
              params: {
                query: {
                  propertyId,
                  ownerPartyId: params.get("ownerId") ?? undefined,
                  spaceId: params.get("spaceId") ?? undefined,
                  leaseId: params.get("leaseId") ?? undefined,
                  tenantPartyId: params.get("tenantPartyId") ?? undefined,
                  concernType:
                    (params.get("concernType") as
                      "general_rental" | "lease" | "tenant" | "vacancy" | undefined) || undefined,
                  priority:
                    (params.get("priority") as "low" | "normal" | "high" | "urgent" | undefined) ||
                    undefined,
                  raisedLocalOnOrAfter: params.get("raisedLocalOnOrAfter") ?? undefined,
                  raisedLocalOnOrBefore: params.get("raisedLocalOnOrBefore") ?? undefined,
                  cursor,
                  pageSize: 25,
                  status: status as "open" | "in_progress" | "resolved" | "dismissed" | undefined,
                },
              },
            }),
          );
        case "communication":
          return readResult(
            await api.GET("/api/communications", {
              signal,
              params: {
                query: {
                  propertyId,
                  entityType,
                  entityId,
                  cursor,
                  pageSize: 25,
                  status: status as "draft" | "recorded" | "superseded" | undefined,
                  partyId: params.get("partyId") ?? undefined,
                  spaceId: params.get("spaceId") ?? undefined,
                  leaseId: params.get("leaseId") ?? undefined,
                  direction:
                    (params.get("direction") as "inbound" | "outbound" | "internal" | undefined) ||
                    undefined,
                  channel:
                    (params.get("channel") as
                      "phone" | "email" | "sms" | "in_person" | "letter" | "other" | undefined) ||
                    undefined,
                  occurredOnOrAfter: params.get("occurredOnOrAfter") ?? undefined,
                  occurredOnOrBefore: params.get("occurredOnOrBefore") ?? undefined,
                  linkedTaskStatus:
                    (params.get("linkedTaskStatus") as
                      "open" | "in_progress" | "completed" | "cancelled" | undefined) || undefined,
                },
              },
            }),
          );
        case "task":
          return follow
            ? readResult(
                await api.GET("/api/tasks/follow-ups", {
                  signal,
                  params: {
                    query: {
                      limit: 25,
                      cursor,
                      priority: priority as "low" | "normal" | "high" | "urgent" | undefined,
                      relatedEntityType: entityType,
                      relatedEntityId: entityId,
                      state:
                        (params.get("state") as
                          "scheduled" | "due" | "overdue" | "unscheduled" | undefined) || undefined,
                    },
                  },
                }),
              )
            : readResult(
                await api.GET("/api/tasks", {
                  signal,
                  params: {
                    query: {
                      pageSize: 25,
                      cursor,
                      status,
                      priority,
                      due,
                      includeVoided: true,
                      relatedEntityType: entityType,
                      relatedEntityId: entityId,
                    },
                  },
                }),
              );
      }
    },
  });
  const statuses =
    kind === "communication"
      ? ["draft", "recorded", "superseded"]
      : [
          "open",
          "in_progress",
          kind === "task" ? "completed" : "resolved",
          kind === "concern" ? "dismissed" : "cancelled",
        ];
  return (
    <section aria-label="Work directory">
      <CommandLinks
        keys={[
          kind === "issue"
            ? "maintenance.issue.create"
            : kind === "concern"
              ? "owner_concern.create"
              : kind === "communication"
                ? "communication.create"
                : "task.create",
        ]}
      />
      <form
        onSubmit={(event) => {
          event.preventDefault();
          const data = new FormData(event.currentTarget);
          const next = new URLSearchParams(params);
          next.delete("cursor");
          for (const key of [
            "status",
            "propertyId",
            "ownerId",
            "entityType",
            "entityId",
            "state",
            "followUps",
            "priority",
            "due",
            "partyId",
            "spaceId",
            "leaseId",
            "tenantPartyId",
            "concernType",
            "raisedLocalOnOrAfter",
            "raisedLocalOnOrBefore",
            "direction",
            "channel",
            "occurredOnOrAfter",
            "occurredOnOrBefore",
            "linkedTaskStatus",
            "category",
            "reporterRole",
            "reporterSubjectKind",
            "reporterPartyId",
            "reportedFrom",
            "reportedTo",
            "appointmentFrom",
            "appointmentTo",
            "hasEvidence",
            "hasLinkedExpense",
            "hasActiveTask",
          ]) {
            const raw = data.get(key);
            const value = typeof raw === "string" ? raw : "";
            if (value) next.set(key, value);
            else next.delete(key);
          }
          setParams(next);
        }}
      >
        <label>
          Status
          <select name="status" defaultValue={status ?? ""}>
            <option value="">All statuses</option>
            {statuses.map((item) => (
              <option key={item}>{item}</option>
            ))}
          </select>
        </label>
        {kind !== "task" && (
          <label>
            Property ID
            <input name="propertyId" defaultValue={propertyId} />
          </label>
        )}
        {kind === "concern" && (
          <>
            <label>
              Owner identity ID
              <input name="ownerId" defaultValue={params.get("ownerId") ?? ""} />
            </label>
            <label>
              Concern type
              <select name="concernType" defaultValue={params.get("concernType") ?? ""}>
                <option value="">Any</option>
                {["general_rental", "lease", "tenant", "vacancy"].map((type) => (
                  <option key={type}>{type}</option>
                ))}
              </select>
            </label>
            {[
              ["spaceId", "Concern Space ID"],
              ["leaseId", "Concern Lease ID"],
              ["tenantPartyId", "Concern Tenant ID"],
            ].map(([key, label]) => (
              <label key={key}>
                {label}
                <input name={key} defaultValue={params.get(key) ?? ""} />
              </label>
            ))}
            <label>
              Raised local from
              <input
                type="date"
                name="raisedLocalOnOrAfter"
                defaultValue={params.get("raisedLocalOnOrAfter") ?? ""}
              />
            </label>
            <label>
              Raised local through
              <input
                type="date"
                name="raisedLocalOnOrBefore"
                defaultValue={params.get("raisedLocalOnOrBefore") ?? ""}
              />
            </label>
          </>
        )}
        {kind === "issue" && <MaintenanceFilters />}
        {(kind === "communication" || kind === "task") && (
          <>
            <label>
              Related entity type
              <input name="entityType" defaultValue={entityType} />
            </label>
            <label>
              Related entity ID
              <input name="entityId" defaultValue={entityId} />
            </label>
          </>
        )}
        {kind === "communication" && (
          <>
            {[
              ["direction", "Direction", ["inbound", "outbound", "internal"]],
              ["channel", "Channel", ["phone", "email", "sms", "in_person", "letter", "other"]],
              [
                "linkedTaskStatus",
                "Follow-up Task status",
                ["open", "in_progress", "completed", "cancelled"],
              ],
            ].map(([key, title, options]) => (
              <label key={key as string}>
                {title}
                <select name={key as string} defaultValue={params.get(key as string) ?? ""}>
                  <option value="">Any</option>
                  {(options as string[]).map((option) => (
                    <option key={option} value={option}>
                      {option.replaceAll("_", " ")}
                    </option>
                  ))}
                </select>
              </label>
            ))}
            {[
              ["partyId", "Participant Party ID"],
              ["spaceId", "Space ID"],
              ["leaseId", "Lease ID"],
            ].map(([key, title]) => (
              <label key={key}>
                {title}
                <input name={key} maxLength={36} defaultValue={params.get(key) ?? ""} />
              </label>
            ))}
            <label>
              Occurred from (stored local date)
              <input
                type="date"
                name="occurredOnOrAfter"
                defaultValue={params.get("occurredOnOrAfter") ?? ""}
              />
            </label>
            <label>
              Occurred to (stored local date)
              <input
                type="date"
                name="occurredOnOrBefore"
                defaultValue={params.get("occurredOnOrBefore") ?? ""}
              />
            </label>
          </>
        )}
        {kind === "task" && (
          <>
            <label>
              Priority
              <select name="priority" defaultValue={priority ?? ""}>
                <option value="">All priorities</option>
                {["low", "normal", "high", "urgent"].map((item) => (
                  <option key={item}>{item}</option>
                ))}
              </select>
            </label>
            <label>
              Due period
              <select name="due" defaultValue={due ?? ""} disabled={follow}>
                <option value="">All due dates</option>
                <option value="overdue">Overdue</option>
                <option value="today">Today</option>
                <option value="next7days">Next 7 days</option>
                <option value="nodate">No due date</option>
              </select>
            </label>
            <label>
              <input type="checkbox" name="followUps" value="true" defaultChecked={follow} />
              Waiting follow-ups
            </label>
            <label>
              Follow-up state
              <select name="state" defaultValue={params.get("state") ?? ""}>
                <option value="">All follow-ups</option>
                {["scheduled", "due", "overdue", "unscheduled"].map((item) => (
                  <option key={item}>{item}</option>
                ))}
              </select>
            </label>
          </>
        )}
        <button>Apply work filters</button>
      </form>
      {result.isPending && <p role="status">Loading work records…</p>}
      {result.error && <p role="alert">Records unavailable: {result.error.message}</p>}
      {result.data && (
        <>
          {"matchingTotal" in result.data && (
            <p>{String(result.data.matchingTotal)} matching follow-ups</p>
          )}
          {"asOf" in result.data && <p>As of {String(result.data.asOf)}</p>}
          {result.data.items.length === 0 && (
            <p>
              No matching recorded items on this page. This does not establish that no problems
              exist.
            </p>
          )}
          {follow && "asOf" in result.data && "matchingTotal" in result.data ? (
            <AttentionQueue
              kind="waiting"
              asOf={String(result.data.asOf)}
              total={Number(result.data.matchingTotal)}
              emptyMessage="No matching recorded follow-ups."
              items={result.data.items.map((item) => ({
                sourceKey: `task:${item.id}`,
                title: scalar(record(item).title),
                status: scalar(record(item).followUpState),
                summary: `Waiting for ${scalar(record(item).waitingForLabel)} · ${scalar(record(item).taskDeadlineState)}`,
                renderDetails: () => (
                  <>
                    <p>Follow-up: {scalar(record(item).followUpAt) || "Not scheduled"}</p>
                    <p>
                      Task deadline: {scalar(record(item).dueAtUtc) || "Not recorded"} ·{" "}
                      {scalar(record(item).dueTimezone) || "No deadline zone"}
                    </p>
                    <p>Priority: {scalar(record(item).priority)}</p>
                    <p>Waiting does not resolve the original source or change its deadline.</p>
                    <Link to={workUrl("task", item.id)}>Review Task and follow-up</Link>
                  </>
                ),
              }))}
            />
          ) : (
            <ul>
              {result.data.items.map((item) => (
                <li key={item.id}>
                  <Link to={workUrl(kind, item.id)}>
                    {scalar(record(item).summary ?? record(item).subject ?? record(item).title)}
                  </Link>{" "}
                  · {item.status}
                  {"priority" in item && ` · ${item.priority}`}
                  {kind === "issue" && (
                    <p>
                      Reported by {scalar(record(record(item).reporter).displayName)} ·{" "}
                      {scalar(record(record(item).reporter).role)} (
                      {scalar(record(record(item).reporter).subjectKind).replaceAll("_", " ")}) —
                      retained attribution, not current relationship eligibility.
                    </p>
                  )}
                  {kind === "task" && (
                    <>
                      <TaskOutcome value={record(item)} />
                      {["open", "in_progress"].includes(item.status) && (
                        <details>
                          <summary>Task details and completion</summary>
                          <p>
                            Task deadline: {scalar(record(item).dueAtUtc) || "No due date"} ·{" "}
                            {scalar(record(item).dueTimezone)}
                          </p>
                          <TaskCompletion value={record(item)} />
                        </details>
                      )}
                    </>
                  )}
                </li>
              ))}
            </ul>
          )}
          {result.data.nextCursor && (
            <button
              onClick={() => {
                const next = new URLSearchParams(params);
                next.set("cursor", result.data.nextCursor!);
                setParams(next);
              }}
            >
              Next work page
            </button>
          )}
          {cursor && (
            <button
              onClick={() => {
                const next = new URLSearchParams(params);
                next.delete("cursor");
                setParams(next);
              }}
            >
              First work page
            </button>
          )}
        </>
      )}
    </section>
  );
}

function TaskQuickAdd() {
  const [opened, setOpened] = useState(false);
  const definition = workflows.find((item) => item.formKey === "task.create")!;
  if (!opened)
    return (
      <button type="button" onClick={() => setOpened(true)}>
        Quick add task
      </button>
    );
  return (
    <section aria-label="Quick add task">
      <CommandLoader
        definition={definition}
        revision={0}
        initial={{ priority: "normal", isAllDay: false }}
        returnTo="/tasks"
      />
    </section>
  );
}

function TaskSummary() {
  const { scope } = useWorkspace();
  const result = useQuery({
    queryKey: scope.key("task-work-summary"),
    queryFn: async ({ signal }) =>
      readResult(
        await api.GET("/api/tasks/summary", { signal, params: { query: { limitPerBucket: 10 } } }),
      ),
  });
  return (
    <section aria-label="Task deadlines and reminders">
      <h3>Deadlines and reminders</h3>
      {result.isPending && <p role="status">Loading deadline summary…</p>}
      {result.error && <p role="alert">Deadline summary unavailable: {result.error.message}</p>}
      {result.data && (
        <>
          <p>As of {result.data.asOf}</p>
          {(["overdue", "today", "next7days"] as const).map((key) => (
            <AttentionSection
              key={key}
              title={
                key === "next7days"
                  ? "Upcoming Task deadlines"
                  : key === "overdue"
                    ? "Overdue Tasks"
                    : "Tasks due today"
              }
              total={result.data[`${key}Total`]}
              asOf={result.data.asOf}
              emptyMessage="No matching Task deadlines in this response."
              items={result.data[key].map(taskAttentionItem)}
            />
          ))}
          <h4>Due reminders · {result.data.dueRemindersTotal}</h4>
          {result.data.dueReminders.map((item) => (
            <p key={item.id}>
              <Link to={workUrl("task", item.taskId)}>{item.taskTitle}</Link> · {item.remindAtUtc}
            </p>
          ))}
        </>
      )}
    </section>
  );
}

function taskAttentionItem(item: components["schemas"]["TaskResponse"]): AttentionItem {
  return {
    sourceKey: `task:${item.id}`,
    title: item.title,
    summary: `${item.priority}${item.isWaiting ? ` · Waiting for ${item.waitingForLabel}` : ""}`,
    status: item.status,
    renderDetails: () => (
      <>
        <p>
          Task deadline: {item.dueAtUtc ?? "Not scheduled"} · {item.dueTimezone ?? "No time zone"}
        </p>
        <p>Completing this Task does not resolve its related issue or verify physical work.</p>
        <TaskCompletion value={item} />
        <Link to={workUrl("task", item.id)}>Review Task and actions</Link>
      </>
    ),
  };
}
