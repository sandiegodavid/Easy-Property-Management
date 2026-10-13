import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@epm/contracts";
import { record, scalar } from "@epm/contracts/workflows";
import { useWorkspace } from "../app/workspace-gate";
import { Facts, readResult } from "./reads";

export function reporterProblem(values: Record<string, unknown>) {
  const reporter = record(values.reporter);
  const historicalFields =
    reporter.historicalSelectionConfirmed != null || reporter.historicalSelectionReason != null;
  if (!["owner", "tenant", "manager", "staff"].includes(scalar(reporter.role)))
    return "Select a reporter role.";
  if (!["party", "local_operator"].includes(scalar(reporter.subjectKind)))
    return "Select a reporter subject.";
  if (
    (reporter.role === "manager" || reporter.role === "staff") &&
    reporter.subjectKind !== "local_operator"
  )
    return "Manager and staff use Local operator in this MVP.";
  if (reporter.role === "tenant" && reporter.subjectKind !== "party")
    return "Tenant reporters require an existing Party.";
  if (reporter.subjectKind === "party" && !reporter.partyId)
    return "Select the existing reporter Party.";
  if (reporter.subjectKind === "local_operator" && (reporter.partyId || historicalFields))
    return "Local operator attribution cannot include Party or historical-selection fields.";
  if (
    historicalFields &&
    !(
      reporter.historicalSelectionConfirmed === true &&
      scalar(reporter.historicalSelectionReason, "").trim()
    )
  )
    return "Historical selection requires explicit confirmation and a reason.";
  return undefined;
}

export function ReporterContext({
  values,
  source,
  locked,
  onChange,
}: {
  values: Record<string, unknown>;
  source: Record<string, unknown>;
  locked: boolean;
  onChange: (values: Record<string, unknown>) => void;
}) {
  const { scope } = useWorkspace();
  const [input, setInput] = useState("");
  const [search, setSearch] = useState("");
  const [historical, setHistorical] = useState(false);
  const reporter = record(values.reporter),
    partyId = scalar(reporter.partyId, "");
  const parties = useQuery({
    queryKey: scope.key("reporter-parties", search, historical),
    enabled: reporter.subjectKind === "party",
    queryFn: async ({ signal }) =>
      readResult(
        await api.GET("/api/parties/selection", {
          signal,
          params: {
            query: { search: search || undefined, includeArchived: historical, limit: 25 },
          },
        }),
      ),
  });
  const party = useQuery({
    queryKey: scope.key("reporter-current-party", partyId),
    enabled: reporter.subjectKind === "party" && !!partyId,
    queryFn: async ({ signal }) =>
      readResult(
        await api.GET("/api/parties/{party_id}", {
          signal,
          params: { path: { party_id: partyId } },
        }),
      ),
  });
  const problem = reporterProblem(values);
  return (
    <section aria-label="Reporter attribution review">
      <h3>Who reported this issue?</h3>
      <Facts
        value={source.reporter}
        fields={["role", "subjectKind", "partyId", "displayName", "currentPartyState"]}
      />
      <p>
        Attribution is a contextual assertion, not a global Party or authorization role.
        Manager/staff use Local operator; owner may use a Party or eligible self-owner Local
        operator. Tenant requires a Party with eligible lease occupancy and participation.
      </p>
      <p>
        The server validates relationships on the Property-local reported date, not today. For a
        Space issue the tenant must occupy that exact Space; a Property issue permits participation
        in any of its Spaces. Draft/void leases and dates outside occupancy or end-exclusive
        participant boundaries are not eligible.
      </p>
      <p>
        Reported instant used for validation: {scalar(source.reportedAtUtc ?? values.reportedAtUtc)}{" "}
        · {scalar(source.reportedTimezone, "Property IANA time zone")}. A correction keeps the
        original report date and does not rewrite linked Communications, Tasks or evidence.
      </p>
      {reporter.subjectKind === "party" && (
        <>
          <label>
            Find reporter by name
            <input
              maxLength={200}
              disabled={locked}
              value={input}
              onChange={(event) => setInput(event.target.value)}
            />
          </label>
          <button type="button" disabled={locked} onClick={() => setSearch(input.trim())}>
            Search reporter identities
          </button>
          <label>
            <input
              type="checkbox"
              disabled={locked}
              checked={historical}
              onChange={(event) => setHistorical(event.target.checked)}
            />
            Show archived identities for a backdated report
          </label>
          <p>
            At most 25 identities are shown. A name/role match is not proof of ownership or tenancy;
            relationship validation remains server-owned.
          </p>
          {parties.error && (
            <p role="alert">Reporter selection unavailable: {parties.error.message}</p>
          )}
          {parties.data?.items.map((item) => (
            <button
              type="button"
              key={item.id}
              disabled={locked}
              onClick={() =>
                onChange({
                  ...values,
                  reporter: {
                    role: reporter.role,
                    subjectKind: "party",
                    partyId: item.id,
                    ...(item.archivedAt ? { historicalSelectionConfirmed: false } : {}),
                  },
                })
              }
            >
              Use {item.displayName} as reporter{item.archivedAt ? " (archived)" : ""}
            </button>
          ))}
          {party.error && <p role="alert">Reporter identity unavailable: {party.error.message}</p>}
          {party.data && (
            <p>
              Selected identity: {party.data.displayName} ·{" "}
              {party.data.archivedAt
                ? "Archived — backdated relationship, historical confirmation and reason required; no records will be restored"
                : "Active"}
              . The server retains its name snapshot.
            </p>
          )}
        </>
      )}
      {problem && <p role="alert">{problem}</p>}
      <p>
        Reporter identity and historical/correction reasons are sensitive contextual history,
        redacted from general activity. Communication participants are separate: a Party reporter
        can be explicitly prefilled, but Local operator never creates a fake Party.
      </p>
    </section>
  );
}
