import { useQuery } from "@tanstack/react-query";
import { CoverageLinks } from "../shared/coverage";
import { Link } from "react-router-dom";
import { communicationLocalTime } from "./communication-context";
import { MoneyFacts } from "./money-presentation";
import { QuoteComparison } from "./quote-context";
import { WorkJournal } from "./work-journal";
import { api } from "@epm/contracts";
import { record, scalar } from "@epm/contracts/workflows";
import { useWorkspace } from "../app/workspace-gate";
import { CommandLinks, workflowUrl } from "./command";
import { Facts, History, readResult } from "./reads";
import { TaskOutcome } from "./task-controls";

import { workUrl, type WorkKind } from "./work-links";
export async function loadWorkRecord(
  kind: WorkKind,
  id: string,
  signal?: AbortSignal,
): Promise<Record<string, unknown>> {
  switch (kind) {
    case "issue":
      return record(
        readResult(
          await api.GET("/api/maintenance-issues/{issue_id}", {
            signal,
            params: { path: { issue_id: id } },
          }),
        ),
      );
    case "communication":
      return record(
        readResult(
          await api.GET("/api/communications/{communication_id}", {
            signal,
            params: { path: { communication_id: id } },
          }),
        ),
      );
    case "task":
      return record(
        readResult(
          await api.GET("/api/tasks/{task_id}", { signal, params: { path: { task_id: id } } }),
        ),
      );
    case "concern":
      return record(
        readResult(
          await api.GET("/api/owner-concerns/{concern_id}", {
            signal,
            params: { path: { concern_id: id } },
          }),
        ),
      );
  }
}
export function workChildren(value: Record<string, unknown>, key: string) {
  return Array.isArray(value[key]) ? (value[key] as unknown[]).map(record) : [];
}
const common = [
  "status",
  "priority",
  "revision",
  "summary",
  "description",
  "createdAt",
  "updatedAt",
  "updatedAtUtc",
];
export function WorkRecord({ kind, id }: { kind: WorkKind; id: string }) {
  const { scope } = useWorkspace();
  const result = useQuery({
    queryKey: scope.key("work-record", kind, id),
    retry: false,
    queryFn: ({ signal }) => loadWorkRecord(kind, id, signal),
  });
  const value = result.data;
  const active = value && ["open", "in_progress"].includes(scalar(value.status));
  return (
    <section aria-label="Work record">
      <Link
        to={
          kind === "task" ? "/tasks" : kind === "communication" ? "/conversations" : "/maintenance"
        }
      >
        Return to work directory
      </Link>
      {result.isPending && <p role="status">Loading current record…</p>}
      {result.error && <p role="alert">Current record unavailable: {result.error.message}</p>}
      {value && (
        <>
          <h2>{scalar(value.summary ?? value.subject ?? value.title)}</h2>
          {!!value.propertyId && <CoverageLinks propertyId={scalar(value.propertyId)} />}
          <Facts value={value} fields={common} />
          {!!value.propertyId && (
            <p>
              <Link to={`/properties/${scalar(value.propertyId)}/maintenance`}>
                Property context
              </Link>
            </p>
          )}
          {!!value.leaseId && (
            <p>
              <Link to={`/leases/${scalar(value.leaseId)}`}>Lease context</Link>
            </p>
          )}
          {!!value.ownerPartyId && (
            <p>
              <Link to={`/owners/${scalar(value.ownerPartyId)}/overview`}>Owner context</Link>
            </p>
          )}
          {kind === "task" && (
            <>
              <TaskOutcome value={value} />
              <p>
                Waiting preserves the original deadline and urgency. Reminder acknowledgement is not
                Task completion. Setting waiting context again replaces whom or what is awaited;
                rescheduling only changes or removes the follow-up date.
              </p>
              <Facts
                value={value}
                fields={[
                  "title",
                  "notes",
                  "dueAtUtc",
                  "dueTimezone",
                  "taskDeadlineState",
                  "isAllDay",
                  "isWaiting",
                  "waitingForKind",
                  "waitingForLabel",
                  "followUpAt",
                  "followUpTimezone",
                  "followUpState",
                  "followUpDueToday",
                  "followUpActionable",
                  "outcomeNote",
                ]}
              />
              <RelatedLink
                kind={scalar(value.relatedEntityType)}
                id={scalar(value.relatedEntityId)}
              />
              <CommandLinks
                target={id}
                keys={
                  active
                    ? [
                        "task.edit",
                        ...(value.status === "open" ? ["task.start"] : []),
                        "task.complete",
                        "task.cancel",
                        "task.reminder.add",
                        ...(value.isWaiting
                          ? ["task.waiting.set", "task.waiting.clear", "task.waiting.reschedule"]
                          : ["task.waiting.set"]),
                      ]
                    : ["task.reopen"]
                }
              />
              <CommandLinks target={id} keys={["task.delete"]} title="Delete task" />
              <TaskReminders id={id} active={!!active} />
            </>
          )}
          {kind === "communication" && (
            <>
              <p>This is a manual conversation record; nothing is sent.</p>
              <p>
                Recorded local occurrence: {communicationLocalTime(value)} ·{" "}
                {scalar(value.occurredTimezone)}
              </p>
              <Facts
                value={value}
                fields={[
                  "direction",
                  "channel",
                  "subject",
                  "body",
                  "occurredAtUtc",
                  "occurredTimezone",
                  "correctionReason",
                ]}
              />
              {workChildren(value, "participants").map((item) => (
                <Facts
                  key={scalar(item.id)}
                  value={item}
                  fields={["role", "partyDisplayName", "contactDisplayValue"]}
                />
              ))}
              {workChildren(value, "links").map((item) => (
                <article key={scalar(item.id)}>
                  <RelatedLink kind={scalar(item.entityType)} id={scalar(item.entityId)} />
                  <Facts value={item} fields={["propertyTimezoneSnapshot"]} />
                  <Facts value={item.context} fields={Object.keys(record(item.context))} />
                </article>
              ))}
              <CommandLinks
                target={id}
                keys={
                  value.status === "draft"
                    ? ["communication.patch", "communication.draft.record"]
                    : value.status === "recorded"
                      ? ["communication.correct"]
                      : []
                }
              />
              {workChildren(value, "followUpTasks").map((item) => (
                <div key={scalar(item.id)}>
                  <Link to={workUrl("task", scalar(item.id))}>{scalar(item.title)}</Link> ·{" "}
                  {scalar(item.status)}
                  <Facts value={item} fields={["dueAtUtc", "dueTimezone"]} />
                </div>
              ))}
              {(["supersedesCommunicationId", "supersededByCommunicationId"] as const).map(
                (key) =>
                  value[key] && (
                    <p key={key}>
                      {key}:{" "}
                      <Link to={workUrl("communication", scalar(value[key]))}>
                        Conversation history
                      </Link>
                    </p>
                  ),
              )}
            </>
          )}
          {kind === "concern" && (
            <>
              <p>
                A concern is an Owner's recorded claim, not a derived property status. Follow-up
                completion does not resolve it.
              </p>
              <Facts
                value={value}
                fields={[
                  "concernType",
                  "ownerDisplayNameSnapshot",
                  "propertyDisplayNameSnapshot",
                  "spaceDisplayNameSnapshot",
                  "leaseDisplaySnapshot",
                  "tenantDisplayNameSnapshot",
                  "raisedAtUtc",
                  "propertyTimezoneSnapshot",
                  "observedOccupancyStatus",
                  "observedAvailabilityStatus",
                  "observedAvailableOn",
                  "resolutionSummary",
                  "dismissalReason",
                ]}
              />
              {value.status === "dismissed" && !record(value.successor).id && (
                <p>
                  <Link to={`${workflowUrl("owner_concern.create")}&replacesConcernId=${id}`}>
                    Correct dismissed concern context
                  </Link>
                </p>
              )}
              <Facts
                value={value.currentSourceState}
                fields={Object.keys(record(value.currentSourceState))}
              />
              {!!value.originatingCommunicationId && (
                <p>
                  <Link to={workUrl("communication", scalar(value.originatingCommunicationId))}>
                    Originating conversation
                  </Link>{" "}
                  ·{" "}
                  {scalar(record(value.originatingCommunicationState).status, "State unavailable")}
                </p>
              )}
              {!!record(value.originatingCommunicationState).supersededByCommunicationId && (
                <p>
                  <Link
                    to={workUrl(
                      "communication",
                      scalar(
                        record(value.originatingCommunicationState).supersededByCommunicationId,
                      ),
                    )}
                  >
                    Corrected originating conversation
                  </Link>
                </p>
              )}
              <CommandLinks
                target={id}
                keys={
                  active
                    ? [
                        "owner_concern.patch",
                        ...(value.status === "open" ? ["owner_concern.in_progress"] : []),
                        "owner_concern.resolved",
                        "owner_concern.dismissed",
                        "owner_concern.follow_up",
                      ]
                    : ["owner_concern.open"]
                }
              />
              {workChildren(value, "followUpTasks").map((item) => (
                <p key={scalar(item.id)}>
                  <Link to={workUrl("task", scalar(item.id))}>{scalar(item.title)}</Link> ·{" "}
                  {scalar(item.status)}
                </p>
              ))}
              <section aria-label="Recent concern conversations">
                <p>
                  {scalar(value.linkedCommunicationCount, "0")} retained conversation links; recent
                  preview only.
                </p>
                {workChildren(value, "recentCommunications").map((item) => (
                  <p key={scalar(item.id)}>
                    <Link to={workUrl("communication", scalar(item.id))}>
                      {scalar(item.subject)}
                    </Link>{" "}
                    · {scalar(item.status)}
                  </p>
                ))}
              </section>
              {["predecessor", "successor"].map(
                (key) =>
                  record(value[key]).id && (
                    <p key={key}>
                      {key}:{" "}
                      <Link to={workUrl("concern", scalar(record(value[key]).id))}>
                        Related concern
                      </Link>
                    </p>
                  ),
              )}
            </>
          )}
          {kind === "issue" && <IssueDetails value={value} active={!!active} />}
          {(kind === "issue" || kind === "concern") && (
            <>
              <Link
                to={`/conversations?entityType=${kind === "issue" ? "maintenance_issue" : "owner_concern"}&entityId=${id}`}
              >
                All linked conversations
              </Link>
              <p>
                <Link
                  to={`${workflowUrl("communication.create")}&entityType=${kind === "issue" ? "maintenance_issue" : "owner_concern"}&entityId=${id}`}
                >
                  Record linked conversation
                </Link>
              </p>
              {workChildren(
                value,
                kind === "issue" ? "communications" : "recentCommunications",
              ).map((item) => (
                <p key={scalar(item.id)}>
                  <Link to={workUrl("communication", scalar(item.id))}>{scalar(item.subject)}</Link>{" "}
                  · {scalar(item.status)}
                </p>
              ))}
            </>
          )}
          <History
            kind={
              {
                issue: "maintenance_issue",
                task: "task",
                concern: "owner_concern",
                communication: "communication",
              }[kind]
            }
            id={id}
          />
        </>
      )}
    </section>
  );
}
function IssueDetails({ value, active }: { value: Record<string, unknown>; active: boolean }) {
  const id = scalar(value.id);
  return (
    <>
      <p>
        Appointment attendance, reported completion, physical verification and issue resolution are
        independent facts. Cost context is not a paid expense.
      </p>
      <Facts
        value={value.reporter}
        fields={["role", "subjectKind", "partyId", "displayName", "currentPartyState"]}
      />
      <Facts
        value={value}
        fields={[
          "reportedAtUtc",
          "reportedTimezone",
          "resolutionSummary",
          "cancellationReason",
          "activeCompletionEvidenceCount",
        ]}
      />
      <CommandLinks
        target={id}
        keys={
          active
            ? [
                "maintenance.issue.patch",
                "maintenance.reporter.correct",
                ...(value.status === "open"
                  ? ["maintenance.issue.start"]
                  : ["maintenance.issue.return_to_open"]),
                "maintenance.issue.resolve",
                "maintenance.issue.cancel",
                "maintenance.appointment.create",
                "maintenance.quote.create",
                "maintenance.assignment.create",
                "maintenance.cost.create",
                "maintenance.expense.link",
                "maintenance.follow_up.create",
                "maintenance.journal.record",
              ]
            : ["maintenance.issue.reopen", "maintenance.journal.record"]
        }
      />
      {workChildren(value, "tasks").map((item) => (
        <div key={scalar(item.id)}>
          <Link to={workUrl("task", scalar(item.id))}>{scalar(item.title)}</Link> ·{" "}
          {scalar(item.status)}
          <Facts value={item} fields={["dueAtUtc", "dueTimezone"]} />
        </div>
      ))}
      {[
        [
          "appointments",
          "Appointments",
          [
            "startsAtUtc",
            "endsAtUtc",
            "scheduledTimezone",
            "status",
            "purpose",
            "outcomeNote",
            "cancellationReason",
          ],
          ["maintenance.appointment.update", "maintenance.appointment.finish"],
        ],
        [
          "quotes",
          "Provider quotes",
          [
            "providerDisplayNameSnapshot",
            "label",
            "scopeSummary",
            "amountMinor",
            "receivedOn",
            "withdrawnAt",
            "earliestWorkStartOn",
            "estimatedWorkFinishOn",
            "termsNotes",
            "validThrough",
            "withdrawalReason",
            "replacesQuoteId",
            "currentPartyState",
            "currentProviderProfileState",
          ],
          ["maintenance.quote.withdraw"],
        ],
        [
          "assignments",
          "Provider assignments",
          [
            "providerDisplayNameSnapshot",
            "assignedAt",
            "endedAt",
            "instructions",
            "endReason",
            "quoteId",
            "providerSelectionStatusSnapshot",
            "selectionReason",
            "avoidOverrideReason",
            "replacesAssignmentId",
            "currentPartyState",
            "currentProviderProfileState",
          ],
          ["maintenance.assignment.end"],
        ],
        [
          "costContexts",
          "Cost context (not paid money)",
          [
            "label",
            "contextKind",
            "amountMinor",
            "observedOn",
            "voidedAt",
            "voidReason",
            "sourceNote",
            "replacesCostContextId",
          ],
          ["maintenance.cost.void"],
        ],
        [
          "expenseLinks",
          "Paid expense associations",
          ["expenseId", "archivedAt", "archiveReason"],
          ["maintenance.expense.archive"],
        ],
      ].map(([key, title, fields, actions]) => (
        <section key={String(key)} aria-label={String(title)}>
          <h3>{String(title)}</h3>
          {workChildren(value, String(key)).map((item) => (
            <article key={scalar(item.id)}>
              {key === "costContexts" ? (
                <MoneyFacts value={item} fields={fields as string[]} />
              ) : key === "quotes" ? (
                <MoneyFacts value={item} fields={fields as string[]} />
              ) : (
                <Facts value={item} fields={fields as string[]} />
              )}
              {key === "quotes" && !!item.withdrawnAt && active && (
                <Link
                  to={`${workflowUrl("maintenance.quote.create", id)}&replacesQuoteId=${scalar(item.id)}`}
                >
                  Replace withdrawn quote
                </Link>
              )}
              {key === "assignments" && !item.endedAt && active && (
                <Link
                  to={`${workflowUrl("maintenance.assignment.create", id)}&replacesAssignmentId=${scalar(item.id)}`}
                >
                  Review reassignment
                </Link>
              )}
              {key === "costContexts" && !!item.voidedAt && active && (
                <Link
                  to={`${workflowUrl("maintenance.cost.create", id)}&replacesCostContextId=${scalar(item.id)}`}
                >
                  Replace cost context
                </Link>
              )}
              <EvidenceLinks
                items={workChildren(item, "files")}
                issueId={key !== "expenseLinks" ? id : undefined}
              />
              {key !== "expenseLinks" && (
                <p>
                  <Link
                    state={{ returnTo: workUrl("issue", id) }}
                    to={`${workflowUrl("file.upload")}&entityType=${key === "appointments" ? "maintenance_appointment" : key === "quotes" ? "maintenance_quote" : key === "assignments" ? "maintenance_assignment" : "maintenance_cost_context"}&entityId=${scalar(item.id)}&purpose=${key === "appointments" ? "appointment_document" : "supporting_document"}`}
                  >
                    Attach supporting document
                  </Link>
                </p>
              )}
              {key === "expenseLinks" && (
                <Link to={`/money?record=expense&id=${scalar(item.expenseId)}`}>Paid expense</Link>
              )}
              {active &&
                !item.archivedAt &&
                !item.voidedAt &&
                !item.withdrawnAt &&
                !item.endedAt &&
                (key !== "appointments" || item.status === "scheduled") && (
                  <CommandLinks
                    target={id}
                    child={scalar(item.id)}
                    keys={actions as string[]}
                    title={`Actions for ${scalar(item.label ?? item.purpose ?? item.providerDisplayNameSnapshot ?? item.id)}`}
                  />
                )}
            </article>
          ))}
        </section>
      ))}
      <WorkJournal id={id} />
      <QuoteComparison id={id} active={active} />
      <p>
        <Link
          state={{ returnTo: workUrl("issue", id) }}
          to={`${workflowUrl("file.upload")}&entityType=maintenance_issue&entityId=${id}`}
        >
          Attach issue evidence
        </Link>
      </p>
      <EvidenceLinks items={workChildren(value, "files")} issueId={id} />
    </>
  );
}
function TaskReminders({ id, active }: { id: string; active: boolean }) {
  const { scope } = useWorkspace();
  const result = useQuery({
    queryKey: scope.key("task-reminders", id),
    queryFn: async ({ signal }) =>
      readResult(
        await api.GET("/api/tasks/{task_id}/reminders", {
          signal,
          params: { path: { task_id: id }, query: { limit: 100 } },
        }),
      ),
  });
  return (
    <section aria-label="Task reminders">
      <h3>Reminders</h3>
      {result.error && <p role="alert">Reminders unavailable: {result.error.message}</p>}
      {result.data?.length === 100 && (
        <p>Showing the first 100 reminders; this is not the complete history.</p>
      )}
      {result.data?.map((item) => (
        <article key={item.id}>
          <Facts
            value={item}
            fields={["remindAtUtc", "status", "acknowledgedAtUtc", "dismissedAtUtc"]}
          />
          {active && item.status === "pending" && (
            <CommandLinks
              target={id}
              child={item.id}
              keys={["task.reminder.acknowledge", "task.reminder.dismiss"]}
              title={`Reminder actions ${item.remindAtUtc}`}
            />
          )}
        </article>
      ))}
    </section>
  );
}
function EvidenceLinks({ items, issueId }: { items: Record<string, unknown>[]; issueId?: string }) {
  return (
    <section aria-label="Evidence references">
      {items
        .filter((item) => !item.archivedAt)
        .map((item) => (
          <p key={scalar(item.id)}>
            <Link to={`/money?file=${scalar(item.fileId)}`}>
              Review evidence metadata: {scalar(item.originalName)}
            </Link>
            {item.available === false && " · Content unavailable; opening disabled"}
            {issueId && (
              <Link
                to={`/maintenance?workflow=file.link.archive&target=${scalar(item.id)}&issueId=${issueId}`}
              >
                Archive evidence association
              </Link>
            )}
          </p>
        ))}
    </section>
  );
}
export function RelatedLink({ kind, id }: { kind: string; id: string }) {
  if (!id) return null;
  const url =
    kind === "maintenance_issue"
      ? workUrl("issue", id)
      : kind === "owner_concern"
        ? workUrl("concern", id)
        : kind === "task"
          ? workUrl("task", id)
          : kind === "property"
            ? `/properties/${id}/overview`
            : kind === "lease"
              ? `/leases/${id}`
              : kind === "party"
                ? `/parties?identity=${id}`
                : kind === "rent_receipt"
                  ? `/money?record=receipt&id=${id}`
                  : kind === "rent_expectation"
                    ? `/money?record=expectation&id=${id}`
                    : null;
  return url ? (
    <Link to={url}>Related {kind.replaceAll("_", " ")}</Link>
  ) : (
    <span>
      Related {kind}: {id}
    </span>
  );
}
