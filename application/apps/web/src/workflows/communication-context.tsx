import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@epm/contracts";
import { record, scalar } from "@epm/contracts/workflows";
import { useWorkspace } from "../app/workspace-gate";
import { Facts, readResult } from "./reads";

export function communicationLocalTime(value: Record<string, unknown>) {
  try {
    return new Intl.DateTimeFormat("en-US", {
      timeZone: scalar(value.occurredTimezone),
      dateStyle: "medium",
      timeStyle: "short",
    }).format(new Date(scalar(value.occurredAtUtc)));
  } catch {
    return "Local occurrence unavailable";
  }
}

function ParticipantContact({
  participant,
  index,
  locked,
  onChange,
}: {
  participant: Record<string, unknown>;
  index: number;
  locked: boolean;
  onChange: (contact: string | undefined) => void;
}) {
  const { scope } = useWorkspace();
  const id = scalar(participant.partyId, "");
  const party = useQuery({
    queryKey: scope.key("communication-participant", id),
    enabled: !!id,
    queryFn: async ({ signal }) =>
      readResult(
        await api.GET("/api/parties/{party_id}", { signal, params: { path: { party_id: id } } }),
      ),
  });
  if (!id) return null;
  if (party.error)
    return (
      <p role="alert">
        Participant {index + 1} identity unavailable: {party.error.message}
      </p>
    );
  return (
    <div>
      <p>
        Participant {index + 1}: {party.data?.displayName ?? "Loading identity…"}
        {party.data?.archivedAt
          ? " — archived; cannot make a new recording with this identity"
          : ""}
      </p>
      <label>
        Contact snapshot for participant {index + 1}
        <select
          disabled={locked || !party.data || !!party.data.archivedAt}
          value={scalar(participant.partyContactMethodId, "")}
          onChange={(event) => onChange(event.target.value || undefined)}
        >
          <option value="">No contact snapshot</option>
          {(party.data?.contactMethods ?? [])
            .filter((contact) => !contact.archivedAt)
            .map((contact) => (
              <option key={contact.id} value={contact.id}>
                {contact.methodKind} · {contact.displayValue}
              </option>
            ))}
        </select>
      </label>
      <p>
        A contact is an immutable historical snapshot, not a delivery destination or sending
        authorization.
      </p>
    </div>
  );
}

export function CommunicationContext({
  values,
  locked,
  onChange,
  source,
}: {
  values: Record<string, unknown>;
  locked: boolean;
  onChange: (values: Record<string, unknown>) => void;
  source: Record<string, unknown>;
}) {
  const { scope } = useWorkspace();
  const [input, setInput] = useState("");
  const [search, setSearch] = useState("");
  const parties = useQuery({
    enabled: Array.isArray(values.participants) && search.length >= 2,
    queryKey: scope.key("communication-party-selection", search),
    queryFn: async ({ signal }) =>
      readResult(
        await api.GET("/api/parties/selection", {
          signal,
          params: { query: { search: search || undefined, limit: 25, includeArchived: false } },
        }),
      ),
  });
  const participants = Array.isArray(values.participants) ? values.participants.map(record) : [];
  return (
    <section aria-label="Manual communication review">
      <h3>Record an interaction, never send it</h3>
      <p>
        Body, participant contacts and correction reasons are sensitive contextual history. Do not
        paste passwords, credentials or unrelated personal details; general activity does not
        disclose this narrative.
      </p>
      <p>
        Outbound means already sent or spoken outside this application. Inbound means received
        manually; nothing is fetched from a mailbox. Drafts are not recorded history. Follow-up
        creates a Task, not a message or automated reminder.
      </p>
      <p>
        Use the original occurrence instant and its IANA time zone. Typed Property, Space or Lease
        links must agree with that zone. Source links reference retained evidence; they do not copy
        its contents or automatically follow replacements.
      </p>
      <Facts value={source} fields={["status", "revision", "occurredAtUtc", "occurredTimezone"]} />
      {Array.isArray(values.participants) && (
        <>
          <label>
            Find participant by name
            <input
              value={input}
              onChange={(event) => setInput(event.target.value)}
              maxLength={200}
              disabled={locked}
            />
          </label>
          <button type="button" disabled={locked} onClick={() => setSearch(input.trim())}>
            Search participants
          </button>
          {parties.error && (
            <p role="alert">Participant selection unavailable: {parties.error.message}</p>
          )}
          <p>
            At most 25 active identities are shown. Search to narrow the selection; no tenant role
            is required.
          </p>
          {parties.data?.items.map((party) => (
            <button
              type="button"
              key={party.id}
              disabled={
                locked ||
                participants.length >= 100 ||
                participants.some((item) => item.partyId === party.id)
              }
              onClick={() =>
                onChange({
                  ...values,
                  participants: [...participants, { partyId: party.id, role: "recipient" }],
                })
              }
            >
              Add {party.displayName} participant
            </button>
          ))}
          {participants.map((participant, index) => (
            <ParticipantContact
              key={`${index}:${scalar(participant.partyId)}`}
              participant={participant}
              index={index}
              locked={locked}
              onChange={(contact) =>
                onChange({
                  ...values,
                  participants: participants.map((item, position) =>
                    position === index ? { ...item, partyContactMethodId: contact } : item,
                  ),
                })
              }
            />
          ))}
        </>
      )}
      {source.status === "recorded" && (
        <p>
          Correction preserves the original entry and its follow-up Tasks. Explain what was wrong;
          the replacement is a separate recorded interaction, not a silent edit.
        </p>
      )}
    </section>
  );
}
