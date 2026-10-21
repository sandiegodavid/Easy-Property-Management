import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@epm/contracts";
import { record, scalar } from "@epm/contracts/workflows";
import { useWorkspace } from "../app/workspace-gate";
import { normalizeApiError } from "../shared/mutations";
import { label } from "./fields";
import { formatHomeTime } from "../shared/home-time";
import { leasingStatusLabels } from "../shared/leasing-status";

function historyValue(key: string, value: unknown) {
  if (value === null || value === undefined) return "Not recorded";
  const text = scalar(value);
  if (key === "availabilityStatus")
    return leasingStatusLabels[text] ?? (text === "unknown" ? "Needs classification" : text);
  if (key === "occupancyStatus") return text === "unknown" ? "Needs classification" : label(text);
  return text.replaceAll("_", " ");
}

function historySummary(event: Record<string, unknown>) {
  const before = record(event.before);
  const after = record(event.after);
  const changes = [
    "displayName",
    "status",
    "occupancyStatus",
    "availabilityStatus",
    "availableOn",
    "startsOn",
    "endsOn",
  ]
    .filter((key) => key in before && key in after && before[key] !== after[key])
    .map(
      (key) =>
        `${label(key)} changed from ${historyValue(key, before[key])} to ${historyValue(key, after[key])}.`,
    );
  return changes.length ? changes.join(" ") : label(scalar(event.action).replaceAll("_", " "));
}

export function readResult<T>(response: { data?: T; error?: unknown; response: Response }): T {
  if (!response.data)
    throw new Error(normalizeApiError(response.response.status, response.error).message);
  return response.data;
}
const uuidPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function Facts({
  value,
  fields,
  verbatim = false,
}: {
  value: unknown;
  fields: string[];
  verbatim?: boolean;
}) {
  const values = record(value);
  return (
    <dl className="workflow-facts">
      {fields.map((key) => {
        const raw = values[key];
        const text =
          raw === null || raw === undefined
            ? "Not recorded"
            : typeof raw === "boolean"
              ? raw
                ? "Yes"
                : "No"
              : verbatim
                ? scalar(raw)
                : historyValue(key, raw);
        const isStatus =
          typeof raw === "string" && (/(?:Status|Kind|State)$/.test(key) || key === "status");
        const isId =
          typeof raw === "string" && uuidPattern.test(raw) && (key.endsWith("Id") || key === "id");
        return (
          <div key={key}>
            <dt>{label(key)}</dt>
            <dd>
              {isStatus ? (
                <span className="workflow-fact-status" data-status={raw}>
                  {text}
                </span>
              ) : isId ? (
                <span className="workflow-fact-id">{text}</span>
              ) : (
                text
              )}
            </dd>
          </div>
        );
      })}
    </dl>
  );
}
export function History({
  kind,
  id,
  snapshotFields,
  presentation,
}: {
  kind: string;
  id: string;
  snapshotFields?: string[];
  presentation?: "timeline";
}) {
  const { scope } = useWorkspace();
  const timeline = presentation === "timeline" || kind === "space";
  const [open, setOpen] = useState(false);
  const [offset, setOffset] = useState(0);
  const result = useQuery({
    queryKey: scope.key("workflow-history", kind, id, offset),
    enabled: open,
    queryFn: async ({ signal }) => {
      const response = await api.GET("/api/audit/events/{entity_type}/{entity_id}", {
        signal,
        params: { path: { entity_type: kind, entity_id: id }, query: { limit: 20, offset } },
      });
      const events = record(readResult(response)).events;
      if (!Array.isArray(events)) throw new Error("History response is unavailable.");
      return events.map(record);
    },
  });
  return (
    <details
      className={timeline ? "property-history" : undefined}
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      <summary>History</summary>
      {timeline && open && (
        <p className="property-history-intro">Recorded changes, newest first.</p>
      )}
      {result.isPending && open && <p role="status">Loading history…</p>}
      {result.error && <p role="alert">{result.error.message}</p>}
      {result.data?.map((event) => (
        <article key={scalar(event.id)}>
          {timeline ? (
            <>
              <header className="property-history-event-heading">
                <strong>{historySummary(event)}</strong>
                <time dateTime={scalar(event.occurredAt)}>
                  {formatHomeTime(scalar(event.occurredAt))}
                </time>
              </header>
              <p className="property-history-actor">
                {event.actorKind === "local_operator"
                  ? "You"
                  : label(scalar(event.actorKind).replaceAll("_", " "))}
              </p>
              {!!event.reason && (
                <p className="property-history-reason">
                  {scalar(event.reason).replaceAll("_", " ")}
                </p>
              )}
            </>
          ) : (
            <Facts value={event} fields={["action", "occurredAt", "actorKind", "reason"]} />
          )}
          <div className={timeline ? "property-history-changes" : undefined}>
            {["before", "after"].map((phase) => (
              <details key={phase}>
                <summary>{phase === "before" ? "Before change" : "After change"}</summary>
                <Facts
                  value={event[phase]}
                  verbatim={!!snapshotFields}
                  fields={Object.keys(record(event[phase])).filter((key) =>
                    (
                      snapshotFields ?? [
                        "displayName",
                        "status",
                        "archivedAt",
                        "archiveReason",
                        "ownerKind",
                        "startsOn",
                        "endsOn",
                        "effectiveOn",
                        "ownershipContext",
                        "occupancyStatus",
                        "availabilityStatus",
                        "availableOn",
                        "note",
                      ]
                    ).includes(key),
                  )}
                />
                {Array.isArray(record(event[phase]).ownerships) &&
                  (record(event[phase]).ownerships as unknown[]).map((owner, index) => (
                    <Facts key={index} value={owner} fields={["ownerKind", "startsOn", "endsOn"]} />
                  ))}
              </details>
            ))}
          </div>
        </article>
      ))}
      {result.data?.length === 0 && <p>No recorded history on this page.</p>}
      {result.data?.length === 20 && (
        <button onClick={() => setOffset(offset + 20)}>Older history</button>
      )}
      {offset > 0 && <button onClick={() => setOffset(0)}>Latest history</button>}
    </details>
  );
}

