import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@epm/contracts";
import { record, scalar } from "@epm/contracts/workflows";
import { useWorkspace } from "../app/workspace-gate";
import { normalizeApiError } from "../shared/mutations";
import { label } from "./fields";
import { formatHomeTime } from "../shared/home-time";

export function readResult<T>(response: { data?: T; error?: unknown; response: Response }): T {
  if (!response.data)
    throw new Error(normalizeApiError(response.response.status, response.error).message);
  return response.data;
}
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
      {fields.map((key) => (
        <div key={key}>
          <dt>{label(key)}</dt>
          <dd>
            {values[key] === null || values[key] === undefined
              ? "Not recorded"
              : typeof values[key] === "boolean"
                ? values[key]
                  ? "Yes"
                  : "No"
                : verbatim
                  ? scalar(values[key])
                  : scalar(values[key]).replaceAll("_", " ")}
          </dd>
        </div>
      ))}
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
      className={presentation === "timeline" ? "property-history" : undefined}
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      <summary>History</summary>
      {presentation === "timeline" && open && (
        <p className="property-history-intro">Recorded changes to this property, newest first.</p>
      )}
      {result.isPending && open && <p role="status">Loading history…</p>}
      {result.error && <p role="alert">{result.error.message}</p>}
      {result.data?.map((event) => (
        <article key={scalar(event.id)}>
          {presentation === "timeline" ? (
            <>
              <header className="property-history-event-heading">
                <strong>{scalar(event.action).replaceAll("_", " ")}</strong>
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
          <div className={presentation === "timeline" ? "property-history-changes" : undefined}>
            {["before", "after"].map((phase) => (
              <details key={phase}>
                <summary>{phase === "before" ? "Prior facts" : "Resulting facts"}</summary>
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
}: {
  onSelect: (id: string, displayName: string) => void;
}) {
  const [input, setInput] = useState("");
  const [selected, setSelected] = useState("");
  const { scope } = useWorkspace();
  const party = useQuery({
    queryKey: scope.key("identity-lookup", selected),
    enabled: !!selected,
    queryFn: async ({ signal }) =>
      readResult(
        await api.GET("/api/parties/{party_id}", {
          signal,
          params: { path: { party_id: selected } },
        }),
      ),
  });
  return (
    <section aria-label="Find shared identity">
      <h3>Find shared identity</h3>
      <p>
        Use an identity already visible in a property, tenant or provider record. Review its name
        and active roles before selecting it.
      </p>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          setSelected(input);
        }}
      >
        <label>
          Existing identity ID
          <input required value={input} onChange={(event) => setInput(event.target.value)} />
        </label>
        <button>Find identity</button>
      </form>
      {party.isPending && selected && <p role="status">Finding identity…</p>}
      {party.error && <p role="alert">{party.error.message}</p>}
      {party.data && (
        <>
          <p>
            {party.data.displayName} · {party.data.archivedAt ? "Archived" : "Active"} ·{" "}
            {party.data.activeRoles?.join(", ") || "No active roles"}
          </p>
          <button onClick={() => onSelect(party.data.id, party.data.displayName)}>
            Use {party.data.displayName}
          </button>
        </>
      )}
    </section>
  );
}
