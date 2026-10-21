import { useQuery } from "@tanstack/react-query";
import { Link, useLocation, useSearchParams } from "react-router-dom";
import { api } from "@epm/contracts";
import type { components } from "@epm/contracts/generated";
import { useWorkspace } from "../app/workspace-gate";
import { normalizeApiError } from "./mutations";
import { PageAsOf } from "./page-as-of";
import { leaseLastCoveredOn } from "./lease-dates";
import { formatHomeTemporal, formatHomeTime } from "./home-time";

type Conversation = components["schemas"]["CommunicationResponse"];
type Source = {
  title: string;
  facts: Record<string, string | number | null>;
  conversation?: Conversation;
};
const readable = (value: string) =>
  value.replaceAll("_", " ").replace(/^./, (letter) => letter.toUpperCase());
const recordLabels: Record<string, string> = {
  space: "Rental unit",
  lease: "Lease",
  task: "Task",
  maintenance_issue: "Maintenance issue",
  communication: "Conversation",
  owner_concern: "Owner concern",
};

type ConversationPresentation = {
  id: string;
  subject: string;
  occurredAtUtc: string;
  occurredTimezone: string;
  channel: string;
  direction: string;
  status: string;
  body: string;
  participants: {
    id: string;
    role: string;
    partyDisplayName: string;
    contactDisplayValue?: string | null;
  }[];
};

