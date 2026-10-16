import { useQuery } from "@tanstack/react-query";
import { Link, useLocation, useSearchParams } from "react-router-dom";
import { api } from "@epm/contracts";
import { useWorkspace } from "../app/workspace-gate";
import { normalizeApiError } from "./mutations";
import { PageAsOf } from "./page-as-of";
import { leaseLastCoveredOn } from "./lease-dates";

type Source = { title: string; facts: Record<string, string | number | null> };
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
          Property: item.propertyId,
          Status: item.status,
          Revision: item.revision,
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
        title: `${item.leaseKind} lease`,
        facts: {
          Status: item.status,
          Revision: item.leaseRevision,
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
          Status: item.status,
          Revision: item.revision,
          Priority: item.priority,
          Notes: item.notes,
          Deadline: item.dueAtUtc,
          "Deadline time zone": item.dueTimezone,
          "Deadline state": item.taskDeadlineState,
          "Waiting for": item.waitingForLabel,
          "Follow-up": item.followUpAt,
          "Follow-up state": item.followUpState,
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
        facts: { Status: item.status, Priority: item.priority, Category: item.category },
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
        facts: {
          Status: item.status,
          Revision: item.revision,
          Channel: item.channel,
          Direction: item.direction,
          "Occurred at": item.occurredAtUtc,
          "Time zone": item.occurredTimezone,
          Body: item.body,
        },
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
        facts: { Status: item.status, Priority: item.priority, Type: item.concernType },
      };
    }
    default:
      throw new Error("Unsupported source kind.");
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
    <section id="source-detail" aria-label="Source detail" className="context-section">
      <h3>Source detail</h3>
      <p>
        {kind} · {id}
      </p>
      <Link state={state} to={`?${back.toString()}`}>
        Close source detail
      </Link>
      {result.isPending && <p role="status">Loading source…</p>}
      {result.error && (
        <div role="alert">
          {result.error.message}
          <button
            onClick={() => {
              void result.refetch();
            }}
          >
            Retry source
          </button>
        </div>
      )}
      {result.data && (
        <>
          {typeof result.data.facts["As of"] === "string" && (
            <PageAsOf asOf={result.data.facts["As of"]} priority={1} />
          )}
          <h4>{result.data.title}</h4>
          {kind === "lease" && <Link to={`/leases/${id}/details`}>Open Lease workflow</Link>}
          {["task", "maintenance_issue", "communication", "owner_concern"].includes(kind) && (
            <Link
              to={`${kind === "task" ? "/tasks" : kind === "communication" ? "/conversations" : "/maintenance"}?record=${kind === "maintenance_issue" ? "issue" : kind === "owner_concern" ? "concern" : kind}&id=${id}`}
            >
              Open work workflow
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
      )}
    </section>
  );
}