export function IdentityLookup({
  onSelect,
  embedded = false,
}: {
  onSelect: (id: string, displayName: string) => void;
  embedded?: boolean;
}) {
  const [input, setInput] = useState("");
  const [selected, setSelected] = useState("");
  const current = input.trim();
  useEffect(() => {
    const timer = setTimeout(() => {
      setSelected(
        /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(current)
          ? current
          : "",
      );
    }, 300);
    return () => clearTimeout(timer);
  }, [current]);
  const { scope } = useWorkspace();
  const party = useQuery({
    queryKey: scope.key("identity-lookup", selected),
    enabled: !!selected && selected === current,
    queryFn: async ({ signal }) =>
      readResult(
        await api.GET("/api/parties/{party_id}", {
          signal,
          params: { path: { party_id: selected } },
        }),
      ),
  });
  const controls = (
    <>
      <label>
        Existing identity ID
        <input
          value={input}
          onChange={(event) => setInput(event.target.value)}
          onKeyDown={(event) => {
            if (embedded && event.key === "Enter") {
              event.preventDefault();
            }
          }}
        />
      </label>
    </>
  );
  return (
    <section aria-label="Find shared identity">
      <h3>Find shared identity</h3>
      <p>
        Use an identity already visible in a property, tenant or provider record. Review its name
        and active roles before selecting it.
      </p>
      <div>{controls}</div>
      {party.isFetching && selected === current && <p role="status">Finding identity…</p>}
      {party.error && selected === current && <p role="alert">{party.error.message}</p>}
      {party.data && selected === current && (
        <>
          <p>
            {party.data.displayName} · {party.data.archivedAt ? "Archived" : "Active"} ·{" "}
            {party.data.activeRoles?.join(", ") || "No active roles"}
          </p>
          <button type="button" onClick={() => onSelect(party.data.id, party.data.displayName)}>
            Use {party.data.displayName}
          </button>
        </>
      )}
    </section>
  );
}
