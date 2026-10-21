import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "@epm/contracts";
import { record, scalar } from "@epm/contracts/workflows";
import { useWorkspace } from "../app/workspace-gate";
import { readResult } from "./reads";
import { ReadableFacts } from "./readable-facts";
import { EvidenceItem } from "./evidence-item";
import { workflowUrl } from "./command";
import { workUrl } from "./work-links";
import { communicationLocalTime } from "./communication-context";
import { formatHomeTime } from "../shared/home-time";

function workDuration(seconds: number) {
  const units = [
    [86400, "day"],
    [3600, "hour"],
    [60, "minute"],
    [1, "second"],
  ] as const;
  let remaining = Math.floor(Math.abs(seconds));
  const parts: string[] = [];
  for (const [size, name] of units) {
    const count = Math.floor(remaining / size);
    if (count) parts.push(`${count} ${name}${count === 1 ? "" : "s"}`);
    remaining %= size;
  }
  const duration = parts.join(" ") || "0 seconds";
  return seconds < 0 ? `${duration} before assignment` : duration;
}

export function journalProblem(values: Record<string, unknown>, terminal: boolean) {
  const correction = values.entryKind === "correction";
  const kind = correction ? values.correctedEntryKind : values.entryKind;
  if (terminal && values.historicalEntryConfirmed !== true)
    return "Confirm this is historical work on a terminal issue; it does not reopen the issue.";
  if (values.sourceKind === "provider_report" && !values.assignmentId)
    return "A Provider report requires an assignment from this issue.";
  if (correction && (!values.correctsEntryId || !scalar(values.correctionReason, "").trim()))
    return "Select an effective entry and give a correction reason. Originals remain retained.";
  if (kind === "work_completed") {
    if (!values.outcomeStatus || !scalar(values.outcomeSummary, "").trim())
      return "Completed work requires an outcome and summary, not an issue-resolution command.";
    if (
      typeof values.operatorVerified !== "boolean" ||
      typeof values.followUpRequired !== "boolean"
    )
      return "Explicitly record operator verification and follow-up need.";
  } else if (
    ["outcomeStatus", "outcomeSummary", "operatorVerified", "followUpRequired"].some(
      (key) => values[key] !== undefined && values[key] !== null,
    )
  )
    return "Outcome fields apply only to completed work.";
  return undefined;
}

export function JournalCommandContext({
  values,
  terminal,
}: {
  values: Record<string, unknown>;
  terminal: boolean;
}) {
  const problem = journalProblem(values, terminal);
  return (
    <section aria-label="Work journal review">
      <p>
        Append a fact, never edit or delete an entry. A correction retains its predecessor and
        replaces the complete factual payload.
      </p>
      <p>
        Provider-reported completion is not operator verification. Recording work does not resolve
        the issue, end an assignment, finish an appointment or Task, or create spending. Keep money
        in quotes, cost context and Finance.
      </p>
      <p>
        Assignment selection includes current and ended engagements. Unassigned operator
        observations are allowed. Evidence is optional and attached after saving the entry.
      </p>
      {terminal && (
        <p>
          This issue is terminal. Explicit historical confirmation is required; the issue stays
          terminal.
        </p>
      )}
      {problem && <p role="alert">{problem}</p>}
    </section>
  );
}