export function ConversationDetail({
  item,
  showTitle = true,
  showFullLink = true,
}: {
  item: ConversationPresentation;
  showTitle?: boolean;
  showFullLink?: boolean;
}) {
  return (
    <>
      {showTitle && <h4 className="conversation-detail-subject">{item.subject}</h4>}
      <p className="conversation-detail-time">
        <time dateTime={item.occurredAtUtc}>
          {formatHomeTemporal({ at: item.occurredAtUtc, timeZone: item.occurredTimezone })}
        </time>
      </p>
      <dl className="conversation-detail-meta">
        <div>
          <dt>Channel</dt>
          <dd>{readable(item.channel)}</dd>
        </div>
        <div>
          <dt>Direction</dt>
          <dd>{readable(item.direction)}</dd>
        </div>
        <div>
          <dt>Status</dt>
          <dd>{readable(item.status)}</dd>
        </div>
      </dl>
      <ul className="conversation-detail-participants" aria-label="Conversation participants">
        {item.participants.map((participant) => (
          <li key={participant.id}>
            <span>
              {participant.role === "sender"
                ? "From"
                : participant.role === "recipient"
                  ? "To"
                  : readable(participant.role)}
            </span>{" "}
            <strong>{participant.partyDisplayName}</strong>
            {participant.contactDisplayValue && <> · {participant.contactDisplayValue}</>}
          </li>
        ))}
      </ul>
      <section className="conversation-detail-message" aria-label="Message">
        <h5>Message</h5>
        <p>{item.body || "No message recorded."}</p>
      </section>
      {showFullLink && (
        <Link to={`/conversations?record=communication&id=${item.id}`}>View full conversation</Link>
      )}
    </>
  );
}
async function readSource(kind: string, id: string, signal: AbortSignal): Promise<Source> {
  function data<T>(response: { data?: T; error?: unknown; response: Response }): T {
    if (!response.data)
      throw new Error(normalizeApiError(response.response.status, response.error).message);
    return response.data;
  }
  switch (kind) {
    case "space": {
      const item = data(
        await api.GET("/api/spaces/{space_id}/status", {
          signal,
          params: { path: { space_id: id } },
        }),
      );
      return {
        title: item.displayName,
        facts: {
          Status: readable(item.status),
          "Effective local date": item.effectiveLocalDate,
          "As of": item.asOf,
        },
      };
    }
    case "lease": {
      const item = data(
        await api.GET("/api/leases/{lease_id}", { signal, params: { path: { lease_id: id } } }),
      );
      return {
        title: `${readable(item.leaseKind)} lease`,
        facts: {
          Status: readable(item.status),
          "Contract starts": item.contractStartsOn,
          "Lease end (last covered day)": leaseLastCoveredOn(item.contractEndsOn),
          "Occupancy starts": item.occupancyStartsOn,
          "Actual move-out": item.actualMoveOutOn,
          Notes: item.notes,
        },
      };
    }
    case "task": {
      const item = data(
        await api.GET("/api/tasks/{task_id}", { signal, params: { path: { task_id: id } } }),
      );
      return {
        title: item.title,
        facts: {
          Status: readable(item.status),
          Priority: readable(item.priority),
          Notes: item.notes,
          Deadline: item.dueAtUtc
            ? formatHomeTemporal({ at: item.dueAtUtc, timeZone: item.dueTimezone })
            : null,
          "Deadline status": item.taskDeadlineState ? readable(item.taskDeadlineState) : null,
          "Waiting for": item.waitingForLabel,
          "Follow-up": item.followUpAt ? formatHomeTime(item.followUpAt) : null,
          "Follow-up status": item.followUpState ? readable(item.followUpState) : null,
          "As of": item.asOf,
        },
      };
    }
    case "maintenance_issue": {
      const item = data(
        await api.GET("/api/maintenance-issues/{issue_id}", {
          signal,
          params: { path: { issue_id: id } },
        }),
      );
      return {
        title: item.summary,
        facts: {
          Status: readable(item.status),
          Priority: readable(item.priority),
          Category: readable(item.category),
        },
      };
    }
    case "communication": {
      const item = data(
        await api.GET("/api/communications/{communication_id}", {
          signal,
          params: { path: { communication_id: id } },
        }),
      );
      return {
        title: item.subject,
        facts: {},
        conversation: item,
      };
    }
    case "owner_concern": {
      const item = data(
        await api.GET("/api/owner-concerns/{concern_id}", {
          signal,
          params: { path: { concern_id: id } },
        }),
      );
      return {
        title: item.summary,
        facts: {
          Status: readable(item.status),
          Priority: readable(item.priority),
          Type: readable(item.concernType),
        },
      };
    }
    default:
      throw new Error("This record type cannot be displayed here.");
  }
}
export function SourceDetail() {
  const location = useLocation();
  const state: unknown = location.state;
  const [params] = useSearchParams();
  const { scope } = useWorkspace();
  const kind = params.get("sourceType"),
    id = params.get("sourceId");
  const result = useQuery({
    queryKey: scope.key("context-source", kind, id),
    enabled: !!kind && !!id,
    queryFn: ({ signal }) => readSource(kind ?? "", id ?? "", signal),
  });
  if (!kind || !id) return null;
  const back = new URLSearchParams(params);
  back.delete("sourceType");
  back.delete("sourceId");
  return (
    <section
      id="source-detail"
      aria-label="Record details"
      className={kind === "communication" ? "conversation-detail" : "context-section"}
    >
      <header className={kind === "communication" ? "conversation-detail-heading" : undefined}>
        <h3>{recordLabels[kind] ?? "Record"} details</h3>
        <Link state={state} to={`?${back.toString()}`}>
          {kind === "communication" ? "Close conversation" : "Close details"}
        </Link>
      </header>
      {result.isPending && <p role="status">Loading record…</p>}
      {result.error && (
        <div role="alert">
          {result.error.message}
          <button
            onClick={() => {
              void result.refetch();
            }}
          >
            Retry record
          </button>
        </div>
      )}
      {result.data?.conversation ? (
        <ConversationDetail item={result.data.conversation} />
      ) : (
        result.data && (
          <>
            {typeof result.data.facts["As of"] === "string" && (
              <PageAsOf asOf={result.data.facts["As of"]} priority={1} />
            )}
            <h4>{result.data.title}</h4>
            {kind === "lease" && <Link to={`/leases/${id}/details`}>View lease</Link>}
            {["task", "maintenance_issue", "communication", "owner_concern"].includes(kind) && (
              <Link
                to={`${kind === "task" ? "/tasks" : kind === "communication" ? "/conversations" : "/maintenance"}?record=${kind === "maintenance_issue" ? "issue" : kind === "owner_concern" ? "concern" : kind}&id=${id}`}
              >
                View {recordLabels[kind]?.toLowerCase() ?? "record"}
              </Link>
            )}
            <dl>
              {Object.entries(result.data.facts)
                .filter(([name]) => name !== "As of")
                .map(([name, value]) => (
                  <div key={name}>
                    <dt>{name}</dt>
                    <dd>{value ?? "Not recorded"}</dd>
                  </div>
                ))}
            </dl>
          </>
        )
      )}
    </section>
  );
}
