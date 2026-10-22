import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@epm/contracts";
import { record, scalar } from "@epm/contracts/workflows";
import { useWorkspace } from "../app/workspace-gate";
import { readResult } from "./reads";

export function reporterChanged(values: Record<string, unknown>, original: unknown) {
  const current = record(values.reporter),
    prior = record(original);
  return ["role", "subjectKind", "partyId"].some(
    (key) => scalar(current[key], "") !== scalar(prior[key], ""),
  );
}

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
    return "Select You when you are reporting as a manager or staff member.";
  if (reporter.role === "tenant" && reporter.subjectKind !== "party")
    return "Choose the tenant reporting this issue.";
  if (reporter.subjectKind === "party" && !reporter.partyId)
    return "Select the person reporting this issue.";
  if (reporter.subjectKind === "local_operator" && (reporter.partyId || historicalFields))
    return "When you are the reporter, do not select another person.";
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
    <section aria-label="Reporter attribution review" className="maintenance-create-section">
      <h3>Reporter details</h3>
      {Object.keys(record(source.reporter)).length > 0 && (
        <p>
          Currently recorded: {scalar(record(source.reporter).displayName, "Local operator")} ·{" "}
          {scalar(record(source.reporter).role)}
        </p>
      )}
      <p>
        For a manager or staff report, choose Local operator. For an owner or tenant, select the
        person who reported the issue. Their relationship to the property is checked on the date
        recorded for the issue. New issues use the time you save; editing keeps the original time.
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
            Show archived identities
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
                ? "Archived — must have a valid relationship on the issue’s recorded date; historical confirmation and a reason are required"
                : "Active"}
              . The server retains its name snapshot.
            </p>
          )}
        </>
      )}
      {problem && <p role="alert">{problem}</p>}
    </section>
  );
}