export function WorkJournal({ id, provider = false }: { id: string; provider?: boolean }) {
  const { scope } = useWorkspace();
  const [cursor, setCursor] = useState<string>();
  const result = useQuery({
    queryKey: scope.key("work-journal", provider, id, cursor),
    queryFn: async ({ signal }) =>
      readResult(
        provider
          ? await api.GET("/api/maintenance-work-journal", {
              signal,
              params: { query: { providerPartyId: id, pageSize: 20, cursor } },
            })
          : await api.GET("/api/maintenance-issues/{issue_id}/work-journal", {
              signal,
              params: { path: { issue_id: id }, query: { pageSize: 20, cursor } },
            }),
      ),
  });
  const cursorQuery = cursor ? `&journalCursor=${encodeURIComponent(cursor)}` : "";
  return (
    <section aria-label={provider ? "Issue-backed Provider work" : "Work journal"}>
      <h3>
        {provider
          ? "Issue-backed work — Maintenance history"
          : "Work journal and physical verification"}
      </h3>
      {provider && (
        <p>
          Quoted dates are planned; occurrences are actual recorded facts. Recorded
          assignment-to-work-start is not Provider response time. Manual Provider prior-work notes
          remain separate.
        </p>
      )}
      {result.isPending && <p role="status">Loading work journal…</p>}
      {result.error && <p role="alert">Work journal unavailable: {result.error.message}</p>}
      {result.data?.items.length === 0 && <p>No work entries on this page.</p>}
      <ol className="work-journal-timeline">
        {result.data?.items.map((item) => (
          <li key={item.id}>
            <article>
              <time dateTime={item.occurredAtUtc}>{communicationLocalTime(item)}</time>
              <header className="child-record-heading">
                <h4>{item.summary}</h4>
                <span className="record-pill">
                  {item.isEffective ? "Current record" : "Superseded"}
                </span>
              </header>
              <ReadableFacts
                value={{
                  ...item,
                  recordedAtUtc: formatHomeTime(item.recordedAtUtc),
                  recordedAssignmentToWorkStartSeconds:
                    item.recordedAssignmentToWorkStartSeconds == null
                      ? null
                      : workDuration(item.recordedAssignmentToWorkStartSeconds),
                }}
                fields={[
                  "effectiveKind",
                  "sourceKind",
                  "assignmentId",
                  "providerDisplayNameSnapshot",
                  "occurredTimezone",
                  "recordedAtUtc",
                  "detail",
                  "outcomeStatus",
                  "outcomeSummary",
                  "followUpRequired",
                  "operatorVerified",
                  "correctsEntryId",
                  "correctionReason",
                  "assignedAt",
                  "quotedEarliestWorkStartOn",
                  "quotedEstimatedWorkFinishOn",
                  "recordedAssignmentToWorkStartSeconds",
                ].filter(
                  (field) =>
                    !field.endsWith("Id") &&
                    field !== "occurredTimezone" &&
                    record(item)[field] != null,
                )}
              />
              {!item.isEffective && (
                <p>Superseded factual entry; retained for context, not current completion.</p>
              )}
              {provider ? (
                <Link to={workUrl("issue", item.issueId)}>
                  Review owning issue: {item.issueSummary}
                </Link>
              ) : (
                <>
                  {item.files
                    .filter((file) => !file.archivedAt)
                    .map((file) => (
                      <EvidenceItem
                        key={file.id}
                        name={file.originalName}
                        state={file.available ? "Available" : "Unavailable"}
                      >
                        <Link to={`/money?file=${file.fileId}`}>
                          Review evidence metadata: {file.originalName}
                        </Link>
                        {!file.available && " · Content unavailable; opening disabled"}{" "}
                        <Link
                          to={`/maintenance?workflow=file.link.archive&target=${file.id}&issueId=${id}${cursorQuery}`}
                        >
                          Archive evidence association
                        </Link>
                      </EvidenceItem>
                    ))}
                  {item.isEffective && (
                    <p>
                      <Link
                        to={`${workflowUrl("maintenance.journal.record", id)}&correctsEntryId=${item.id}${cursorQuery}`}
                      >
                        Correct work entry: {item.summary}
                      </Link>
                      {" · "}
                      <Link
                        state={{ returnTo: workUrl("issue", id) }}
                        to={`${workflowUrl("file.upload")}&entityType=maintenance_work_journal_entry&entityId=${item.id}`}
                      >
                        Attach work evidence
                      </Link>
                    </p>
                  )}
                </>
              )}
            </article>
          </li>
        ))}
      </ol>
      {result.data?.nextCursor && (
        <button onClick={() => setCursor(result.data.nextCursor!)}>Older work entries</button>
      )}
      {cursor && <button onClick={() => setCursor(undefined)}>First work page</button>}
    </section>
  );
}
